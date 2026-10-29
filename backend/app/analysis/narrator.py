"""Penyusun alasan sinyal dalam bahasa Indonesia.

Alasan utama selalu berbasis aturan (deterministik). Bila GROQ_API_KEY diisi, LLM Groq
merangkainya menjadi paragraf yang lebih enak dibaca. LLM tidak pernah menentukan sinyal
atau angka; bila gagal/timeout, teks berbasis aturan yang dipakai.
"""

import json
import logging
import re
from functools import lru_cache
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
SYSTEM_PROMPT = (
    "Anda adalah asisten analisis teknikal. Tulis penjelasan 2-3 kalimat dalam bahasa "
    "Indonesia yang sederhana untuk trader pemula, menjelaskan mengapa sinyal ini muncul. "
    "Gunakan HANYA fakta yang diberikan. Jangan menambah angka, prediksi, atau janji profit, "
    "jangan memberi saran keuangan, jangan memakai markdown atau emoji."
)
MAX_CHARS = 600


def rule_based_text(reasons: list[str]) -> str:
    return " ".join(reasons)


class Narrator:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
        reasoning_effort: str = "",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._timeout = timeout
        self._transport = transport

    @property
    def uses_llm(self) -> bool:
        return bool(self._api_key)

    async def describe(self, facts: dict[str, Any], reasons: list[str]) -> str:
        fallback = rule_based_text(reasons)
        if not self._api_key:
            return fallback
        payload: dict[str, Any] = {
            "model": self._model,
            "temperature": 0.3,
            # Model reasoning (gpt-oss, qwen3) memakai sebagian token untuk berpikir
            "max_completion_tokens": 600,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps({"fakta": facts, "alasan": reasons}, ensure_ascii=False),
                },
            ],
        }
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                resp = await client.post(
                    GROQ_URL, json=payload, headers={"Authorization": f"Bearer {self._api_key}"}
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            logger.warning("Groq gagal, memakai alasan berbasis aturan: %s", exc)
            return fallback
        text = re.sub(r"\s+", " ", str(text)).strip().strip('"')
        return text[:MAX_CHARS] if text else fallback


@lru_cache
def get_narrator() -> Narrator:
    settings = get_settings()
    return Narrator(
        settings.groq_api_key.get_secret_value(),
        settings.groq_model,
        reasoning_effort=settings.groq_reasoning_effort,
    )
