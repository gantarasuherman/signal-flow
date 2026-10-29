"""Kontrak plugin strategi.

Menambah strategi baru:
1. Buat modul di app/strategies/, turunkan `Strategy`, isi `name` dan `Params`.
2. Beri dekorator `@register`.
3. Impor modulnya di app/strategies/__init__.py.
4. Pilih di config/strategies.yaml (`active: <name>`).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

import pandas as pd
from pydantic import BaseModel

from app.analysis.indicators import IndicatorConfig
from app.core.instruments import Instrument


class Action(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"
    WAIT = "WAIT"


@dataclass(frozen=True)
class ActiveSignalView:
    """Sinyal BUY/SELL yang masih aktif (dibaca strategi untuk keputusan CLOSE)."""

    id: int
    action: Action
    entry: float
    stop_loss: float
    take_profit: float
    candle_time: datetime


@dataclass
class StrategyContext:
    """Data untuk satu evaluasi. DataFrame berindeks open_time (UTC), berisi kolom OHLC
    + indikator, dan hanya memuat candle yang SUDAH tutup."""

    instrument: Instrument
    now: datetime
    m15: pd.DataFrame
    h1: pd.DataFrame
    h4: pd.DataFrame
    spread_price: float
    active: ActiveSignalView | None = None


@dataclass
class Decision:
    action: Action
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_entry(self) -> bool:
        return self.action in (Action.BUY, Action.SELL)


def confidence_label(score: float) -> str:
    if score >= 0.75:
        return "tinggi"
    if score >= 0.55:
        return "sedang"
    return "rendah"


class Strategy(ABC):
    name: ClassVar[str]
    Params: ClassVar[type[BaseModel]]
    # Jumlah candle minimum per timeframe agar indikator (mis. EMA 200) valid
    min_bars: ClassVar[int] = 250
    # Sumber sinyal: "rule" (strategi aturan, bisa di-backtest) atau "ai" (LLM, eksperimen)
    source: ClassVar[str] = "rule"
    # Rangkai alasan dengan LLM narrator? (sinyal AI sudah membawa alasannya sendiri)
    narrate: ClassVar[bool] = True

    def __init__(self, params: BaseModel | dict[str, Any] | None = None) -> None:
        if isinstance(params, BaseModel):
            self.params = params
        else:
            self.params = self.Params.model_validate(params or {})

    @property
    def indicator_config(self) -> IndicatorConfig:
        return IndicatorConfig()

    async def prepare(self, ctx: StrategyContext) -> None:  # noqa: B027
        """Langkah async sebelum `evaluate` (mis. memanggil API). Tidak dipanggil saat replay."""
        return None

    @abstractmethod
    def evaluate(self, ctx: StrategyContext) -> Decision:
        """Keputusan entry untuk candle M15 terakhir: BUY, SELL, atau WAIT."""

    def should_close(self, ctx: StrategyContext, active: ActiveSignalView) -> str | None:
        """Alasan menutup sinyal aktif lebih awal (selain TP/SL/berbalik arah), atau None."""
        return None


_REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    if cls.name in _REGISTRY:
        raise ValueError(f"Strategi {cls.name} sudah terdaftar")
    _REGISTRY[cls.name] = cls
    return cls


def available_strategies() -> list[str]:
    return sorted(_REGISTRY)


def create_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    try:
        cls = _REGISTRY[name]
    except KeyError as exc:
        raise ValueError(
            f"Strategi '{name}' tidak dikenal. Tersedia: {available_strategies()}"
        ) from exc
    return cls(params)
