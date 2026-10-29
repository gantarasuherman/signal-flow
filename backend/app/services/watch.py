"""Instrumen yang sedang dipantau di dashboard.

Saat grafik suatu instrumen dibuka, API menandai `watch:{symbol}` (kedaluwarsa otomatis bila
tidak diperbarui). Worker hanya menyinkronkan & menganalisis instrumen yang dipantau (plus
yang masih punya posisi aktif) agar hemat kuota data & AI. Tab baru dipilih → worker diberi
tahu lewat channel `watch:start` agar langsung menganalisis tanpa menunggu candle berikutnya.
"""

import json

from redis.asyncio import Redis

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
