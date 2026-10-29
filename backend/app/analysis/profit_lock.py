"""CLOSE "kunci untung": tutup posisi yang sudah untung saat muncul pola candlestick
pembalikan berlawanan arah. Tujuannya keluar di dekat titik untung terbesar, sebelum harga
berbalik menghapus keuntungan (tanpa menunggu TP)."""

from pydantic import BaseModel, Field

from app.analysis.lifecycle import exit_price_at_market
from app.strategies.base import Action, ActiveSignalView, StrategyContext
from app.strategies.common import row_trend
from app.strategies.patterns import read_patterns


class ProfitCloseConfig(BaseModel):
    enabled: bool = True
    min_profit_r: float = Field(
        default=1.0, ge=0, le=10, description="Untung minimal (kelipatan jarak SL) setelah spread"
    )
    min_strength: int = Field(default=2, ge=1, le=3, description="Kekuatan pola lawan minimal")


def profit_lock_reason(
    ctx: StrategyContext, active: ActiveSignalView, cfg: ProfitCloseConfig | None
) -> str | None:
    if cfg is None or not cfg.enabled:
        return None
    d = 1 if active.action is Action.BUY else -1
    bid = float(ctx.m15["close"].iloc[-1])
    exit_price = exit_price_at_market(active.action, bid, ctx.spread_price)
    paid = active.entry + ctx.spread_price if d == 1 else active.entry
    profit = (exit_price - paid) * d
    risk = abs(active.entry - active.stop_loss) or 1e-12
    if profit < cfg.min_profit_r * risk:
        return None
    window = ctx.m15.tail(60)
    reads = [
        r
        for r in read_patterns(window, row_trend(window.iloc[-1]))
        if r.pattern.bias == -d and r.strength >= cfg.min_strength
    ]
    if not reads:
        return None
    best = max(reads, key=lambda r: r.strength)
    pips = profit / ctx.instrument.pip_size
    return (
        f"Ambil untung: pola {best.pattern.name} ({best.pattern.meaning}, {best.note}) muncul "
        f"saat posisi sudah untung ±{pips:.0f} pip ({profit / risk:.1f}R). Kemungkinan untung "
        "terbesar sudah tercapai."
    )
