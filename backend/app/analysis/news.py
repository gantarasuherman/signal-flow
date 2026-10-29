"""Hook kalender ekonomi.

Implementasi bawaan membaca config/news_events.yaml (diisi manual). Untuk sumber otomatis,
buat kelas yang mengimplementasikan `NewsCalendar` lalu kembalikan dari `get_news_calendar`.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

import yaml
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

Impact = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class NewsEvent:
    time: datetime
    currency: str
    impact: Impact
    title: str


class NewsCalendar(Protocol):
    async def events(
        self, currencies: set[str], start: datetime, end: datetime
    ) -> list[NewsEvent]: ...


class _EventModel(BaseModel):
    time: datetime
    currency: str
    impact: Impact = "high"
    title: str


class _FileModel(BaseModel):
    events: list[_EventModel] = []


class YamlNewsCalendar:
    """Membaca ulang file bila berubah, jadi bisa diedit tanpa restart."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._mtime: float | None = None
        self._events: list[NewsEvent] = []

    def _load(self) -> None:
        if not self._path.exists():
            self._events = []
            return
        mtime = self._path.stat().st_mtime
        if mtime == self._mtime:
            return
        try:
            raw = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
            parsed = _FileModel.model_validate(raw)
        except (yaml.YAMLError, ValidationError) as exc:
            logger.error("File kalender berita tidak valid (%s): %s", self._path, exc)
            return
        self._events = [
            NewsEvent(e.time, e.currency.upper(), e.impact, e.title)
            for e in parsed.events
            if e.time.tzinfo is not None
        ]
        self._mtime = mtime

    async def events(self, currencies: set[str], start: datetime, end: datetime) -> list[NewsEvent]:
        self._load()
        return [e for e in self._events if e.currency in currencies and start <= e.time <= end]
