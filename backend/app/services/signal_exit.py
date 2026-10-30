"""Perkiraan waktu CLOSE terbaik untuk sinyal BUY/SELL strategi.

Strategi instrumen di-replay pada histori (logika sama dengan worker live), lalu tiap transaksi
historis dinilai seolah ditutup setelah k = 1…max_hold_candles candle M15, dengan SL/TP tetap
terpasang (SL/TP yang tersentuh lebih dulu menentukan hasil). Lama tahan dengan rata-rata
hasil bersih terbesar menjadi saran CLOSE. Dibandingkan juga dengan mengikuti aturan keluar
strategi apa adanya, agar terlihat apakah saran waktu itu memang lebih baik.

Replay setahun butuh puluhan detik, jadi dihitung worker dan di-cache di Redis; API hanya
membaca cache."""

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

import pandas as pd
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.config import AnalysisConfig, get_analysis_config
from app.analysis.lifecycle import (
    TrailingStopConfig,
    check_price_exit,
    exit_price_at_market,
    result_pips,
)
from app.analysis.replay import ReplayTrade, replay
from app.backtest.runner import InstrumentData, load_dataset
from app.core.instruments import Instrument, get_instruments
from app.core.timeframes import Timeframe
from app.services.pattern_stats import ExitPlan, choose_hold
from app.strategies import Action, create_strategy

logger = logging.getLogger(__name__)

HISTORY_DAYS = 365
CACHE_KEY = "signals:exit:v1:{symbol}:{strategy}"
CACHE_TTL_SECONDS = 36 * 3600


@dataclass(frozen=True)
class ExitProfile:
    net: list[float]  # rata-rata hasil bersih (pip) bila CLOSE setelah k candle (indeks k-1)
    wins: list[int]
    samples: int
    strategy_pips: float  # rata-rata bila mengikuti aturan keluar strategi apa adanya


def exit_profile(
    trades: list[ReplayTrade],
    m15: pd.DataFrame,
    instrument: Instrument,
    spread_pips: float,
    slippage_pips: float,
    max_hold: int,
    trailing: TrailingStopConfig | None = None,
) -> ExitProfile:
    spread = spread_pips * instrument.pip_size
    closes = m15["close"]
    sums = [0.0] * max_hold
    wins = [0] * max_hold
    own: list[float] = []
    for t in trades:
        after = m15[m15.index > t.entry_time].iloc[:max_hold]
        if len(after) < max_hold or t.result_pips is None:
            continue  # histori belum cukup panjang / masih terbuka
        action = Action(t.action)
        hit = check_price_exit(
            action, t.stop_loss, t.take_profit, after, spread, entry=t.entry, trailing=trailing
        )
        hit_at = after.index.get_loc(pd.Timestamp(hit.time)) if hit else max_hold
        for k in range(max_hold):
            price = (
                hit.price
                if hit and k >= hit_at
                else exit_price_at_market(action, float(closes[after.index[k]]), spread)
            )
            pips = float(result_pips(action, t.entry, price, spread, instrument.pip_size))
            pips -= 2 * slippage_pips
            sums[k] += pips
            wins[k] += int(pips > 0)
        own.append(float(t.result_pips) - 2 * slippage_pips)
    n = len(own)
    return ExitProfile(
        net=[round(s / n, 2) for s in sums] if n else [],
        wins=wins if n else [],
        samples=n,
        strategy_pips=round(sum(own) / n, 2) if n else 0.0,
    )


def compute_exit_profile(
    data: InstrumentData, strategy_name: str, params: dict, cfg: AnalysisConfig, start: datetime
) -> ExitProfile:
    f = data.frames
    trades = replay(
        create_strategy(strategy_name, params),
        data.instrument,
        f[Timeframe.M15],
        f[Timeframe.H1],
        f[Timeframe.H4],
        spread_pips=data.spread_pips,
        filters=cfg.filters,
        max_hold_candles=cfg.max_hold_candles,
        profit_close=cfg.profit_close,
        trailing=cfg.trailing_stop,
        start=start,
    )
    return exit_profile(
        trades,
        f[Timeframe.M15],
        data.instrument,
        data.spread_pips,
        data.slippage_pips,
        cfg.max_hold_candles,
        cfg.trailing_stop,
    )


async def refresh_signal_exits(session: AsyncSession, redis: Redis) -> None:
    """Hitung ulang profil CLOSE untuk strategi tiap instrumen (dipanggil worker)."""
    cfg = get_analysis_config()
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    start = end - timedelta(days=HISTORY_DAYS)
    for symbol, instrument in get_instruments().items():
        name, params = cfg.spec_for(symbol)
        try:
            data = await load_dataset(session, instrument, start, end)
            if len(data.frames[Timeframe.M15]) < 500:
                continue
            profile = await asyncio.to_thread(compute_exit_profile, data, name, params, cfg, start)
        except Exception:
            logger.exception("%s: gagal menghitung CLOSE terbaik strategi %s", symbol, name)
            continue
        key = CACHE_KEY.format(symbol=symbol, strategy=name)
        await redis.set(key, json.dumps(asdict(profile)), ex=CACHE_TTL_SECONDS)
        logger.info("CLOSE terbaik %s/%s: %d transaksi", symbol, name, profile.samples)


async def cached_exit_profile(redis: Redis, symbol: str, strategy: str) -> ExitProfile | None:
    raw = await redis.get(CACHE_KEY.format(symbol=symbol, strategy=strategy))
    return ExitProfile(**json.loads(raw)) if raw else None


def best_close(profile: ExitProfile | None) -> ExitPlan | None:
    return choose_hold(profile.net, profile.wins, profile.samples) if profile else None
