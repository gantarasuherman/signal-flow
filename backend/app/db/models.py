"""Model ORM. Semua model harus didefinisikan/diimpor di sini agar terdeteksi Alembic."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Candle(Base):
    """Candle yang SUDAH tutup. Kunci utama (symbol, timeframe, open_time) sekaligus
    menjadi indeks untuk query rentang waktu."""

    __tablename__ = "candles"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(4), primary_key=True)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[float] = mapped_column(Double)
    high: Mapped[float] = mapped_column(Double)
    low: Mapped[float] = mapped_column(Double)
    close: Mapped[float] = mapped_column(Double)
    volume: Mapped[float | None] = mapped_column(Double)
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InstrumentSetting(Base):
    """Pengaturan per instrumen yang bisa diubah dari dashboard: kalibrasi & spread."""

    __tablename__ = "instrument_settings"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    price_offset: Mapped[float] = mapped_column(Double, default=0.0, server_default="0")
    broker_price: Mapped[float | None] = mapped_column(Double)
    feed_price: Mapped[float | None] = mapped_column(Double)
    calibrated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    spread_pips: Mapped[float | None] = mapped_column(Double)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Signal(Base):
    """Event sinyal: BUY/SELL (punya siklus status) dan CLOSE (menutup BUY/SELL induknya).

    Harga disimpan dalam harga FEED (BID); penyesuaian ke broker (offset) diterapkan saat
    ditampilkan sehingga kalibrasi ulang berlaku juga untuk sinyal lama.
    """

    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("symbol", "strategy", "candle_time", "action"),
        Index("ix_signals_symbol_created_at", "symbol", "created_at"),
        Index(
            "uq_signals_one_active",
            "symbol",
            "strategy",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16))
    timeframe: Mapped[str] = mapped_column(String(4), default="M15")
    strategy: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(8))
    candle_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    entry: Mapped[float | None] = mapped_column(Double)
    stop_loss: Mapped[float | None] = mapped_column(Double)
    take_profit: Mapped[float | None] = mapped_column(Double)
    atr: Mapped[float | None] = mapped_column(Double)
    risk_reward: Mapped[float | None] = mapped_column(Double)
    spread_pips: Mapped[float | None] = mapped_column(Double)
    confidence: Mapped[float | None] = mapped_column(Double)
    confidence_label: Mapped[str | None] = mapped_column(String(8))
    entry_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    reasons: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    reason_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    status: Mapped[str | None] = mapped_column(String(8))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_price: Mapped[float | None] = mapped_column(Double)
    close_reason: Mapped[str | None] = mapped_column(Text)
    result_pips: Mapped[float | None] = mapped_column(Double)


class AppSetting(Base):
    """Pengaturan aplikasi key-value (mis. preferensi risiko)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BacktestRun(Base):
    """Permintaan & hasil backtest. Dibuat oleh API (queued), dikerjakan oleh worker."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued/running/done/failed
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class PatternPrediction(Base):
    """Prediksi candle berikutnya dari pola candlestick terbukti, dicatat SAAT terjadi
    (uji maju). `on_time` = tercatat sebelum hasilnya bisa diketahui; hanya baris ini yang
    dihitung sebagai ukuran jujur. Harga mentah (tanpa offset kalibrasi)."""

    __tablename__ = "pattern_predictions"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "pattern_time", "pattern"),
        Index("ix_pattern_predictions_status_close", "status", "close_time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16))
    timeframe: Mapped[str] = mapped_column(String(4))
    pattern: Mapped[str] = mapped_column(String(32))
    direction: Mapped[int]  # 1 BUY, -1 SELL
    chance: Mapped[float] = mapped_column(Double)  # peluang historis saat dicatat
    samples: Mapped[int]
    pattern_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[float] = mapped_column(Double)
    spread_pips: Mapped[float] = mapped_column(Double)
    exit_price: Mapped[float | None] = mapped_column(Double)
    result_pips: Mapped[float | None] = mapped_column(Double)
    status: Mapped[str] = mapped_column(String(8), default="open")  # open / done / no_data
    on_time: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = [
    "AppSetting",
    "BacktestRun",
    "Base",
    "Candle",
    "InstrumentSetting",
    "PatternPrediction",
    "Signal",
]
