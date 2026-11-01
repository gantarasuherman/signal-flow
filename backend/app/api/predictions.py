"""Rekap uji maju prediksi pola candlestick (dicatat saat terjadi)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from app.api.deps import SessionDep, resolve_instrument
from app.core.timeframes import Timeframe
from app.services.prediction_log import prediction_summary

router = APIRouter(tags=["patterns"])


class PredictionGroup(BaseModel):
    symbol: str
    timeframe: str
    done: int
    hits: int
    pips: float


class PredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    timeframe: str
    pattern: str
    direction: int
    chance: float
    entry_time: datetime
    close_time: datetime
    result_pips: float | None
    status: str


class PredictionSummary(BaseModel):
    since: datetime | None
    done: int
    hits: int
    pips: float
    pending: int
    groups: list[PredictionGroup]
    recent: list[PredictionOut]


@router.get("/predictions", response_model=PredictionSummary)
async def get_predictions(
    session: SessionDep,
    symbol: Annotated[str | None, Query(examples=["XAUUSD"])] = None,
    timeframe: Timeframe | None = None,
    days: Annotated[int | None, Query(ge=1, le=3650, description="Kosong = semua")] = None,
) -> PredictionSummary:
    """Hasil prediksi pola yang dicatat TEPAT WAKTU (sebelum hasilnya diketahui), bersih setelah
    spread. Prediksi yang terlambat dicatat (mis. grafik tidak sedang dibuka) tidak dihitung."""
    sym = resolve_instrument(symbol).symbol if symbol else None
    data = await prediction_summary(session, sym, timeframe, days)
    return PredictionSummary.model_validate(data)
