"""Replay strategi candle demi candle pada data historis.

Pada setiap candle M15 hanya data yang sudah tutup pada saat itu yang terlihat (H1/H4 yang
belum tutup tidak dipakai), sehingga hasilnya sama dengan yang akan terjadi secara live.
"""

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from app.analysis.engine import step
from app.analysis.filters import FilterConfig, volatility_block, weekend_close_block
from app.analysis.indicators import compute_indicators
from app.analysis.lifecycle import TrailingStopConfig
from app.analysis.profit_lock import ProfitCloseConfig
from app.core.instruments import Instrument
from app.core.market_hours import candle_has_trading
from app.core.timeframes import Timeframe
from app.strategies.base import ActiveSignalView, Strategy, StrategyContext


@dataclass
class ReplayTrade:
    action: str
    entry_time: datetime
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float
    exit_time: datetime | None = None
    exit_price: float | None = None
    status: str = "ACTIVE"
    result_pips: float | None = None
    close_reason: str | None = None


def replay(
    strategy: Strategy,
    instrument: Instrument,
    m15: pd.DataFrame,
    h1: pd.DataFrame,
    h4: pd.DataFrame,
    *,
    spread_pips: float,
    filters: FilterConfig,
    max_hold_candles: int,
    profit_close: ProfitCloseConfig | None = None,
    trailing: TrailingStopConfig | None = None,
    start: datetime | None = None,
) -> list[ReplayTrade]:
    cfg = strategy.indicator_config
    m15i, h1i, h4i = (compute_indicators(df, cfg) for df in (m15, h1, h4))
    h1_close = h1i.index + Timeframe.H1.delta
    h4_close = h4i.index + Timeframe.H4.delta
    spread_price = spread_pips * instrument.pip_size

    trades: list[ReplayTrade] = []
    open_trade: ReplayTrade | None = None
    active: ActiveSignalView | None = None

    for i in range(strategy.min_bars, len(m15i)):
        open_time = m15i.index[i]
        if start is not None and open_time < start:
            continue
        # Pengaman: provider kadang mengirim candle saat pasar tutup (akhir pekan)
        if not candle_has_trading(instrument.asset_class, open_time, Timeframe.M15):
            continue
        now = (open_time + Timeframe.M15.delta).to_pydatetime()
        j = int(h1_close.searchsorted(now, side="right"))
        k = int(h4_close.searchsorted(now, side="right"))
        if j < strategy.min_bars or k < strategy.min_bars:
            continue

        window = m15i.iloc[: i + 1]
        ctx = StrategyContext(
            instrument=instrument,
            now=now,
            m15=window,
            h1=h1i.iloc[:j],
            h4=h4i.iloc[:k],
            spread_price=spread_price,
            active=active,
        )
        blocked = [
            r
            for r in (
                volatility_block(window, filters),
                weekend_close_block(instrument, now, filters),
            )
            if r
        ]
        result = step(strategy, ctx, blocked, max_hold_candles, profit_close, trailing)

        if result.exit and open_trade:
            open_trade.exit_time = result.exit.time
            open_trade.exit_price = result.exit.price
            open_trade.status = result.exit.status.value
            open_trade.result_pips = result.exit.result_pips
            open_trade.close_reason = result.exit.reason
            open_trade = None
        active = result.still_active

        entry = result.new_entry
        if entry and entry.entry is not None:
            assert entry.stop_loss is not None and entry.take_profit is not None
            open_trade = ReplayTrade(
                action=entry.action.value,
                entry_time=open_time.to_pydatetime(),
                entry=entry.entry,
                stop_loss=entry.stop_loss,
                take_profit=entry.take_profit,
                confidence=entry.confidence,
            )
            trades.append(open_trade)
            active = ActiveSignalView(
                id=len(trades),
                action=entry.action,
                entry=entry.entry,
                stop_loss=entry.stop_loss,
                take_profit=entry.take_profit,
                candle_time=open_time.to_pydatetime(),
            )
    return trades
