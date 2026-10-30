"""Pembacaan pola candlestick (Hammer, Morning Star, Engulfing, dst.) per timeframe, dengan
peluang historis tiap pola dan kesimpulan kemungkinan BUY / SELL."""

from datetime import UTC, datetime
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.analysis.indicators import compute_indicators
from app.api.deps import ProviderDep, SessionDep, resolve_instrument
from app.core.instruments import Instrument, get_instruments
from app.core.market_hours import last_expected_candle_open
from app.core.redis import get_redis
from app.core.timeframes import Timeframe
from app.repositories import candles as candles_repo
from app.services.candle_sync import is_up_to_date, refresh_if_stale
from app.services.live_candle import fetch_live
from app.services.pattern_stats import (
    HORIZON,
    MAX_HOLD,
    MIN_EDGE,
    MIN_SAMPLES,
    PatternStat,
    best_exit,
    get_pattern_stats,
    is_proven,
    wilson_lower,
)
from app.services.signal_engine import candles_to_frame
from app.strategies.common import TREND_TEXT, row_trend
from app.strategies.patterns import PATTERN_INFO, PatternRead, read_patterns, scan_patterns

router = APIRouter(tags=["patterns"])

PATTERN_TIMEFRAMES = tuple(Timeframe)  # M1 … H4
FRAME_BARS = 300  # cukup untuk EMA200 + konteks pola


class PatternOut(BaseModel):
    name: str
    bias: int
    meaning: str
    strength: int
    strength_text: str
    note: str
    probability: float | None = Field(
        default=None,
        description=f"Peluang historis harga bergerak searah pola dalam {HORIZON} candle "
        f"(None bila < {MIN_SAMPLES} kejadian)",
    )
    samples: int = Field(default=0, description="Jumlah kejadian historis pola ini")
    reliable: bool = Field(
        default=False,
        description="Arah terbesar (searah atau berlawanan pola) >= MIN_EDGE dan lolos uji 95%",
    )
    best_hold: int | None = Field(
        default=None,
        description=f"CLOSE dengan rata-rata untung terbesar: sekian candle setelah masuk "
        f"(1…{MAX_HOLD}); None bila tidak ada yang untung setelah spread",
    )
    best_pips: float | None = Field(
        default=None, description="Rata-rata hasil bersih (pip) bila CLOSE di best_hold"
    )
    best_win: float | None = Field(
        default=None, description="Bagian kejadian yang untung bila CLOSE di best_hold"
    )


class PatternMark(PatternOut):
    time: int


class TimeframePatterns(BaseModel):
    timeframe: Timeframe
    trend: str
    candle_time: int | None
    up_to_date: bool = Field(
        default=True, description="false = candle belum diperbarui; pola tidak dibaca"
    )
    patterns: list[PatternOut]


class PatternConclusion(BaseModel):
    bias: Literal["BUY", "SELL", "MIXED", "NONE"]
    text: str
    probability: float | None = Field(
        default=None, description="Peluang historis arah `direction` (BUY/SELL bila meyakinkan)"
    )
    direction: Literal["naik", "turun"] | None = Field(
        default=None, description="Arah yang lebih mungkin (juga saat MIXED / belum meyakinkan)"
    )
    samples: int = 0


class PatternsResponse(BaseModel):
    symbol: str
    horizon: int = Field(default=HORIZON, description="Candle setelah pola yang dinilai")
    timeframes: list[TimeframePatterns]
    conclusion: PatternConclusion


def pattern_out(
    read: PatternRead, stat: PatternStat | None = None, instrument: Instrument | None = None
) -> PatternOut:
    p = read.pattern
    tested = stat is not None and stat.samples >= MIN_SAMPLES and p.bias != 0
    reliable = False
    if tested and stat:
        hits = max(stat.hits, stat.samples - stat.hits)
        reliable = hits / stat.samples >= MIN_EDGE and wilson_lower(hits, stat.samples) > 0.5
    plan = (
        best_exit(stat, instrument.pip_size, instrument.typical_spread_pips)
        if instrument and p.bias
        else None
    )
    return PatternOut(
        name=p.name,
        bias=p.bias,
        meaning=p.meaning,
        strength=read.strength,
        strength_text=read.strength_text,
        note=read.note,
        probability=round(stat.rate, 3) if tested and stat else None,
        samples=stat.samples if stat else 0,
        reliable=reliable,
        best_hold=plan.hold if plan else None,
        best_pips=plan.pips if plan else None,
        best_win=plan.win_rate if plan else None,
    )


def pattern_marks(
    df: pd.DataFrame,
    bars: int,
    stats: dict[str, PatternStat] | None = None,
    instrument: Instrument | None = None,
) -> list[PatternMark]:
    """Pola berarah (bukan Spinning Top) di `bars` candle terakhir, untuk penanda grafik.
    `stats` (peluang historis per pola di timeframe ini) membuat grafik bisa menampilkan
    prediksi candle berikutnya untuk pola yang terbukti."""
    stats = stats or {}
    return [
        PatternMark(
            time=int(t.timestamp()),
            **pattern_out(r, stats.get(r.pattern.name), instrument).model_dump(),
        )
        for t, r in scan_patterns(df, bars, row_trend)
        if r.pattern.bias
    ]


def conclude(frames: list[TimeframePatterns]) -> PatternConclusion:
    """Kemungkinan BUY/SELL dari peluang historis pola yang muncul sekarang (digabung).
    Arah hanya disimpulkan bila peluangnya >= MIN_EDGE dan batas bawah keyakinan 95%-nya di
    atas 50%; tanpa pola yang cukup teruji, kembali ke penilaian kekuatan pola."""
    up = total = 0
    tested: list[str] = []
    for f in frames:
        for p in f.patterns:
            if p.bias and p.probability is not None:
                hits = round(p.probability * p.samples)
                up += hits if p.bias == 1 else p.samples - hits
                total += p.samples
                tested.append(f"{p.name} {f.timeframe.value} {p.probability:.0%} benar")
    if not total:
        return conclude_by_strength(frames)
    direction = 1 if up * 2 >= total else -1
    hits = up if direction == 1 else total - up
    prob = hits / total
    listing = ", ".join(tested)
    side, word = ("BUY", "naik") if direction == 1 else ("SELL", "turun")
    if prob >= MIN_EDGE and wilson_lower(hits, total) > 0.5:
        return PatternConclusion(
            bias=side,
            text=f"Kemungkinan {side} {prob:.0%}: secara historis harga {word} dalam {HORIZON} "
            f"candle setelah pola ini ({listing}; {total} kejadian).",
            probability=round(prob, 3),
            direction=word,
            samples=total,
        )
    return PatternConclusion(
        bias="MIXED",
        text=f"Peluang historis {prob:.0%} {word} ({listing}; {total} kejadian) belum cukup "
        "meyakinkan untuk menentukan arah. Tunggu konfirmasi.",
        probability=round(prob, 3),
        direction=word,
        samples=total,
    )


def conclude_by_strength(frames: list[TimeframePatterns]) -> PatternConclusion:
    """Ringkasan: pola berarah (kekuatan sedang/kuat) dari timeframe besar diberi bobot lebih.
    Pola yang melawan tren H1 tidak dianggap arah, karena pembalikannya belum terkonfirmasi."""
    weight = {
        Timeframe.M1: 0.5,
        Timeframe.M5: 0.75,
        Timeframe.M15: 1.0,
        Timeframe.H1: 1.5,
        Timeframe.H4: 2.0,
    }
    direction = {"naik": 1, "turun": -1}
    h1_trend = next((direction.get(f.trend, 0) for f in frames if f.timeframe == Timeframe.H1), 0)
    score, found = 0.0, []
    for f in frames:
        for p in f.patterns:
            if p.bias and p.strength >= 2:
                score += p.bias * p.strength * weight[f.timeframe]
                found.append(f"{p.name} {f.timeframe.value} ({p.strength_text})")
    if not found:
        return PatternConclusion(
            bias="NONE",
            text="Belum ada pola candlestick berarah yang cukup kuat di candle terakhir.",
        )
    listing = ", ".join(found)
    bias = 1 if score >= 2 else -1 if score <= -2 else 0
    if bias and h1_trend == -bias:
        word = "naik" if bias == 1 else "turun"
        return PatternConclusion(
            bias="MIXED",
            text=f"Pola {word} ({listing}) melawan tren H1 {TREND_TEXT[h1_trend]}: pembalikan "
            "belum terkonfirmasi, tunggu.",
        )
    if bias == 1:
        return PatternConclusion(bias="BUY", text=f"Pola condong NAIK: {listing}.")
    if bias == -1:
        return PatternConclusion(bias="SELL", text=f"Pola condong TURUN: {listing}.")
    return PatternConclusion(bias="MIXED", text=f"Pola campur/lemah: {listing}.")


@router.get("/patterns", response_model=PatternsResponse)
async def get_patterns(
    session: SessionDep,
    provider: ProviderDep,
    symbol: Annotated[str, Query(examples=["XAUUSD"])],
    timeframe: Annotated[
        Timeframe | None,
        Query(description="Timeframe grafik yang sedang dibuka; candle-nya diperbarui dulu"),
    ] = None,
) -> PatternsResponse:
    """Pola candlestick pada candle TERTUTUP terakhir di M1–H4, dengan kekuatannya (di area
    support/resistance? searah tren?) dan peluang historisnya di instrumen ini. Timeframe yang
    candle-nya belum terbaru tidak dibaca (pola lama bukan sinyal sekarang)."""
    instrument = resolve_instrument(symbol)
    redis = get_redis()
    now = datetime.now(UTC)
    if timeframe is not None:
        await refresh_if_stale(session, provider, redis, instrument, timeframe, now)
    frames: list[TimeframePatterns] = []
    for tf in PATTERN_TIMEFRAMES:
        rows = await candles_repo.get_candles(session, instrument.symbol, tf, limit=FRAME_BARS)
        if len(rows) < 3:
            frames.append(
                TimeframePatterns(
                    timeframe=tf, trend="-", candle_time=None, up_to_date=False, patterns=[]
                )
            )
            continue
        df = compute_indicators(candles_to_frame(rows))
        trend = row_trend(df.iloc[-1])
        expected = last_expected_candle_open(instrument.asset_class, now, tf)
        fresh = is_up_to_date(rows[-1].open_time, expected, tf)
        reads = read_patterns(df, trend) if fresh else []
        stats = await get_pattern_stats(session, redis, instrument.symbol, tf) if reads else {}
        frames.append(
            TimeframePatterns(
                timeframe=tf,
                trend=TREND_TEXT[trend],
                candle_time=int(df.index[-1].timestamp()),
                up_to_date=fresh,
                patterns=[pattern_out(r, stats.get(r.pattern.name), instrument) for r in reads],
            )
        )
    return PatternsResponse(
        symbol=instrument.symbol, timeframes=frames, conclusion=conclude(frames)
    )


class PatternOdds(BaseModel):
    symbol: str
    timeframe: Timeframe
    name: str
    bias: int = Field(description="Arah bawaan pola: 1 naik, -1 turun")
    samples: int
    probability: float = Field(description="Seberapa sering pola benar (searah bias)")
    direction: Literal["naik", "turun"] = Field(
        description="Arah yang lebih sering terjadi setelah pola (bisa berlawanan dengan bias)"
    )
    chance: float = Field(description="Peluang `direction` dalam HORIZON candle")
    follows_pattern: bool = Field(description="false = pola lebih sering gagal (arah terbalik)")
    reliable: bool = Field(description="Peluang >= MIN_EDGE dan lolos uji keyakinan 95%")


class PatternOddsResponse(BaseModel):
    horizon: int = HORIZON
    min_samples: int = MIN_SAMPLES
    min_edge: float = MIN_EDGE
    rows: list[PatternOdds]


def pattern_odds(symbol: str, tf: Timeframe, name: str, stat: PatternStat) -> PatternOdds | None:
    bias = PATTERN_INFO.get(name, (0, ""))[0]
    if not bias or stat.samples < MIN_SAMPLES:
        return None
    follows = stat.rate >= 0.5
    hits = stat.hits if follows else stat.samples - stat.hits
    chance = hits / stat.samples
    up = (bias == 1) == follows
    return PatternOdds(
        symbol=symbol,
        timeframe=tf,
        name=name,
        bias=bias,
        samples=stat.samples,
        probability=round(stat.rate, 3),
        direction="naik" if up else "turun",
        chance=round(chance, 3),
        follows_pattern=follows,
        reliable=chance >= MIN_EDGE and wilson_lower(hits, stat.samples) > 0.5,
    )


@router.get("/patterns/stats", response_model=PatternOddsResponse)
async def get_pattern_odds(session: SessionDep) -> PatternOddsResponse:
    """Peluang historis semua pola per instrumen & timeframe (untuk Panduan), diurutkan dari
    peluang terbesar. Dari cache yang dihangatkan worker; M1/M5 dihitung bila belum ada."""
    redis = get_redis()
    rows: list[PatternOdds] = []
    for symbol in sorted(get_instruments()):
        for tf in PATTERN_TIMEFRAMES:
            stats = await get_pattern_stats(session, redis, symbol, tf)
            rows += [r for n, s in stats.items() if (r := pattern_odds(symbol, tf, n, s))]
    rows.sort(key=lambda r: (r.chance, r.samples), reverse=True)
    return PatternOddsResponse(rows=rows)


# ---------- pola pada candle yang SEDANG berjalan ----------


class FormingPrediction(BaseModel):
    direction: Literal["BUY", "SELL"]
    pattern: str
    chance: float = Field(description="Peluang historis pola ini benar (searah teori)")
    samples: int
    hold: int = Field(default=1, description="CLOSE setelah sekian candle sejak masuk")
    close_at: int = Field(description="Waktu CLOSE dengan rata-rata untung terbesar (detik)")
    avg_pips: float | None = Field(
        default=None, description="Rata-rata hasil bersih historis bila CLOSE di close_at"
    )
    win_rate: float | None = Field(
        default=None, description="Bagian kejadian historis yang untung bila CLOSE di close_at"
    )


class FormingResponse(BaseModel):
    symbol: str
    timeframe: Timeframe
    live: bool = Field(description="false = tidak ada candle berjalan (pasar tutup / data kosong)")
    candle_start: int | None = Field(default=None, description="Buka candle berjalan (detik)")
    candle_end: int | None = Field(
        default=None, description="Tutup candle berjalan = awal prediksi"
    )
    next_end: int | None = Field(default=None, description="Tutup candle berikutnya = CLOSE")
    progress: float | None = Field(default=None, description="Bagian candle berjalan yang lewat")
    patterns: list[PatternOut] = Field(default_factory=list)
    prediction: FormingPrediction | None = None
    note: str


@router.get("/patterns/forming", response_model=FormingResponse)
async def get_forming_pattern(
    session: SessionDep,
    provider: ProviderDep,
    symbol: Annotated[str, Query(examples=["XAUUSD"])],
    timeframe: Timeframe = Timeframe.M15,
) -> FormingResponse:
    """Pola yang terbentuk bila candle BERJALAN tutup di harga sekarang, dan prediksi sementara
    untuk candle berikutnya (pola terbukti saja). Bisa berubah sampai candle tutup."""
    instrument = resolve_instrument(symbol)
    redis, now = get_redis(), datetime.now(UTC)
    await refresh_if_stale(session, provider, redis, instrument, timeframe, now)
    rows = await candles_repo.get_candles(session, instrument.symbol, timeframe, limit=FRAME_BARS)
    live, _, _ = await fetch_live(provider, redis, instrument, timeframe)
    if live is None or not rows or live.open_time <= rows[-1].open_time:
        return FormingResponse(
            symbol=instrument.symbol,
            timeframe=timeframe,
            live=False,
            note="Tidak ada candle berjalan (pasar tutup atau data live belum tersedia).",
        )
    df = candles_to_frame(rows)
    live_ohlc = [live.open, live.high, live.low, live.close]
    df.loc[pd.Timestamp(live.open_time).tz_convert(UTC)] = live_ohlc
    df = compute_indicators(df)
    reads = read_patterns(df, row_trend(df.iloc[-1]))
    stats = await get_pattern_stats(session, redis, instrument.symbol, timeframe) if reads else {}
    start = live.open_time
    end = start + timeframe.delta
    proven = [r for r in reads if r.pattern.bias and is_proven(stats.get(r.pattern.name))]
    prediction = None
    if proven:
        best = max(proven, key=lambda r: stats[r.pattern.name].rate)
        stat = stats[best.pattern.name]
        plan = best_exit(stat, instrument.pip_size, instrument.typical_spread_pips)
        hold = plan.hold if plan else 1
        prediction = FormingPrediction(
            direction="BUY" if best.pattern.bias > 0 else "SELL",
            pattern=best.pattern.name,
            chance=round(stat.rate, 3),
            samples=stat.samples,
            hold=hold,
            close_at=int((end + timeframe.delta * hold).timestamp()),
            avg_pips=plan.pips if plan else None,
            win_rate=plan.win_rate if plan else None,
        )
        note = (
            f"Bila candle ini tutup seperti sekarang, {best.pattern.name} terbentuk → "
            f"{prediction.direction} di candle berikutnya, CLOSE setelah {hold} candle. "
            "Masih sementara sampai candle tutup."
        )
    elif reads:
        note = "Pola sedang terbentuk, tetapi belum terbukti di histori — tidak ada prediksi."
    else:
        note = "Belum ada pola yang terbentuk di candle berjalan."
    return FormingResponse(
        symbol=instrument.symbol,
        timeframe=timeframe,
        live=True,
        candle_start=int(start.timestamp()),
        candle_end=int(end.timestamp()),
        next_end=int((end + timeframe.delta).timestamp()),
        progress=round(min(max((now - start) / timeframe.delta, 0.0), 1.0), 2),
        patterns=[pattern_out(r, stats.get(r.pattern.name), instrument) for r in reads],
        prediction=prediction,
        note=note,
    )
