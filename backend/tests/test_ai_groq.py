import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from typing import Any

import httpx
import numpy as np
import pandas as pd
import pytest

from app.analysis.groq_client import GroqClient
from app.analysis.indicators import compute_indicators
from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.strategies import Action, ActiveSignalView, StrategyContext, create_strategy
from app.strategies.ai_groq import AiAnswer, AiGroqStrategy, build_prompt, combine_votes
from app.strategies.features import Setup, potential_setup, timeframe_facts

END = pd.Timestamp("2026-10-28 08:00", tz="UTC")
DIRECT = {"prefilter": False, "votes": 1, "vote_gap_seconds": 0}  # tanpa saringan & voting


def frame(n: int, step: timedelta, base: float = 4000.0) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    close = base + np.cumsum(rng.normal(0, 1, n))
    index = pd.DatetimeIndex([END - step * (n - 1 - i) for i in range(n)])
    df = pd.DataFrame(
        {"open": close - 0.3, "high": close + 1, "low": close - 1, "close": close}, index=index
    )
    return compute_indicators(df)


def force_trend(df: pd.DataFrame, direction: int) -> pd.DataFrame:
    """Paksa tren naik (1) / turun (-1) / datar (0) pada candle terakhir."""
    out = df.copy()
    values = {
        1: [4030, 4020, 4010, 4000],
        -1: [3970, 3980, 3990, 4000],
        0: [4000, 4000, 4010, 3990],
    }
    out.loc[out.index[-1], ["close", "ema_fast", "ema_mid", "ema_slow"]] = values[direction]
    return out


@pytest.fixture
def ctx(xauusd: Instrument) -> StrategyContext:
    return StrategyContext(
        xauusd,
        END.to_pydatetime() + timedelta(minutes=15),
        frame(300, timedelta(minutes=15)),
        force_trend(frame(300, timedelta(hours=1)), 0),
        force_trend(frame(300, timedelta(hours=4)), 0),
        spread_price=0.25,
    )


def with_trends(ctx: StrategyContext, h1: int, h4: int = 0) -> StrategyContext:
    return StrategyContext(
        ctx.instrument, ctx.now, ctx.m15, force_trend(ctx.h1, h1), force_trend(ctx.h4, h4),
        ctx.spread_price, ctx.active,
    )  # fmt: skip


def fake_client(
    answers: Sequence[dict[str, Any] | str], seen: list[dict[str, Any]] | None = None
) -> GroqClient:
    queue = list(answers)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        content = answer if isinstance(answer, str) else json.dumps(answer)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return GroqClient("k", "m", transport=httpx.MockTransport(handler))


def ai(answers: Any, seen: list[dict[str, Any]] | None = None, **params: Any) -> AiGroqStrategy:
    if not isinstance(answers, list):
        answers = [answers]
    return AiGroqStrategy({**DIRECT, **params}, client=fake_client(answers, seen))


BUY = {"action": "BUY", "sl_atr": 1.5, "tp_rr": 2.0, "confidence": 0.8, "reasons": ["Naik."]}
SELL = {"action": "SELL", "confidence": 0.8, "reasons": ["Turun."]}
WAIT = {"action": "WAIT", "confidence": 0.4, "reasons": ["Ragu."]}


# ---------- fakta & prompt ----------


def test_facts_are_computed_by_code(ctx: StrategyContext) -> None:
    facts = timeframe_facts(force_trend(ctx.h1, 1), 2)
    assert facts["tren"] == "naik"
    assert facts["urutan"] == "harga > EMA20 > EMA50 > EMA200"
    assert set(facts) >= {"rsi", "macd", "adx", "bollinger", "swing", "candle_terakhir"}


def test_prompt_contains_facts_setup_and_position(ctx: StrategyContext) -> None:
    setup = Setup(1, "pullback", "pullback ke EMA20")
    prompt = build_prompt(with_trends(ctx, 1), AiGroqStrategy().params, setup)
    assert "OPEN POSITION: none." in prompt
    assert "CANDIDATE SETUP (code): BUY" in prompt
    assert "H1: tren naik; urutan harga > EMA20 > EMA50 > EMA200" in prompt
    assert "M15 last 12 candles" in prompt
    assert len(prompt) < 4000  # ringkas → hemat token Groq


def test_prompt_uses_chosen_entry_timeframe(ctx: StrategyContext) -> None:
    params = AiGroqStrategy().params
    m5 = build_prompt(replace(ctx, timeframe=Timeframe.M5), params)
    assert "Entry timeframe: M5." in m5 and "M5 last 12 candles" in m5
    assert "M15" not in m5
    h1 = build_prompt(replace(ctx, timeframe=Timeframe.H1), params)
    assert h1.count("\nH1: ") == 1  # frame entry H1 tidak diulang sebagai konteks


# ---------- penyaring calon setup ----------


def test_potential_setup_pullback_in_uptrend() -> None:
    m15 = frame(300, timedelta(minutes=15))
    last = m15.index[-1]
    touch = m15.index[-3]
    m15.loc[touch, "low"] = m15.loc[touch, "ema_fast"] - 0.1  # sentuh EMA20
    m15.loc[last, ["close", "rsi"]] = [m15.loc[last, "ema_fast"] + 2, 55]
    h1 = force_trend(frame(300, timedelta(hours=1)), 1)
    setup = potential_setup(m15, h1, force_trend(frame(300, timedelta(hours=4)), 0))
    assert setup is not None and setup.direction == 1 and setup.kind == "pullback"
    # H4 berlawanan → tidak ada setup
    assert potential_setup(m15, h1, force_trend(frame(300, timedelta(hours=4)), -1)) is None


async def test_no_setup_means_no_ai_call(ctx: StrategyContext) -> None:
    seen: list[dict[str, Any]] = []
    s = ai(BUY, seen, prefilter=True)  # H1 datar → tidak ada calon setup
    await s.prepare(ctx)
    d = s.evaluate(ctx)
    assert d.action is Action.WAIT and "AI tidak dipanggil" in d.reasons[0]
    assert seen == [] and s.calls == 0


# ---------- voting ----------


def test_combine_votes_majority_and_disagreement() -> None:
    a = [AiAnswer(**BUY), AiAnswer(**WAIT), AiAnswer(**{**BUY, "confidence": 0.6})]
    merged, summary = combine_votes(a)
    assert merged is not None and merged.action == "BUY" and merged.confidence == 0.7
    assert summary == "BUY, WAIT, BUY"
    split, _ = combine_votes([AiAnswer(**BUY), AiAnswer(**WAIT), AiAnswer(**SELL)])
    assert split is None


async def test_votes_require_majority(ctx: StrategyContext) -> None:
    up = with_trends(ctx, 1)
    s = ai([BUY, WAIT, SELL], votes=3)
    await s.prepare(up)
    d = s.evaluate(up)
    assert s.calls == 3
    assert d.action is Action.WAIT and "tidak sepakat" in d.reasons[0]

    s2 = ai([BUY, WAIT, BUY], votes=3)
    await s2.prepare(up)
    d2 = s2.evaluate(up)
    assert d2.action is Action.BUY and "suara: BUY, WAIT, BUY" in d2.reasons[-1]


# ---------- batas keamanan dari kode ----------


async def test_buy_answer_becomes_signal_with_code_enforced_sl_tp(ctx: StrategyContext) -> None:
    up = with_trends(ctx, 1)
    seen: list[dict[str, Any]] = []
    s = ai({**BUY, "sl_atr": 9, "tp_rr": 1.2}, seen)
    await s.prepare(up)
    d = s.evaluate(up)
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert d.action is Action.BUY and d.confidence == 0.8
    atr = float(up.m15["atr"].iloc[-1])
    entry = float(up.m15["close"].iloc[-1])
    # SL dibatasi 3×ATR (AI minta 9×), R:R dinaikkan ke minimal 2 setelah spread
    assert d.entry - d.stop_loss == pytest.approx(3 * atr, abs=0.02)
    assert d.take_profit - entry == pytest.approx(2 * (3 * atr + 0.25) + 0.25, abs=0.02)


async def test_low_confidence_waits(ctx: StrategyContext) -> None:
    s = ai({**SELL, "confidence": 0.4})
    await s.prepare(ctx)
    d = s.evaluate(ctx)
    assert d.action is Action.WAIT and "40%" in d.reasons[0]


async def test_invalid_answer_waits(ctx: StrategyContext) -> None:
    s = ai("bukan json")
    await s.prepare(ctx)
    d = s.evaluate(ctx)
    assert d.action is Action.WAIT and "AI belum bisa menganalisis" in d.reasons[0]


async def test_trend_guard_blocks_counter_trend_sell(ctx: StrategyContext) -> None:
    up = with_trends(ctx, 1)
    s = ai(SELL)
    await s.prepare(up)
    d = s.evaluate(up)
    assert d.action is Action.WAIT
    assert "melawan tren" in d.reasons[0] and "H1" in d.reasons[0]


async def test_close_and_hold_with_open_position(ctx: StrategyContext) -> None:
    candle = ctx.m15.index[-4].to_pydatetime()
    active = ActiveSignalView(1, Action.BUY, 4000.0, 3995.0, 4010.0, candle)
    with_pos = StrategyContext(ctx.instrument, ctx.now, ctx.m15, ctx.h1, ctx.h4, 0.25, active)

    closer = ai({"action": "CLOSE", "confidence": 0.7, "reasons": ["Momentum berbalik."]}, votes=3)
    await closer.prepare(with_pos)
    assert closer.calls == 1  # posisi aktif: cukup satu pertanyaan
    assert closer.evaluate(with_pos).action is Action.WAIT
    assert "Momentum berbalik" in (closer.should_close(with_pos, active) or "")
    assert "OPEN POSITION: BUY" in build_prompt(with_pos, closer.params)

    holder = ai({**BUY, "confidence": 0.9})
    await holder.prepare(with_pos)
    assert holder.evaluate(with_pos).action is Action.WAIT  # tidak masuk ulang arah yang sama
    assert holder.should_close(with_pos, active) is None


def test_registered_as_ai_source() -> None:
    s = create_strategy("ai_groq")
    assert s.source == "ai" and s.narrate is False
    assert s.params.prefilter and s.params.votes == 3


def test_parse_groq_durations() -> None:
    from app.analysis.groq_client import parse_duration

    assert parse_duration("577ms") == pytest.approx(0.577)
    assert parse_duration("7.66s") == pytest.approx(7.66)
    assert parse_duration("1m2.5s") == pytest.approx(62.5)
    assert parse_duration("2h35m31.2s") == pytest.approx(9331.2)
    assert parse_duration(None) == 0


async def test_daily_quota_exhausted_fails_fast(ctx: StrategyContext) -> None:
    from app.analysis import groq_client

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429, headers={"retry-after": "612"}, json={"error": {"message": "TPD"}}
        )

    client = GroqClient("k", "m", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(groq_client.GroqError, match="harian habis"):
            await client.chat_json("s", "u")
        with pytest.raises(groq_client.GroqError, match="aktif lagi"):
            await client.chat_json("s", "u")  # tidak menembak API lagi selama diblokir
        assert calls == 1
    finally:
        groq_client._budget["blocked_until"] = 0.0


async def test_passive_mode_never_calls_ai(ctx: StrategyContext) -> None:
    seen: list[dict[str, Any]] = []
    candle = ctx.m15.index[-4].to_pydatetime()
    active = ActiveSignalView(1, Action.SELL, 4000.0, 4005.0, 3990.0, candle)
    with_pos = StrategyContext(ctx.instrument, ctx.now, ctx.m15, ctx.h1, ctx.h4, 0.25, active)
    s = ai({"action": "CLOSE", "confidence": 0.9, "reasons": ["x"]}, seen, passive=True)
    await s.prepare(with_pos)
    assert seen == [] and s.calls == 0
    d = s.evaluate(with_pos)
    assert d.action is Action.WAIT and "Analisis AI" in d.reasons[0]
    assert s.should_close(with_pos, active) is None  # TP/SL tetap diurus mesin, bukan AI
