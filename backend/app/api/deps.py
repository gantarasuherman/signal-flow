from typing import Annotated

from fastapi import Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.instruments import Instrument, get_instrument
from app.data.providers import DataProvider, get_provider
from app.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ProviderDep = Annotated[DataProvider, Depends(get_provider)]


def resolve_instrument(symbol: str) -> Instrument:
    instrument = get_instrument(symbol)
    if instrument is None:
        raise HTTPException(404, f"Instrumen {symbol.upper()} tidak terdaftar atau nonaktif")
    return instrument


def instrument_from_path(symbol: Annotated[str, Path(examples=["XAUUSD"])]) -> Instrument:
    return resolve_instrument(symbol)


InstrumentDep = Annotated[Instrument, Depends(instrument_from_path)]
