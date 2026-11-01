"""Strategi AI (eksperimen): LLM Groq menilai setup yang sudah disaring kode.

Alur per analisis (versi 2). Frame entry = M15 bawaan, atau M1–H4 pilihan pengguna:
1. Kode menghitung fakta pasar per timeframe (tren, urutan EMA, zona RSI, MACD, ADX, posisi
   Bollinger, swing high/low) — LLM tidak perlu menebak dari deretan angka.
2. Tanpa posisi: AI hanya dipanggil bila kode melihat CALON SETUP searah tren (pullback ke
   EMA20 atau breakout 20 candle; H1 bertren dan H4 tidak berlawanan). Selain itu → WAIT.
3. AI ditanya `votes` kali; BUY/SELL hanya bila mayoritas sepakat dan searah calon setup.
4. Batas keamanan ditegakkan kode: SL sl_atr_min..sl_atr_max × ATR, R:R >= min_rr setelah
   spread, keyakinan >= min_confidence, tidak melawan tren H1/H4.
Dengan posisi AI aktif: satu kali tanya HOLD/CLOSE/berbalik.

Tidak bisa di-replay gratis (memanggil API); evaluasi historis lewat `python -m app.cli ai-eval`.
"""

import asyncio
import logging
import statistics
from collections import Counter
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator

from app.analysis.groq_client import GroqClient, GroqError, get_groq_client
from app.analysis.risk import price_to_pips
from app.strategies.base import (
    Action,
    ActiveSignalView,
    Decision,
    Strategy,
    StrategyContext,
    register,
)
from app.strategies.common import TREND_TEXT, net_rr, take_profit_distance, trend_of
from app.strategies.features import Setup, SetupFilter, potential_setup, timeframe_facts

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a disciplined forex/gold technical analyst reviewing ONE candidate
trade on the entry timeframe stated in the prompt. All facts (trend, EMA order, RSI zone,
MACD, ADX, Bollinger position, swing levels, candlestick patterns "pola") were computed by
code and are correct — trust them, do not re-derive them from raw prices.

Rules:
- Without an open position answer "BUY", "SELL" or "WAIT". A candidate setup direction is
  given; confirm it only if the facts support it (trend alignment H4/H1/entry timeframe, momentum
  agreeing, room to the next swing level, not overextended). Otherwise WAIT. Never trade
  against the H1 or H4 trend. Size stops and targets for the entry timeframe (e.g. M1/M5 =
  short scalp, H4 = multi-day swing). A candlestick pattern against the trade (e.g. Evening Star,
  Shooting Star, Three Black Crows for a BUY) or a Spinning Top is a reason to WAIT; a pattern
  in the trade direction (e.g. Hammer, Morning Star for a BUY) supports it.
- HISTORICAL EVIDENCE (if given) is this instrument's real track record computed by code:
  how often each detected candlestick pattern was right, how the code chart read performed,
  and how YOUR past trades did. Weigh it heavily: a pattern marked NOT reliable is noise; a
  RELIABLE pattern against the trade is a reason to WAIT; if your recent record is poor, demand
  stronger confirmation. Prefer fewer, higher-quality trades — WAIT is always acceptable.
- With an open position answer "HOLD", "CLOSE" (exit early because momentum clearly turned
  against the position) or the opposite direction (reverse). Do not re-enter the same side.
- "sl_atr": stop-loss distance in multiples of the entry-timeframe ATR (1.0-3.0), e.g.
  beyond the swing level.
- "tp_rr": take-profit as reward/risk multiple (>= 2.0).
- "confidence": 0.0-1.0, honest; below 0.6 means you would not take the trade.
- "reasons": 2-4 short reasons in simple Indonesian (bahasa Indonesia) using only the facts.
  No financial advice language, no promises of profit.
Respond with JSON only:
{"action": "...", "sl_atr": 1.5, "tp_rr": 2.0, "confidence": 0.6, "reasons": ["..."]}"""


class AiGroqParams(BaseModel):
    min_confidence: float = Field(default=0.6, ge=0, le=1)
    sl_atr_min: float = Field(default=1.0, gt=0, le=10)
    sl_atr_max: float = Field(default=3.0, gt=0, le=10)
    min_rr: float = Field(default=2.0, ge=1, le=10)
    m15_candles: int = Field(default=12, ge=4, le=120)
    # Tolak usulan AI yang melawan tren H1/H4 (dihitung kode: harga & EMA50 vs EMA200)
    trend_guard: bool = True
    # Panggil AI hanya bila kode melihat calon setup (hemat kuota, kurangi sinyal asal)
    prefilter: bool = True
    # Jumlah jawaban AI untuk entry baru; BUY/SELL hanya bila mayoritas sepakat
    votes: int = Field(default=3, ge=1, le=5)
    vote_gap_seconds: float = Field(default=3.0, ge=0, le=60)
    # Pasif: tidak memanggil AI; hanya memantau TP/SL/batas waktu posisi AI yang aktif
    # (dipakai worker — analisis AI hanya dijalankan saat tombol "Analisis AI" ditekan)
    passive: bool = False
    # Penajam calon setup (sama dengan strategi setup_trend; pilih lewat riset)
    setup_filter: SetupFilter = Field(default_factory=SetupFilter)


class AiAnswer(BaseModel):
    action: Literal["BUY", "SELL", "WAIT", "HOLD", "CLOSE"]
    sl_atr: float = 1.5
    tp_rr: float = 2.0
    confidence: float = Field(default=0.5, ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)

    @field_validator("sl_atr", "tp_rr", "confidence", "reasons", mode="before")
    @classmethod
    def _null_to_default(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None:
            return cls.model_fields[info.field_name].get_default(call_default_factory=True)
        return value


def build_prompt(ctx: StrategyContext, params: AiGroqParams, setup: Setup | None = None) -> str:
    inst = ctx.instrument
    d = inst.digits
    tf = ctx.timeframe
    lines = [
        f"Entry timeframe: {tf}.",
        f"Instrument: {inst.symbol} ({inst.name}), pip size {inst.pip_size}, "
        f"spread ~{ctx.spread_price / inst.pip_size:.1f} pips, "
        f"time (UTC) {ctx.now:%Y-%m-%d %H:%M}.",
    ]
    if ctx.active:
        a = ctx.active
        last = float(ctx.m15["close"].iloc[-1])
        direction = 1 if a.action is Action.BUY else -1
        pnl = (last - a.entry) * direction / inst.pip_size
        bars = int((ctx.m15.index > a.candle_time).sum())
        lines.append(
            f"OPEN POSITION: {a.action} entry {a.entry}, SL {a.stop_loss}, TP {a.take_profit}, "
            f"open {bars} {tf} candles, unrealized {pnl:+.1f} pips."
        )
    else:
        lines.append("OPEN POSITION: none.")
    if setup:
        side = "BUY" if setup.direction == 1 else "SELL"
        lines.append(f"CANDIDATE SETUP (code): {side} — {setup.note}.")

    if ctx.evidence:
        lines.append("HISTORICAL EVIDENCE (code, this instrument):")
        lines.extend(f"- {note}" for note in ctx.evidence)

    frames = {"H4": ctx.h4, "H1": ctx.h1, tf.value: ctx.m15}  # entry H1/H4: tanpa duplikat
    for label, df in frames.items():
        facts = timeframe_facts(df, d)
        lines.append(f"{label}: " + "; ".join(f"{k} {v}" for k, v in facts.items()))

    lines.append(f"{tf} last {params.m15_candles} candles (old→new) open/high/low/close:")
    for _, row in ctx.m15.tail(params.m15_candles).iterrows():
        lines.append(" ".join(f"{row[k]:.{d}f}" for k in ("open", "high", "low", "close")))
    return "\n".join(lines)


def combine_votes(answers: list[AiAnswer]) -> tuple[AiAnswer | None, str]:
    """Jawaban mayoritas (> separuh suara). None bila AI tidak sepakat."""
    counts = Counter(a.action for a in answers)
    action, count = counts.most_common(1)[0]
    summary = ", ".join(a.action for a in answers)
    if count * 2 <= len(answers):
        return None, summary
    agreeing = [a for a in answers if a.action == action]
    best = max(agreeing, key=lambda a: a.confidence)
    merged = AiAnswer(
        action=action,
        sl_atr=statistics.median(a.sl_atr for a in agreeing),
        tp_rr=statistics.median(a.tp_rr for a in agreeing),
        confidence=round(statistics.mean(a.confidence for a in agreeing), 2),
        reasons=best.reasons,
    )
    return merged, summary


@register
class AiGroqStrategy(Strategy):
    name = "ai_groq"
    Params = AiGroqParams
    params: AiGroqParams
    source: ClassVar[str] = "ai"
    narrate: ClassVar[bool] = False

    def __init__(
        self, params: BaseModel | dict[str, Any] | None = None, client: GroqClient | None = None
    ) -> None:
        super().__init__(params)
        self._client = client
        self.calls = 0  # jumlah panggilan API (untuk evaluasi kuota)
        self.reset()

    @property
    def wants_evidence(self) -> bool:
        return not self.params.passive

    def reset(self) -> None:
        self._answer: AiAnswer | None = None
        self._error: str | None = None
        self._skip: str | None = None
        self._setup: Setup | None = None
        self._votes = ""

    async def _ask(self, prompt: str) -> AiAnswer | None:
        client = self._client or get_groq_client()
        self.calls += 1
        try:
            return AiAnswer.model_validate(await client.chat_json(SYSTEM_PROMPT, prompt))
        except (GroqError, ValidationError) as exc:
            self._error = str(exc)[:200]
            return None

    async def prepare(self, ctx: StrategyContext) -> None:
        self.reset()
        p = self.params
        if p.passive:
            self._skip = "Tekan tombol Analisis AI untuk meminta keputusan AI terbaru."
            return
        if ctx.active is None and p.prefilter:
            self._setup = potential_setup(ctx.m15, ctx.h1, ctx.h4, p.setup_filter)
            if self._setup is None:
                t1, t4 = trend_of(ctx.h1).direction, trend_of(ctx.h4).direction
                self._skip = (
                    f"Belum ada calon setup searah tren (H4 {TREND_TEXT[t4]}, "
                    f"H1 {TREND_TEXT[t1]}); AI tidak dipanggil."
                )
                return
        prompt = build_prompt(ctx, p, self._setup)
        n = 1 if ctx.active else p.votes
        answers = []
        for i in range(n):
            if i and p.vote_gap_seconds:
                await asyncio.sleep(p.vote_gap_seconds)
            if (answer := await self._ask(prompt)) is not None:
                answers.append(answer)
        if not answers:
            logger.warning("AI %s gagal: %s", ctx.instrument.symbol, self._error)
            return
        self._answer, self._votes = combine_votes(answers)
        if self._answer is None:
            self._skip = f"AI tidak sepakat ({self._votes}), jadi menunggu."

    def _reasons(self) -> list[str]:
        assert self._answer is not None
        reasons = [r.strip() for r in self._answer.reasons if r.strip()][:4]
        # Pastikan tiap alasan diakhiri tanda baca agar enak dibaca saat digabung
        reasons = [r if r[-1] in ".!?" else f"{r}." for r in reasons]
        return reasons or ["AI tidak memberi alasan."]

    def evaluate(self, ctx: StrategyContext) -> Decision:
        p = self.params
        if self._skip:
            return Decision(Action.WAIT, reasons=[self._skip], details={"ai_votes": self._votes})
        if self._answer is None:
            return Decision(
                Action.WAIT,
                reasons=[f"AI belum bisa menganalisis: {self._error or 'tidak ada jawaban'}"],
            )
        ans = self._answer
        details: dict[str, Any] = {
            "ai_action": ans.action,
            "ai_confidence": ans.confidence,
            "ai_votes": self._votes,
        }
        reasons = self._reasons()
        votes = f" (suara: {self._votes})" if "," in self._votes else ""
        conf_text = f"Keyakinan AI {ans.confidence:.0%}{votes}."

        if ans.action not in ("BUY", "SELL"):
            label = {"WAIT": "menunggu", "HOLD": "tahan posisi", "CLOSE": "tutup posisi"}
            return Decision(
                Action.WAIT,
                reasons=[f"AI: {label[ans.action]}. {conf_text}", *reasons],
                details=details,
            )
        if ctx.active and Action(ans.action) == ctx.active.action:
            return Decision(
                Action.WAIT, reasons=[f"AI: tahan posisi {ans.action}.", *reasons], details=details
            )
        if ans.confidence < p.min_confidence:
            return Decision(
                Action.WAIT,
                reasons=[
                    f"AI condong {ans.action} tetapi keyakinannya {ans.confidence:.0%} "
                    f"(< {p.min_confidence:.0%}), jadi menunggu.",
                    *reasons,
                ],
                details=details,
            )
        direction = 1 if ans.action == "BUY" else -1
        if self._setup and self._setup.direction != direction:
            return Decision(
                Action.WAIT,
                reasons=[f"AI menyarankan {ans.action}, berlawanan dengan calon setup — menunggu."],
                details=details,
            )
        if p.trend_guard:
            against = [
                label
                for label, df in (("H4", ctx.h4), ("H1", ctx.h1))
                if trend_of(df).direction == -direction
            ]
            if against:
                word = "turun" if direction == 1 else "naik"
                return Decision(
                    Action.WAIT,
                    reasons=[
                        f"AI menyarankan {ans.action}, tetapi tren {'/'.join(against)} {word} "
                        "— diabaikan agar tidak melawan tren.",
                        *reasons,
                    ],
                    details=details,
                )

        last = ctx.m15.iloc[-1]
        atr = float(last["atr"])
        sl_dist = min(max(ans.sl_atr, p.sl_atr_min), p.sl_atr_max) * atr
        tp_dist = take_profit_distance(sl_dist, ctx.spread_price, max(ans.tp_rr, p.min_rr))
        rr = net_rr(sl_dist, tp_dist, ctx.spread_price)
        entry = float(last["close"])
        inst = ctx.instrument
        details.update(
            atr=atr, risk_reward=round(rr, 2), setup=self._setup.kind if self._setup else None
        )
        return Decision(
            Action(ans.action),
            entry=inst.round_price(entry),
            stop_loss=inst.round_price(entry - direction * sl_dist),
            take_profit=inst.round_price(entry + direction * tp_dist),
            confidence=round(ans.confidence, 2),
            reasons=[
                *reasons,
                f"{conf_text} SL {price_to_pips(sl_dist, inst)} pip, "
                f"TP {price_to_pips(tp_dist, inst)} pip, R:R 1:{rr:.1f} setelah spread.",
            ],
            details=details,
        )

    def should_close(self, ctx: StrategyContext, active: ActiveSignalView) -> str | None:
        if self._answer and self._answer.action == "CLOSE":
            return "AI menyarankan tutup posisi: " + " ".join(self._reasons()[:2])
        return None
