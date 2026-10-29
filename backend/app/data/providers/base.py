from abc import ABC, abstractmethod
from datetime import datetime

from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.data.schemas import CandleDTO, PriceQuote

MAX_BATCH = 5000


class DataProvider(ABC):
    """Kontrak data provider. Tambah provider baru dengan mengimplementasikan kelas ini
    lalu mendaftarkannya di `app.data.providers.create_provider`."""

    name: str

    @abstractmethod
    async def fetch_candles(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[CandleDTO]:
        """Candle urut naik berdasarkan waktu. Boleh menyertakan candle yang belum tutup."""

    @abstractmethod
    async def fetch_price(self, instrument: Instrument) -> PriceQuote:
        """Harga terkini (dipakai untuk kalibrasi)."""

    async def remaining_daily_credits(self) -> int | None:
        """Sisa kuota harian, atau None bila provider tidak berkuota."""
        return None

    async def aclose(self) -> None:  # noqa: B027 - opsional untuk provider tanpa koneksi
        return None
