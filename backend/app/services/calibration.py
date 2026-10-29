"""Kalibrasi harga: menyesuaikan harga feed ke harga yang tampil di aplikasi broker."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.instruments import Instrument
from app.data.providers.base import DataProvider
from app.db.models import InstrumentSetting
from app.repositories import instrument_settings as settings_repo

# Selisih > 2% hampir pasti salah ketik / salah instrumen
MAX_OFFSET_RATIO = 0.02


class CalibrationError(ValueError):
    pass


def compute_offset(broker_price: float, feed_price: float, digits: int) -> float:
    """Offset yang ditambahkan ke harga feed agar sama dengan harga broker."""
    offset = round(broker_price - feed_price, digits)
    if abs(offset) > feed_price * MAX_OFFSET_RATIO:
        raise CalibrationError(
            f"Selisih {offset} terlalu besar dibanding harga feed {feed_price}. "
            "Periksa kembali instrumen dan harga yang dimasukkan."
        )
    return offset


def adjust_price(price: float, offset: float, digits: int) -> float:
    return round(price + offset, digits)


async def calibrate(
    session: AsyncSession,
    provider: DataProvider,
    instrument: Instrument,
    broker_price: float,
) -> InstrumentSetting:
    quote = await provider.fetch_price(instrument)
    offset = compute_offset(broker_price, quote.price, instrument.digits)

    setting = await settings_repo.get_or_create(session, instrument.symbol)
    setting.price_offset = offset
    setting.broker_price = broker_price
    setting.feed_price = quote.price
    setting.calibrated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(setting)
    return setting


async def reset_calibration(session: AsyncSession, instrument: Instrument) -> InstrumentSetting:
    setting = await settings_repo.get_or_create(session, instrument.symbol)
    setting.price_offset = 0.0
    setting.broker_price = None
    setting.feed_price = None
    setting.calibrated_at = None
    await session.commit()
    await session.refresh(setting)
    return setting
