"""Deteksi candle bolong (hilang padahal pasar buka)."""

from collections.abc import Iterable
from datetime import datetime
from itertools import pairwise

from app.core.market_hours import candle_has_trading
from app.core.timeframes import Timeframe

MAX_REPORTED_GAPS = 500


def find_gaps(
    open_times: Iterable[datetime], timeframe: Timeframe, asset_class: str
) -> list[datetime]:
    missing: list[datetime] = []
    for prev, nxt in pairwise(sorted(open_times)):
        t = prev + timeframe.delta
        while t < nxt:
            if candle_has_trading(asset_class, t, timeframe):
                missing.append(t)
                if len(missing) >= MAX_REPORTED_GAPS:
                    return missing
            t += timeframe.delta
    return missing
