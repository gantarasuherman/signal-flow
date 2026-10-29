"""Konfigurasi analisis dari config/strategies.yaml."""

from functools import cache, lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.analysis.filters import FilterConfig
from app.analysis.news import NewsCalendar, YamlNewsCalendar
from app.analysis.profit_lock import ProfitCloseConfig
from app.core.config import get_settings
from app.strategies import Strategy, create_strategy


class InstrumentStrategy(BaseModel):
    """Override strategi untuk satu instrumen."""

    strategy: str
    params: dict[str, Any] = Field(default_factory=dict)


class AnalysisConfig(BaseModel):
    active: str = "trend_pullback"
    strategies: dict[str, dict[str, Any]] = Field(default_factory=dict)
    instruments: dict[str, InstrumentStrategy] = Field(default_factory=dict)
    max_hold_candles: int = Field(default=32, ge=1)
    profit_close: ProfitCloseConfig = Field(default_factory=ProfitCloseConfig)
    entry_valid_minutes: int = Field(default=45, ge=1)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    # Instrumen yang mendapat sinyal AI (None = semua). Dibatasi berdasarkan hasil ai-eval.
    ai_instruments: list[str] | None = None

    def ai_enabled_for(self, symbol: str) -> bool:
        return self.ai_instruments is None or symbol.upper() in self.ai_instruments

    def spec_for(self, symbol: str) -> tuple[str, dict[str, Any]]:
        """(nama strategi, parameter lengkap) untuk instrumen: bawaan + override."""
        override = self.instruments.get(symbol.upper())
        name = override.strategy if override else self.active
        params = {**self.strategies.get(name, {}), **(override.params if override else {})}
        return name, params


def config_dir() -> Path:
    return get_settings().instruments_file.parent


def load_analysis_config(path: Path) -> AnalysisConfig:
    if not path.exists():
        return AnalysisConfig()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AnalysisConfig.model_validate(raw)


@lru_cache
def get_analysis_config() -> AnalysisConfig:
    return load_analysis_config(config_dir() / "strategies.yaml")


@cache
def get_strategy_for(symbol: str) -> Strategy:
    name, params = get_analysis_config().spec_for(symbol)
    return create_strategy(name, params)


@lru_cache
def get_news_calendar() -> NewsCalendar:
    return YamlNewsCalendar(config_dir() / "news_events.yaml")
