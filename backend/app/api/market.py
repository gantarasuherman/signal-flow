"""Endpoint instrumen, kalibrasi harga, dan data candle."""

from datetime import UTC, datetime
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.indicators import compute_indicators
from app.api.deps import InstrumentDep, ProviderDep, SessionDep, resolve_instrument
from app.api.patterns import PatternMark, pattern_marks
from app.core.config import get_settings
from app.core.instruments import get_instruments
from app.core.market_hours import is_market_open
from app.core.redis import get_redis
from app.core.timeframes import Timeframe
from app.data.errors import ProviderError
from app.data.providers import PROVIDER_LABELS
from app.repositories import candles as candles_repo
from app.repositories import instrument_settings as settings_repo
from app.services.calibration import CalibrationError, calibrate, reset_calibration
from app.services.candle_sync import refresh_if_stale
from app.services.live_candle import fetch_live
from app.services.signal_engine import candles_to_frame
from app.services.views import CandleOut, InstrumentOut, candle_out, instrument_out


def quota_exhausted_warning(provider_name: str) -> str:
    label = PROVIDER_LABELS.get(provider_name, provider_name)
    return (
        f"Kuota harian {label} habis (reset 00:00 UTC / 07:00 WIB). Menampilkan data tersimpan. "
        "Sumber data bisa diganti di Pengaturan."
    )


router = APIRouter(tags=["market"])


class SettingsUpdate(BaseModel):
    spread_pips: float | None = Field(
        default=None, ge=0, le=1000, description="null = kembali ke spread bawaan"
    )
    price_offset: float | None = Field(default=None, description="Set offset manual")


class CalibrateRequest(BaseModel):
    broker_price: float = Field(gt=0, description="Harga BID (Sell) yang tampil di broker")


class LiveCandleResponse(BaseModel):
    symbol: str
    timeframe: Timeframe
    market_open: bool
    live: CandleOut | None = Field(description="Candle yang sedang berjalan (belum tutup)")
    live_updated_at: datetime | None
    refresh_seconds: int
    warning: str | None


class IndicatorPoint(BaseModel):
    time: int
    value: float


class CandlesResponse(LiveCandleResponse):
    adjusted: bool
    price_offset: float
    candles: list[CandleOut]
    indicators: dict[str, list[IndicatorPoint]] | None = Field(
        default=None,
        description="ema20/ema50/ema200/bb_upper/bb_mid/bb_lower (harga, sudah offset), "
        "rsi, macd, macd_signal, macd_hist",
    )
    patterns: list[PatternMark] | None = Field(
        default=None, description="Pola candlestick berarah per candle (Hammer, Morning Star, ...)"
    )


# Candle tambahan agar EMA 200 sudah 'panas' pada candle pertama yang ditampilkan
INDICATOR_WARMUP = 250
INDICATOR_SERIES = {
    "ema20": ("ema_fast", True),
    "ema50": ("ema_mid", True),
    "ema200": ("ema_slow", True),
    "bb_upper": ("bb_upper", True),
    "bb_mid": ("bb_mid", True),
    "bb_lower": ("bb_lower", True),
    "rsi": ("rsi", False),
    "macd": ("macd", False),
    "macd_signal": ("macd_signal", False),
    "macd_hist": ("macd_hist", False),
}


def indicator_series(
    full: pd.DataFrame, limit: int, offset: float, digits: int
) -> dict[str, list[IndicatorPoint]]:
    df = full.iloc[-limit:]
    times = [int(ts.timestamp()) for ts in df.index]
    out: dict[str, list[IndicatorPoint]] = {}
    for name, (column, is_price) in INDICATOR_SERIES.items():
        points = []
        for t, value in zip(times, df[column], strict=True):
            if pd.isna(value):
                continue
            v = round(float(value) + offset, digits) if is_price else round(float(value), 6)
            points.append(IndicatorPoint(time=t, value=v))
        out[name] = points
    return out


async def _offset(session: AsyncSession, symbol: str, adjusted: bool) -> float:
    if not adjusted:
        return 0.0
    setting = (await settings_repo.get_all(session)).get(symbol)
    return setting.price_offset if setting else 0.0


@router.get("/instruments", response_model=list[InstrumentOut])
async def list_instruments(session: SessionDep) -> list[InstrumentOut]:
    settings_map = await settings_repo.get_all(session)
    now = datetime.now(UTC)
    return [
        instrument_out(inst, settings_map.get(sym), now)
        for sym, inst in sorted(get_instruments().items())
    ]


@router.get("/instruments/{symbol}", response_model=InstrumentOut)
async def get_instrument_detail(instrument: InstrumentDep, session: SessionDep) -> InstrumentOut:
    settings_map = await settings_repo.get_all(session)
    return instrument_out(instrument, settings_map.get(instrument.symbol), datetime.now(UTC))


@router.put("/instruments/{symbol}/settings", response_model=InstrumentOut)
async def update_settings(
    instrument: InstrumentDep, body: SettingsUpdate, session: SessionDep
) -> InstrumentOut:
    setting = await settings_repo.get_or_create(session, instrument.symbol)
    if "spread_pips" in body.model_fields_set:
        setting.spread_pips = body.spread_pips
    if body.price_offset is not None:
        setting.price_offset = round(body.price_offset, instrument.digits)
        setting.broker_price = setting.feed_price = None
        setting.calibrated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(setting)
    return instrument_out(instrument, setting, datetime.now(UTC))


@router.post("/instruments/{symbol}/calibrate", response_model=InstrumentOut)
async def calibrate_instrument(
    instrument: InstrumentDep, body: CalibrateRequest, session: SessionDep, provider: ProviderDep
) -> InstrumentOut:
    """Masukkan harga yang sedang tampil di aplikasi broker; sistem menghitung offset."""
    try:
        setting = await calibrate(session, provider, instrument, body.broker_price)
    except CalibrationError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(502, f"Gagal mengambil harga feed: {exc}") from exc
    return instrument_out(instrument, setting, datetime.now(UTC))


@router.delete("/instruments/{symbol}/calibration", response_model=InstrumentOut)
async def delete_calibration(instrument: InstrumentDep, session: SessionDep) -> InstrumentOut:
    setting = await reset_calibration(session, instrument)
    return instrument_out(instrument, setting, datetime.now(UTC))


@router.get("/candles", response_model=CandlesResponse)
async def get_candles(
    session: SessionDep,
    provider: ProviderDep,
    symbol: Annotated[str, Query(examples=["XAUUSD"])],
    timeframe: Timeframe = Timeframe.M15,
    limit: Annotated[int, Query(ge=1, le=2000)] = 300,
    adjusted: Annotated[bool, Query(description="Terapkan offset kalibrasi broker")] = True,
    include_live: Annotated[bool, Query(description="Sertakan candle yang sedang berjalan")] = True,
    indicators: Annotated[bool, Query(description="Sertakan deret indikator untuk grafik")] = False,
) -> CandlesResponse:
    """Candle tertutup dari database + (opsional) live candle dan deret indikator."""
    instrument = resolve_instrument(symbol)
    now = datetime.now(UTC)
    warning = await refresh_if_stale(session, provider, get_redis(), instrument, timeframe, now)
    fetch_limit = limit + INDICATOR_WARMUP if indicators else limit
    all_rows = await candles_repo.get_candles(
        session, instrument.symbol, timeframe, limit=fetch_limit
    )
    rows = all_rows[-limit:]
    frame = compute_indicators(candles_to_frame(all_rows)) if indicators and all_rows else None
    offset = await _offset(session, instrument.symbol, adjusted)

    live, live_at, live_warning = (None, None, None)
    if include_live:
        live, live_at, live_warning = await fetch_live(provider, get_redis(), instrument, timeframe)

    warning = warning or live_warning
    if warning is None and await provider.remaining_daily_credits() == 0:
        # Penyegaran ditolak lokal tanpa pesan; tetap jelaskan mengapa grafik tidak bergerak
        warning = quota_exhausted_warning(provider.name)

    return CandlesResponse(
        symbol=instrument.symbol,
        timeframe=timeframe,
        adjusted=adjusted,
        price_offset=offset,
        market_open=is_market_open(instrument.asset_class, now),
        warning=warning,
        candles=[candle_out(row, offset, instrument.digits) for row in rows],
        live=candle_out(live, offset, instrument.digits) if live else None,
        live_updated_at=live_at,
        refresh_seconds=get_settings().live_refresh_seconds,
        indicators=indicator_series(frame, limit, offset, instrument.digits)
        if frame is not None
        else None,
        patterns=pattern_marks(frame, len(rows)) if frame is not None else None,
    )


@router.get("/candles/live", response_model=LiveCandleResponse)
async def get_live(
    session: SessionDep,
    provider: ProviderDep,
    symbol: Annotated[str, Query(examples=["XAUUSD"])],
    timeframe: Timeframe = Timeframe.M15,
    adjusted: bool = True,
) -> LiveCandleResponse:
    """Hanya candle yang sedang berjalan. Dashboard sebaiknya memakai WebSocket /ws."""
    instrument = resolve_instrument(symbol)
    live, live_at, warning = await fetch_live(provider, get_redis(), instrument, timeframe)
    offset = await _offset(session, instrument.symbol, adjusted)
    return LiveCandleResponse(
        symbol=instrument.symbol,
        timeframe=timeframe,
        market_open=is_market_open(instrument.asset_class, datetime.now(UTC)),
        live=candle_out(live, offset, instrument.digits) if live else None,
        live_updated_at=live_at,
        refresh_seconds=get_settings().live_refresh_seconds,
        warning=warning,
    )
