"""Perhitungan jarak pip, nilai pip, dan saran ukuran lot (akun dalam USD)."""

import math

from app.core.instruments import Instrument

LOT_STEP = 0.01
MIN_LOT = 0.01


def price_to_pips(distance: float, instrument: Instrument) -> float:
    return round(abs(distance) / instrument.pip_size, 1)


def pip_value_per_lot_usd(instrument: Instrument, price: float) -> float | None:
    """Nilai 1 pip untuk 1 lot dalam USD. None bila butuh kurs silang yang tidak tersedia."""
    pip_value_quote = instrument.pip_size * instrument.contract_size
    if instrument.quote_currency == "USD":
        return pip_value_quote
    if instrument.symbol.startswith("USD") and price > 0:
        return pip_value_quote / price
    return None


def suggest_lot(
    instrument: Instrument,
    *,
    capital: float,
    risk_percent: float,
    entry: float,
    stop_loss: float,
) -> float | None:
    """Lot sehingga kerugian saat kena SL ≈ modal × risiko%. Dibulatkan KE BAWAH ke 0.01."""
    sl_pips = abs(entry - stop_loss) / instrument.pip_size
    pip_value = pip_value_per_lot_usd(instrument, entry)
    if capital <= 0 or risk_percent <= 0 or sl_pips <= 0 or pip_value is None:
        return None
    raw = capital * risk_percent / 100 / (sl_pips * pip_value)
    lots = math.floor(raw / LOT_STEP + 1e-9) * LOT_STEP
    return round(max(lots, 0.0), 2) if lots >= MIN_LOT else 0.0
