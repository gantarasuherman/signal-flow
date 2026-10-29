"""Konfigurasi aplikasi dari environment variable (.env)."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    timezone: str = "Asia/Jakarta"

    database_url: str = "postgresql+asyncpg://signalflow:signalflow@localhost:5432/signalflow"
    redis_url: str = "redis://localhost:6379/0"
    instruments_file: Path = Path("config/instruments.yaml")

    data_provider: Literal["twelvedata", "mock"] = "twelvedata"
    twelvedata_api_key: SecretStr = SecretStr("")
    twelvedata_rate_limit_per_min: int = Field(default=8, ge=1)
    twelvedata_daily_limit: int = Field(default=800, ge=1)
    # Kuota harian yang tidak boleh dipakai live candle (dicadangkan untuk worker)
    twelvedata_reserved_daily: int = Field(default=300, ge=0)
    live_refresh_seconds: int = Field(default=20, ge=5, le=300)
    # Harga real-time per detik via WebSocket Twelve Data (simbol yang didukung paket)
    twelvedata_streaming: bool = True

    scheduler_delay_seconds: int = Field(default=10, ge=0, le=300)

    default_risk_percent: float = Field(default=1.0, gt=0, le=10)

    # Hanya analisis instrumen yang sedang dibuka di dashboard (+ yang punya posisi aktif).
    # false = analisis semua instrumen setiap 15 menit.
    analyze_watched_only: bool = True

    # Sinyal AI Groq berdampingan dengan strategi (eksperimen; butuh GROQ_API_KEY)
    ai_signals_enabled: bool = True
    # Jeda antar panggilan AI per instrumen agar tidak melewati batas token/menit Groq
    ai_call_gap_seconds: int = Field(default=15, ge=0, le=120)

    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "openai/gpt-oss-120b"
    # low | medium | high untuk model reasoning; kosongkan untuk model non-reasoning
    groq_reasoning_effort: str = "low"

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Zona waktu tidak dikenal: {value}") from exc
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ai_signals_enabled() -> bool:
    settings = get_settings()
    return settings.ai_signals_enabled and bool(settings.groq_api_key.get_secret_value())
