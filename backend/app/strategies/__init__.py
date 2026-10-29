"""Registry strategi. Impor modul strategi baru di sini agar terdaftar."""

from app.strategies import (  # noqa: F401
    ai_groq,
    candle_pattern,
    disabled,
    donchian_breakout,
    session_breakout,
    setup_trend,
    trend_pullback,
)
from app.strategies.base import (
    Action,
    ActiveSignalView,
    Decision,
    Strategy,
    StrategyContext,
    available_strategies,
    confidence_label,
    create_strategy,
)

__all__ = [
    "Action",
    "ActiveSignalView",
    "Decision",
    "Strategy",
    "StrategyContext",
    "available_strategies",
    "confidence_label",
    "create_strategy",
]
