"""Factory data provider (adapter pattern). Pilih lewat DATA_PROVIDER di .env."""

from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.data.providers.base import DataProvider
from app.data.providers.mock import MockProvider
from app.data.providers.twelvedata import TwelveDataProvider
from app.data.rate_limit import RedisRateLimiter

_provider: DataProvider | None = None


def create_provider(settings: Settings) -> DataProvider:
    match settings.data_provider:
        case "twelvedata":
            limiter = RedisRateLimiter(
                get_redis(),
                "twelvedata",
                per_minute=settings.twelvedata_rate_limit_per_min,
                per_day=settings.twelvedata_daily_limit,
            )
            return TwelveDataProvider(settings.twelvedata_api_key.get_secret_value(), limiter)
        case "mock":
            return MockProvider()
    raise ValueError(f"DATA_PROVIDER tidak dikenal: {settings.data_provider}")


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


__all__ = ["DataProvider", "close_provider", "create_provider", "get_provider"]
