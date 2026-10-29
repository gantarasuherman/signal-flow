"""Peluang historis tiap pola candlestick per instrumen & timeframe: seberapa sering harga
bergerak searah pola dalam HORIZON candle berikutnya.

Dihitung dari candle tersimpan dengan pembacaan yang sama seperti panel pola (tanpa mengintip
masa depan: pola di candle i hanya memakai data sampai candle i), lalu di-cache di Redis
karena memindai setahun M15 butuh beberapa detik."""

import asyncio
import json
import math
from dataclasses import asdict, dataclass

import pandas as pd
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.indicators import compute_indicators
from app.core.timeframes import Timeframe
from app.repositories import candles as candles_repo
from app.services.signal_engine import candles_to_frame
from app.strategies.common import row_trend
from app.strategies.patterns import scan_patterns

HORIZON = 4  # candle setelah pola
MIN_SAMPLES = 30  # di bawah ini peluang tidak ditampilkan sebagai angka yang bisa dipercaya
MIN_EDGE = 0.55  # arah BUY/SELL baru disimpulkan mulai peluang ini (54% ≈ lempar koin)
HISTORY_BARS = 30_000  # ±1 tahun M15
CACHE_TTL_SECONDS = 12 * 3600
CACHE_KEY = "patterns:stats:{symbol}:{timeframe}"


@dataclass(frozen=True)
class PatternStat:
    samples: int
    hits: int  # harga bergerak searah pola setelah HORIZON candle

    @property
    def rate(self) -> float:
        return self.hits / self.samples if self.samples else 0.0


def wilson_lower(hits: int, samples: int, z: float = 1.96) -> float:
    """Batas bawah interval keyakinan 95% untuk proporsi (hindari yakin pada sampel kecil)."""
    if samples == 0:
        return 0.0
    p = hits / samples
    centre = p + z * z / (2 * samples)
    margin = z * math.sqrt(p * (1 - p) / samples + z * z / (4 * samples * samples))
    return (centre - margin) / (1 + z * z / samples)


def compute_pattern_stats(df: pd.DataFrame, horizon: int = HORIZON) -> dict[str, PatternStat]:
    """`df` berisi indikator. Hanya pola berarah (bukan Spinning Top) yang dihitung."""
    close = df["close"].to_numpy()
    position = {t: i for i, t in enumerate(df.index)}
    counts: dict[str, tuple[int, int]] = {}
    for t, read in scan_patterns(df, len(df), row_trend):
        bias, i = read.pattern.bias, position[t]
        if not bias or i + horizon >= len(close):
            continue
        n, hits = counts.get(read.pattern.name, (0, 0))
        counts[read.pattern.name] = (n + 1, hits + int((close[i + horizon] - close[i]) * bias > 0))
    return {name: PatternStat(n, hits) for name, (n, hits) in counts.items()}


async def get_pattern_stats(
    session: AsyncSession, redis: Redis, symbol: str, timeframe: Timeframe, *, refresh: bool = False
) -> dict[str, PatternStat]:
    """Dari cache Redis; `refresh` memaksa hitung ulang (dipakai worker untuk pemanasan)."""
    key = CACHE_KEY.format(symbol=symbol, timeframe=timeframe.value)
    if not refresh and (raw := await redis.get(key)):
        return {name: PatternStat(**v) for name, v in json.loads(raw).items()}
    rows = await candles_repo.get_candles(session, symbol, timeframe, limit=HISTORY_BARS)
    stats: dict[str, PatternStat] = {}
    if len(rows) > HORIZON + 3:
        df = compute_indicators(candles_to_frame(rows))
        stats = await asyncio.to_thread(compute_pattern_stats, df)
    payload = {name: asdict(s) for name, s in stats.items()}
    # Histori masih pendek (mis. M1/M5 baru terkumpul): hitung ulang lebih cepat
    ttl = CACHE_TTL_SECONDS if len(rows) >= 2000 else 3600
    await redis.set(key, json.dumps(payload), ex=ttl)
    return stats
