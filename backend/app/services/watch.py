"""Instrumen yang sedang dipantau di dashboard.

Saat grafik suatu instrumen dibuka, API menandai `watch:{symbol}` (kedaluwarsa otomatis bila
tidak diperbarui). Worker hanya menyinkronkan & menganalisis instrumen yang dipantau (plus
yang masih punya posisi aktif) agar hemat kuota data & AI. Tab baru dipilih → worker diberi
tahu lewat channel `watch:start` agar langsung menganalisis tanpa menunggu candle berikutnya.
"""

import json

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import app_settings

WATCH_KEY = "watch:{symbol}"
WATCH_CHANNEL = "watch:start"
WATCH_TTL_SECONDS = 180  # diperbarui tiap ±20 detik oleh koneksi grafik yang terbuka


async def mark_watched(redis: Redis, symbol: str) -> bool:
    """Tandai dipantau. True bila sebelumnya TIDAK dipantau (baru mulai dibuka)."""
    key = WATCH_KEY.format(symbol=symbol)
    started = bool(await redis.set(key, "1", nx=True, ex=WATCH_TTL_SECONDS))
    if started:
        await redis.publish(WATCH_CHANNEL, json.dumps({"symbol": symbol}))
    else:
        await redis.expire(key, WATCH_TTL_SECONDS)
    return started


async def watched_symbols(redis: Redis, symbols: list[str]) -> set[str]:
    if not symbols:
        return set()
    flags = await redis.mget([WATCH_KEY.format(symbol=s) for s in symbols])
    return {s for s, flag in zip(symbols, flags, strict=True) if flag}


# ---------- pilihan "Pantau keempatnya" ----------

WATCH_ALL_SETTING = "watch_all"


async def watch_all_enabled(session: AsyncSession) -> bool:
    """True bila pengguna memilih menganalisis SEMUA instrumen (bukan hanya yang dibuka)."""
    return bool(await app_settings.get_value(session, WATCH_ALL_SETTING))


async def set_watch_all(
    session: AsyncSession, redis: Redis, enabled: bool, symbols: list[str]
) -> None:
    await app_settings.set_value(session, WATCH_ALL_SETTING, enabled)
    await session.commit()
    if enabled:
        # Minta worker langsung menganalisis semua instrumen tanpa menunggu candle berikutnya
        for symbol in symbols:
            await redis.publish(WATCH_CHANNEL, json.dumps({"symbol": symbol}))
