"""Peluang historis tiap pola candlestick per instrumen & timeframe: seberapa sering harga
bergerak searah pola dalam HORIZON candle berikutnya.

Dihitung dari candle tersimpan dengan pembacaan yang sama seperti panel pola (tanpa mengintip
masa depan: pola di candle i hanya memakai data sampai candle i), lalu di-cache di Redis
karena memindai setahun M15 butuh beberapa detik."""

import asyncio
import json
import math
from collections.abc import Sequence
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

HORIZON = 1  # candle setelah pola: 1 candle timeframe grafik (M15 → 15 menit ke depan, H4 → 4 jam)
MIN_SAMPLES = 30  # di bawah ini peluang tidak ditampilkan sebagai angka yang bisa dipercaya
MIN_EDGE = 0.55  # arah BUY/SELL baru disimpulkan mulai peluang ini (54% ≈ lempar koin)
MAX_HOLD = 8  # lama tahan yang diuji untuk CLOSE terbaik: 1…8 candle setelah masuk
# Pilih tahan terpendek yang hasilnya >= 90% dari yang terbaik (uang tertahan lebih singkat)
NEAR_BEST = 0.9
MIN_PROFIT_PIPS = 0.5  # rata-rata bersih di bawah ini praktis impas, bukan keuntungan
HISTORY_BARS = 30_000  # ±1 tahun M15
CACHE_TTL_SECONDS = 12 * 3600
CACHE_KEY = "patterns:stats:v2:h{horizon}:{symbol}:{timeframe}"


@dataclass(frozen=True)
class PatternStat:
    samples: int
    hits: int  # harga bergerak searah pola setelah HORIZON candle
    # Per lama tahan k = 1…MAX_HOLD candle setelah masuk (indeks k-1), dari pola yang punya
    # MAX_HOLD candle sesudahnya: rata-rata gerak harga searah pola, dan jumlah yang untung
    moves: tuple[float, ...] = ()
    wins: tuple[int, ...] = ()
    hold_samples: int = 0

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


def is_proven(stat: PatternStat | None) -> bool:
    """Pola terbukti searah teorinya di histori: cukup kejadian, benar >= MIN_EDGE, dan batas
    bawah keyakinan 95% di atas 50%. Aturan yang sama untuk grafik, uji maju, dan pola berjalan."""
    return (
        stat is not None
        and stat.samples >= MIN_SAMPLES
        and stat.rate >= MIN_EDGE
        and wilson_lower(stat.hits, stat.samples) > 0.5
    )


@dataclass(frozen=True)
class ExitPlan:
    hold: int  # CLOSE setelah sekian candle sejak masuk
    pips: float  # rata-rata hasil bersih per transaksi setelah spread
    win_rate: float  # bagian kejadian yang untung (sebelum spread)
    samples: int


def best_exit(stat: PatternStat | None, pip_size: float, spread_pips: float) -> ExitPlan | None:
    """CLOSE dengan rata-rata keuntungan terbesar di histori, dari lama tahan 1…MAX_HOLD candle.
    Bila beberapa hampir sama, ambil yang terpendek (uang tidak tertahan lama). None bila tidak
    ada lama tahan yang rata-ratanya untung setelah spread, atau datanya terlalu sedikit."""
    if stat is None or not stat.moves:
        return None
    net = [m / pip_size - spread_pips for m in stat.moves]
    return choose_hold(net, stat.wins, stat.hold_samples)


def choose_hold(net: Sequence[float], wins: Sequence[int], samples: int) -> ExitPlan | None:
    """`net[k-1]` = rata-rata hasil bersih (pip) bila CLOSE setelah k candle, `wins[k-1]` =
    jumlah kejadian yang untung. Ambil lama tahan terpendek yang >= NEAR_BEST dari terbaik."""
    if samples < MIN_SAMPLES or not net:
        return None
    top = max(net)
    if top < MIN_PROFIT_PIPS:
        return None
    k = next(i for i, v in enumerate(net) if v >= top * NEAR_BEST)
    return ExitPlan(
        hold=k + 1,
        pips=round(net[k], 1),
        win_rate=round(wins[k] / samples, 3),
        samples=samples,
    )


def compute_pattern_stats(df: pd.DataFrame, horizon: int = HORIZON) -> dict[str, PatternStat]:
    """`df` berisi indikator. Hanya pola berarah (bukan Spinning Top) yang dihitung."""
    close = df["close"].to_numpy()
    position = {t: i for i, t in enumerate(df.index)}
    counts: dict[str, tuple[int, int]] = {}
    paths: dict[str, list[list[float]]] = {}
    for t, read in scan_patterns(df, len(df), row_trend):
        bias, i = read.pattern.bias, position[t]
        if not bias or i + horizon >= len(close):
            continue
        n, hits = counts.get(read.pattern.name, (0, 0))
        counts[read.pattern.name] = (n + 1, hits + int((close[i + horizon] - close[i]) * bias > 0))
        if i + MAX_HOLD < len(close):
            moves = [float((close[i + k] - close[i]) * bias) for k in range(1, MAX_HOLD + 1)]
            paths.setdefault(read.pattern.name, []).append(moves)
    stats: dict[str, PatternStat] = {}
    for name, (n, hits) in counts.items():
        rows = paths.get(name, [])
        stats[name] = PatternStat(
            n,
            hits,
            moves=tuple(sum(r[k] for r in rows) / len(rows) for k in range(MAX_HOLD))
            if rows
            else (),
            wins=tuple(sum(r[k] > 0 for r in rows) for k in range(MAX_HOLD)) if rows else (),
            hold_samples=len(rows),
        )
    return stats


def stat_from_json(v: dict) -> PatternStat:
    return PatternStat(
        v["samples"],
        v["hits"],
        moves=tuple(v.get("moves", ())),
        wins=tuple(v.get("wins", ())),
        hold_samples=v.get("hold_samples", 0),
    )


async def get_pattern_stats(
    session: AsyncSession, redis: Redis, symbol: str, timeframe: Timeframe, *, refresh: bool = False
) -> dict[str, PatternStat]:
    """Dari cache Redis; `refresh` memaksa hitung ulang (dipakai worker untuk pemanasan)."""
    key = CACHE_KEY.format(horizon=HORIZON, symbol=symbol, timeframe=timeframe.value)
    if not refresh and (raw := await redis.get(key)):
        return {name: stat_from_json(v) for name, v in json.loads(raw).items()}
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
