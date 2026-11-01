"""Metrik kinerja sinyal. Dipakai untuk backtest dan untuk statistik sinyal live.

Satuan utama adalah R (kelipatan risiko): +2R = untung dua kali jarak SL. Dengan risiko %
yang tetap per sinyal, R sebanding dengan uang, sehingga emas & forex bisa digabung.
"""

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class TradeResult:
    symbol: str
    action: str
    entry_time: datetime
    exit_time: datetime
    status: str  # HIT_TP / HIT_SL / CLOSED
    result_pips: float  # bersih setelah spread & slippage
    risk_pips: float  # jarak SL + spread (kerugian bila kena SL)
    planned_rr: float | None = None
    close_reason: str | None = None

    @property
    def r(self) -> float:
        return self.result_pips / self.risk_pips if self.risk_pips > 0 else 0.0


@dataclass
class Metrics:
    trades: int
    wins: int
    losses: int
    win_rate: float | None
    net_pips: float
    avg_win_pips: float | None
    avg_loss_pips: float | None
    total_r: float
    expectancy_r: float | None
    profit_factor: float | None
    avg_rr_planned: float | None
    avg_rr_realized: float | None
    max_drawdown_r: float
    max_drawdown_pct: float
    return_pct: float
    sharpe: float | None
    by_status: dict[str, int]
    # Total keuntungan (siklus untung) dan kerugian (siklus rugi, negatif) secara terpisah
    win_pips: float = 0.0
    loss_pips: float = 0.0
    win_r: float = 0.0
    loss_r: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _weekdays(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def compute_metrics(
    trades: Sequence[TradeResult],
    *,
    risk_percent: float = 1.0,
    period: tuple[datetime, datetime] | None = None,
) -> Metrics:
    ordered = sorted(trades, key=lambda t: t.exit_time)
    wins = [t for t in ordered if t.result_pips > 0]
    losses = [t for t in ordered if t.result_pips <= 0]
    rs = [t.r for t in ordered]

    gross_win = sum(r for r in rs if r > 0)
    gross_loss = -sum(r for r in rs if r < 0)
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None

    # Drawdown pada kurva R kumulatif dan pada modal yang dimajemukkan (risiko % per sinyal)
    cum = peak = max_dd_r = 0.0
    equity = equity_peak = 1.0
    max_dd_pct = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        max_dd_r = max(max_dd_r, peak - cum)
        equity *= 1 + risk_percent / 100 * r
        equity_peak = max(equity_peak, equity)
        max_dd_pct = max(max_dd_pct, (equity_peak - equity) / equity_peak * 100)

    # Sharpe tahunan dari R harian (hari kerja tanpa trade = 0)
    sharpe = None
    if ordered:
        start = (period[0] if period else ordered[0].exit_time).astimezone(UTC).date()
        end = (period[1] if period else ordered[-1].exit_time).astimezone(UTC).date()
        daily: dict[date, float] = defaultdict(float)
        for t in ordered:
            daily[t.exit_time.astimezone(UTC).date()] += t.r
        series = [daily.get(d, 0.0) for d in _weekdays(start, end)]
        if len(series) > 1:
            mean = sum(series) / len(series)
            std = math.sqrt(sum((x - mean) ** 2 for x in series) / (len(series) - 1))
            sharpe = round(mean / std * math.sqrt(252), 2) if std > 0 else None

    planned = [t.planned_rr for t in ordered if t.planned_rr]
    avg_win_r = sum(t.r for t in wins) / len(wins) if wins else None
    avg_loss_r = sum(t.r for t in losses) / len(losses) if losses else None
    by_status: dict[str, int] = defaultdict(int)
    for t in ordered:
        by_status[t.status] += 1

    def avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 1) if values else None

    return Metrics(
        trades=len(ordered),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / len(ordered) * 100, 1) if ordered else None,
        net_pips=round(sum(t.result_pips for t in ordered), 1),
        avg_win_pips=avg([t.result_pips for t in wins]),
        avg_loss_pips=avg([t.result_pips for t in losses]),
        total_r=round(sum(rs), 2),
        expectancy_r=round(sum(rs) / len(rs), 3) if rs else None,
        profit_factor=profit_factor,
        avg_rr_planned=round(sum(planned) / len(planned), 2) if planned else None,
        avg_rr_realized=round(avg_win_r / abs(avg_loss_r), 2)
        if avg_win_r is not None and avg_loss_r
        else None,
        max_drawdown_r=round(max_dd_r, 2),
        max_drawdown_pct=round(max_dd_pct, 2),
        return_pct=round((equity - 1) * 100, 2),
        sharpe=sharpe,
        by_status=dict(by_status),
        win_pips=round(sum(t.result_pips for t in wins), 1),
        loss_pips=round(sum(t.result_pips for t in losses), 1),
        win_r=round(gross_win, 2),
        loss_r=round(-gross_loss, 2),
    )


def equity_curve(
    trades: Sequence[TradeResult], risk_percent: float = 1.0, max_points: int = 400
) -> list[dict[str, Any]]:
    """Kurva modal (100 = awal) per trade, dipadatkan agar ringan untuk grafik."""
    ordered = sorted(trades, key=lambda t: t.exit_time)
    by_time: dict[int, float] = {}  # grafik butuh waktu unik: ambil nilai terakhir per waktu
    equity = 100.0
    for t in ordered:
        equity *= 1 + risk_percent / 100 * t.r
        by_time[int(t.exit_time.timestamp())] = round(equity, 3)
    points = [{"time": time, "equity": value} for time, value in by_time.items()]
    if len(points) > max_points:
        step = len(points) / max_points
        points = [points[int(i * step)] for i in range(max_points)] + [points[-1]]
    return points
