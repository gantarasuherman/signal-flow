"""Registry instrumen yang dibaca dari config/instruments.yaml."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings


class Instrument(BaseModel):
    symbol: str = Field(pattern=r"^[A-Z0-9]{3,12}$")
    provider_symbol: str
    name: str
    asset_class: Literal["forex", "metal", "index", "crypto", "commodity"]
    pip_size: float = Field(gt=0)
    digits: int = Field(ge=0, le=8)
    contract_size: float = Field(gt=0)
    quote_currency: str = Field(min_length=3, max_length=3)
    typical_spread_pips: float = Field(ge=0)
    slippage_pips: float = Field(default=0.0, ge=0)
    signal_validity_pips: float = Field(gt=0)
    enabled: bool = True

    def round_price(self, price: float) -> float:
        return round(price, self.digits)


class InstrumentsFile(BaseModel):
    instruments: list[Instrument]

    @field_validator("instruments")
    @classmethod
    def _unique_symbols(cls, items: list[Instrument]) -> list[Instrument]:
        symbols = [item.symbol for item in items]
        duplicates = {s for s in symbols if symbols.count(s) > 1}
        if duplicates:
            raise ValueError(f"Simbol instrumen duplikat: {sorted(duplicates)}")
        return items


def load_instruments(path: Path) -> list[Instrument]:
    if not path.exists():
        raise FileNotFoundError(f"File instrumen tidak ditemukan: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return InstrumentsFile.model_validate(raw).instruments


@lru_cache
def get_instruments() -> dict[str, Instrument]:
    """Instrumen aktif, di-key berdasarkan simbol."""
    items = load_instruments(get_settings().instruments_file)
    return {item.symbol: item for item in items if item.enabled}


def get_instrument(symbol: str) -> Instrument | None:
    return get_instruments().get(symbol.upper())
