"""Strategi 'disabled': selalu WAIT. Dipakai untuk instrumen yang belum punya strategi
yang lolos uji backtest out-of-sample, agar dashboard tidak menampilkan sinyal yang belum
terbukti."""

from pydantic import BaseModel

from app.strategies.base import Action, Decision, Strategy, StrategyContext, register


class DisabledParams(BaseModel):
    pass


@register
class DisabledStrategy(Strategy):
    name = "disabled"
    Params = DisabledParams
    min_bars = 1

    def evaluate(self, ctx: StrategyContext) -> Decision:
        return Decision(
            Action.WAIT,
            reasons=[
                f"Sinyal {ctx.instrument.symbol} dinonaktifkan: belum ada strategi yang lolos "
                "uji backtest out-of-sample untuk instrumen ini."
            ],
        )
