"""Factory data provider (adapter pattern). Bawaan dari DATA_PROVIDER di .env; Twelve Data dan
Tiingo bisa diganti saat berjalan dari Pengaturan (disimpan di tabel app_settings)."""

import time
from collections.abc import Awaitable, Callable
from datetime import datetime

from app.core.config import Settings, get_settings
from app.core.instruments import Instrument
from app.core.redis import get_redis
from app.core.timeframes import Timeframe
from app.data.providers.base import DataProvider
from app.data.providers.mock import MockProvider
from app.data.providers.tiingo import TiingoProvider
from app.data.providers.twelvedata import TwelveDataProvider
from app.data.rate_limit import RedisRateLimiter
from app.data.schemas import CandleDTO, PriceQuote

DATA_PROVIDER_SETTING = "data_provider"
PROVIDER_LABELS = {"twelvedata": "Twelve Data", "tiingo": "Tiingo"}
CHOICE_TTL_SECONDS = 5.0  # backend & worker membaca ulang pilihan secepat ini

_provider: DataProvider | None = None


async def load_saved_choice() -> str | None:
    from app.db.session import SessionLocal
    from app.repositories import app_settings

    async with SessionLocal() as session:
        value = await app_settings.get_value(session, DATA_PROVIDER_SETTING)
    return value if isinstance(value, str) else None


class SwitchableProvider(DataProvider):
    """Meneruskan setiap panggilan ke provider pilihan Pengaturan."""

    def __init__(
        self,
        providers: dict[str, DataProvider],
        default: str,
        load_choice: Callable[[], Awaitable[str | None]] = load_saved_choice,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.providers = providers
        self._default = default
        self._load_choice = load_choice
        self._clock = clock
        self._active = default
        self._checked_at: float | None = None

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._active

    def invalidate(self) -> None:
        self._checked_at = None

    async def active_name(self) -> str:
        now = self._clock()
        if self._checked_at is None or now - self._checked_at >= CHOICE_TTL_SECONDS:
            choice = await self._load_choice()
            self._active = choice if choice in self.providers else self._default
            self._checked_at = now
        return self._active

    async def current(self) -> DataProvider:
        return self.providers[await self.active_name()]

    async def fetch_candles(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[CandleDTO]:
        provider = await self.current()
        return await provider.fetch_candles(
            instrument, timeframe, start=start, end=end, limit=limit
        )

    async def fetch_price(self, instrument: Instrument) -> PriceQuote:
        return await (await self.current()).fetch_price(instrument)

    async def remaining_daily_credits(self) -> int | None:
        return await (await self.current()).remaining_daily_credits()

    async def aclose(self) -> None:
        for provider in self.providers.values():
            await provider.aclose()


def create_provider(settings: Settings) -> DataProvider:
    if settings.data_provider == "mock":
        return MockProvider()
    redis = get_redis()
    providers: dict[str, DataProvider] = {
        "twelvedata": TwelveDataProvider(
            settings.twelvedata_api_key.get_secret_value(),
            RedisRateLimiter(
                redis,
                "twelvedata",
                per_minute=settings.twelvedata_rate_limit_per_min,
                per_day=settings.twelvedata_daily_limit,
            ),
        ),
        "tiingo": TiingoProvider(
            settings.tiingo_api_key.get_secret_value(),
            RedisRateLimiter(
                redis,
                "tiingo",
                per_minute=settings.tiingo_rate_limit_per_min,
                per_hour=settings.tiingo_rate_limit_per_hour,
                per_day=settings.tiingo_daily_limit,
            ),
        ),
    }
    return SwitchableProvider(providers, default=settings.data_provider)


def provider_configured(settings: Settings, name: str) -> bool:
    key = {"twelvedata": settings.twelvedata_api_key, "tiingo": settings.tiingo_api_key}[name]
    return bool(key.get_secret_value())


def get_provider() -> DataProvider:
    global _provider
    if _provider is None:
        _provider = create_provider(get_settings())
    return _provider


async def close_provider() -> None:
    global _provider
    if _provider is not None:
        await _provider.aclose()
        _provider = None


__all__ = [
    "DATA_PROVIDER_SETTING",
    "PROVIDER_LABELS",
    "DataProvider",
    "SwitchableProvider",
    "close_provider",
    "create_provider",
    "get_provider",
    "provider_configured",
]
