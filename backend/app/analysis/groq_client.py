"""Klien Groq (API kompatibel OpenAI) untuk jawaban JSON terstruktur."""

import asyncio
import json
import logging
import re
import time
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Perkiraan token satu panggilan (prompt + jawaban). Bila sisa kuota/menit di bawah ini,
# tunggu sampai kuota pulih SEBELUM mengirim (hindari ditolak 429).
CALL_TOKEN_RESERVE = 3500
_DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_budget: dict[str, float | None] = {"remaining": None, "reset_at": 0.0, "blocked_until": 0.0}


def parse_duration(text: str | None) -> float:
    """Durasi gaya Groq ("577ms", "7.66s", "1m2.5s", "2h35m31.2s") → detik."""
    scale = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}
    return sum(float(n) * scale[u] for n, u in _DURATION.findall(text or ""))


def _remember_budget(headers: httpx.Headers) -> None:
    remaining = headers.get("x-ratelimit-remaining-tokens")
    if remaining is not None:
        _budget["remaining"] = float(remaining)
        _budget["reset_at"] = time.monotonic() + parse_duration(
            headers.get("x-ratelimit-reset-tokens")
        )


MAX_INLINE_WAIT = 60.0


def _blocked_message(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    return f"kuota AI Groq harian habis, aktif lagi ±{minutes} menit"


async def _pace() -> None:
    blocked = (_budget.get("blocked_until") or 0.0) - time.monotonic()
    if blocked > 0:
        raise GroqError(_blocked_message(blocked))
    remaining, reset_at = _budget["remaining"], _budget["reset_at"] or 0.0
    wait = reset_at - time.monotonic()
    if remaining is not None and remaining < CALL_TOKEN_RESERVE and wait > 0:
        logger.info("Menunggu kuota token Groq pulih (%.1f detik)", wait)
        await asyncio.sleep(wait + 0.5)
        _budget["remaining"] = None


class GroqError(Exception):
    pass


class GroqClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        reasoning_effort: str = "",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._timeout = timeout
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    async def chat_json(
        self, system: str, user: str, *, max_tokens: int = 500, temperature: float = 0.2
    ) -> dict[str, Any]:
        """Kirim percakapan dan kembalikan objek JSON dari jawaban model."""
        if not self._api_key:
            raise GroqError("GROQ_API_KEY belum diisi")
        payload: dict[str, Any] = {
            "model": self._model,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort

        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for attempt in range(2):
                await _pace()
                try:
                    resp = await client.post(
                        GROQ_URL, json=payload, headers={"Authorization": f"Bearer {self._api_key}"}
                    )
                except httpx.HTTPError as exc:
                    raise GroqError(f"Groq tidak terjangkau: {exc}") from exc
                _remember_budget(resp.headers)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("retry-after") or 0)
                    if retry_after > MAX_INLINE_WAIT:
                        # Kuota harian (TPD/RPD) habis: berhenti mencoba sampai pulih
                        _budget["blocked_until"] = time.monotonic() + retry_after
                        logger.warning("Kuota harian Groq habis: %s", resp.text[:200])
                        raise GroqError(_blocked_message(retry_after))
                    if attempt == 0:
                        wait = max(retry_after, 1.0)
                        logger.warning("Batas Groq per menit, menunggu %.0f detik", wait)
                        await asyncio.sleep(wait)
                        continue
                if resp.status_code >= 400:
                    raise GroqError(f"Groq HTTP {resp.status_code}: {resp.text[:200]}")
                break
        try:
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise GroqError(f"Jawaban Groq bukan JSON yang valid: {exc}") from exc


def get_groq_client() -> GroqClient:
    settings = get_settings()
    return GroqClient(
        settings.groq_api_key.get_secret_value(),
        settings.groq_model,
        reasoning_effort=settings.groq_reasoning_effort,
    )
