from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.instruments import load_instruments

REPO_CONFIG_CANDIDATES = [
    Path(__file__).resolve().parents[1] / "config" / "instruments.yaml",  # di dalam container
    Path(__file__).resolve().parents[2] / "config" / "instruments.yaml",  # di repo lokal
]


def test_cors_origins_accepts_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    assert Settings(_env_file=None).cors_origins == ["http://a.test", "http://b.test"]


def test_invalid_timezone_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIMEZONE", "Mars/Olympus")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_repo_instruments_file_is_valid() -> None:
    path = next((p for p in REPO_CONFIG_CANDIDATES if p.exists()), None)
    if path is None:
        pytest.skip("config/instruments.yaml tidak ter-mount")
    symbols = {item.symbol for item in load_instruments(path)}
    assert {"XAUUSD", "EURUSD", "GBPUSD", "USDJPY"} <= symbols


def test_duplicate_symbols_rejected(tmp_path: Path) -> None:
    entry = """
  - symbol: EURUSD
    provider_symbol: EUR/USD
    name: Euro
    asset_class: forex
    pip_size: 0.0001
    digits: 5
    contract_size: 100000
    quote_currency: USD
    typical_spread_pips: 1
    signal_validity_pips: 5
"""
    path = tmp_path / "instruments.yaml"
    path.write_text("instruments:" + entry + entry, encoding="utf-8")
    with pytest.raises(ValidationError, match="duplikat"):
        load_instruments(path)
