"""Model tampilan untuk dashboard: instrumen, candle, kartu sinyal (harga sudah
disesuaikan ke broker, jarak pip, status entry, saran lot)."""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.config import get_analysis_config
from app.analysis.lifecycle import TrailingStopConfig, trailing_stops
from app.analysis.risk import price_to_pips, suggest_lot
from app.core.instruments import Instrument
from app.core.market_hours import is_market_open, next_market_open
from app.core.timeframes import Timeframe, next_candle_close
from app.data.schemas import CandleDTO
from app.db.models import Candle, InstrumentSetting, Signal
from app.repositories import candles as candles_repo
from app.repositories import signals as signals_repo
from app.services.calibration import adjust_price
from app.services.live_candle import latest_cached_price
from app.services.risk_prefs import RiskPrefs
from app.services.signal_engine import candles_to_frame, get_latest_analysis
from app.services.signal_exit import best_close, cached_exit_profile
from app.strategies import Action

# Harga live dianggap segar selama ini; setelahnya dipakai penutupan candle M15 terakhir
LIVE_PRICE_MAX_AGE = timedelta(minutes=2)

STATUS_LABELS = {
    "ACTIVE": "aktif",
    "EXPIRED": "kedaluwarsa",
    "HIT_TP": "kena TP",
    "HIT_SL": "kena SL",
    "CLOSED": "ditutup",
}


class EntryState(StrEnum):
    VALID = "VALID"
    EXPIRED_TIME = "EXPIRED_TIME"
    EXPIRED_DISTANCE = "EXPIRED_DISTANCE"
    CLOSED = "CLOSED"


ENTRY_STATE_LABELS = {
    EntryState.VALID: "masih bisa masuk",
    EntryState.EXPIRED_TIME: "kedaluwarsa, jangan masuk (sinyal sudah terlalu lama)",
    EntryState.EXPIRED_DISTANCE: "kedaluwarsa, jangan masuk (harga sudah terlalu jauh dari entry)",
    EntryState.CLOSED: "sinyal sudah selesai",
}


# ---------- Instrumen & candle ----------


class InstrumentOut(BaseModel):
    symbol: str
    name: str
    asset_class: str
    pip_size: float
    digits: int
    contract_size: float
    spread_pips: float
    spread_is_custom: bool
    signal_validity_pips: float
    price_offset: float
    price_offset_pips: float
    broker_price: float | None
    feed_price: float | None
    calibrated_at: datetime | None
    market_open: bool
    next_open: datetime | None


def spread_pips_of(inst: Instrument, setting: InstrumentSetting | None) -> float:
    if setting and setting.spread_pips is not None:
        return setting.spread_pips
    return inst.typical_spread_pips


def instrument_out(
    inst: Instrument, setting: InstrumentSetting | None, now: datetime
) -> InstrumentOut:
    offset = setting.price_offset if setting else 0.0
    market_open = is_market_open(inst.asset_class, now)
    return InstrumentOut(
        symbol=inst.symbol,
        name=inst.name,
        asset_class=inst.asset_class,
        pip_size=inst.pip_size,
        digits=inst.digits,
        contract_size=inst.contract_size,
        spread_pips=spread_pips_of(inst, setting),
        spread_is_custom=bool(setting and setting.spread_pips is not None),
        signal_validity_pips=inst.signal_validity_pips,
        price_offset=offset,
        price_offset_pips=round(offset / inst.pip_size, 1),
        broker_price=setting.broker_price if setting else None,
        feed_price=setting.feed_price if setting else None,
        calibrated_at=setting.calibrated_at if setting else None,
        market_open=market_open,
        next_open=None if market_open else next_market_open(inst.asset_class, now),
    )


class CandleOut(BaseModel):
    time: int = Field(description="Unix timestamp UTC waktu buka candle")
    open: float
    high: float
    low: float
    close: float


def candle_out(c: CandleDTO | Candle, offset: float, digits: int) -> CandleOut:
    return CandleOut(
        time=int(c.open_time.timestamp()),
        open=adjust_price(c.open, offset, digits),
        high=adjust_price(c.high, offset, digits),
        low=adjust_price(c.low, offset, digits),
        close=adjust_price(c.close, offset, digits),
    )


# ---------- Harga terkini ----------


class PriceInfo(BaseModel):
    price: float = Field(description="Harga FEED (belum disesuaikan offset)")
    source: str = Field(description="live = live candle; last_close = penutupan M15 terakhir")
    updated_at: datetime


async def current_price(
    session: AsyncSession, redis: Redis, symbol: str, now: datetime
) -> PriceInfo | None:
    cached = await latest_cached_price(redis, symbol)
    if cached and now - cached[1] <= LIVE_PRICE_MAX_AGE:
        return PriceInfo(price=cached[0], source="live", updated_at=cached[1])
    rows = await candles_repo.get_candles(session, symbol, Timeframe.M15, limit=1)
    if not rows:
        return None
    last = rows[-1]
    return PriceInfo(
        price=last.close, source="last_close", updated_at=last.open_time + Timeframe.M15.delta
    )


# ---------- Kartu sinyal ----------


class BestCloseOut(BaseModel):
    hold: int = Field(description="CLOSE setelah sekian candle sejak masuk")
    close_at: datetime = Field(description="Perkiraan waktu CLOSE dengan rata-rata untung terbesar")
    avg_pips: float = Field(description="Rata-rata hasil bersih historis bila CLOSE di close_at")
    win_rate: float
    samples: int = Field(description="Jumlah transaksi historis strategi ini yang dinilai")
    strategy_pips: float = Field(
        description="Rata-rata hasil bila mengikuti aturan keluar strategi (TP/SL/CLOSE) apa adanya"
    )


class SignalView(BaseModel):
    id: int
    source: str = Field(description="rule = strategi teruji, ai = AI Groq (eksperimen)")
    symbol: str
    instrument_name: str
    digits: int
    pip_size: float
    action: str
    closes_action: str | None = Field(description="Untuk CLOSE: aksi yang ditutup (BUY/SELL)")
    parent_id: int | None
    strategy: str
    timeframe: Timeframe = Field(description="Timeframe entry sinyal")
    signal_time: datetime = Field(description="Waktu sinyal = waktu tutup candle pemicu")
    created_at: datetime

    price_offset: float
    entry: float | None = Field(description="Sudah disesuaikan ke harga broker")
    stop_loss: float | None
    take_profit: float | None
    trailing_stop: float | None = Field(
        default=None, description="SL terkini setelah trailing stop bergeser (disesuaikan broker)"
    )
    take_profit_active: bool = Field(
        default=True, description="false = TP dilepas; posisi ditutup trailing stop / sinyal"
    )
    sl_pips: float | None
    tp_pips: float | None
    risk_reward: float | None
    spread_pips: float | None

    confidence: float | None
    confidence_label: str | None
    reason_text: str
    reasons: list[str]

    status: str
    status_label: str
    entry_state: EntryState
    entry_state_label: str
    entry_valid_until: datetime | None
    validity_pips: float
    current_price: float | None = Field(description="Harga terkini (disesuaikan ke broker)")
    price_source: str | None
    price_updated_at: datetime | None
    distance_from_entry_pips: float | None = Field(
        description="Positif = harga bergerak searah sinyal, negatif = berlawanan"
    )

    capital: float | None
    risk_percent: float
    risk_amount: float | None
    suggested_lot: float | None

    closed_at: datetime | None
    close_price: float | None
    close_reason: str | None
    result_pips: float | None

    best_close: BestCloseOut | None = Field(
        default=None, description="Perkiraan waktu CLOSE terbaik (sinyal aktif strategi)"
    )
    best_close_note: str | None = Field(
        default=None, description="Penjelasan bila perkiraan CLOSE terbaik tidak tersedia"
    )


def entry_state(
    signal: Signal, now: datetime, price: float | None, validity_pips: float, pip_size: float
) -> tuple[EntryState, float | None]:
    """Apakah sinyal masih layak dimasuki? Mengembalikan (status, jarak bertanda dalam pip)."""
    distance: float | None = None
    if price is not None and signal.entry is not None and signal.action in ("BUY", "SELL"):
        direction = 1 if signal.action == "BUY" else -1
        distance = round((price - signal.entry) * direction / pip_size, 1)
    if signal.status != "ACTIVE":
        return EntryState.CLOSED, distance
    if signal.entry_expires_at and now > signal.entry_expires_at:
        return EntryState.EXPIRED_TIME, distance
    if distance is not None and abs(distance) > validity_pips:
        return EntryState.EXPIRED_DISTANCE, distance
    return EntryState.VALID, distance


def build_signal_view(
    signal: Signal,
    instrument: Instrument,
    *,
    offset: float,
    now: datetime,
    price: PriceInfo | None,
    prefs: RiskPrefs,
    closes_action: str | None = None,
    trailing_stop: float | None = None,
    take_profit_active: bool = True,
) -> SignalView:
    digits = instrument.digits

    def adj(value: float | None) -> float | None:
        return adjust_price(value, offset, digits) if value is not None else None

    raw_price = price.price if price else None
    state, distance = entry_state(
        signal, now, raw_price, instrument.signal_validity_pips, instrument.pip_size
    )
    if signal.action == "CLOSE":
        status = "CLOSED"
    elif signal.status == "ACTIVE" and state in (
        EntryState.EXPIRED_TIME,
        EntryState.EXPIRED_DISTANCE,
    ):
        status = "EXPIRED"
    else:
        status = signal.status or "CLOSED"

    lot = risk_amount = None
    is_entry = signal.action in ("BUY", "SELL")
    if is_entry and prefs.capital and signal.entry is not None and signal.stop_loss is not None:
        lot = suggest_lot(
            instrument,
            capital=prefs.capital,
            risk_percent=prefs.risk_percent,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
        )
        risk_amount = round(prefs.capital * prefs.risk_percent / 100, 2)

    def pips(a: float | None, b: float | None) -> float | None:
        return price_to_pips(a - b, instrument) if a is not None and b is not None else None

    return SignalView(
        id=signal.id,
        source="ai" if signal.strategy == signals_repo.AI_STRATEGY else "rule",
        symbol=signal.symbol,
        instrument_name=instrument.name,
        digits=digits,
        pip_size=instrument.pip_size,
        action=signal.action,
        closes_action=closes_action,
        parent_id=signal.parent_id,
        strategy=signal.strategy,
        timeframe=Timeframe(signal.timeframe),
        signal_time=signal.candle_time + Timeframe(signal.timeframe).delta,
        created_at=signal.created_at,
        price_offset=offset,
        entry=adj(signal.entry),
        stop_loss=adj(signal.stop_loss),
        take_profit=adj(signal.take_profit),
        trailing_stop=adj(trailing_stop),
        take_profit_active=take_profit_active,
        sl_pips=pips(signal.entry, signal.stop_loss),
        tp_pips=pips(signal.take_profit, signal.entry),
        risk_reward=signal.risk_reward,
        spread_pips=signal.spread_pips,
        confidence=signal.confidence,
        confidence_label=signal.confidence_label,
        reason_text=signal.reason_text,
        reasons=list(signal.reasons or []),
        status=status,
        status_label=STATUS_LABELS.get(status, status.lower()),
        entry_state=state,
        entry_state_label=ENTRY_STATE_LABELS[state],
        entry_valid_until=signal.entry_expires_at,
        validity_pips=instrument.signal_validity_pips,
        current_price=adj(raw_price),
        price_source=price.source if price else None,
        price_updated_at=price.updated_at if price else None,
        distance_from_entry_pips=distance if is_entry else None,
        capital=prefs.capital,
        risk_percent=prefs.risk_percent,
        risk_amount=risk_amount,
        suggested_lot=lot,
        closed_at=signal.closed_at,
        close_price=adj(signal.close_price),
        close_reason=signal.close_reason,
        result_pips=signal.result_pips,
    )


async def load_signal_view(
    session: AsyncSession,
    redis: Redis,
    signal: Signal,
    instrument: Instrument,
    setting: InstrumentSetting | None,
    prefs: RiskPrefs,
    now: datetime,
    price: PriceInfo | None = None,
) -> SignalView:
    closes_action = None
    if signal.action == "CLOSE" and signal.parent_id:
        parent = await session.get(Signal, signal.parent_id)
        closes_action = parent.action if parent else None
    if price is None and signal.status == "ACTIVE":
        price = await current_price(session, redis, signal.symbol, now)
    trail_cfg = get_analysis_config().trailing_stop
    stop = None
    if trail_cfg.enabled and signal.status == "ACTIVE" and signal.action in ("BUY", "SELL"):
        stop = await _current_trailing_stop(session, signal, instrument, setting, trail_cfg)
    view = build_signal_view(
        signal,
        instrument,
        offset=setting.price_offset if setting else 0.0,
        now=now,
        price=price,
        prefs=prefs,
        closes_action=closes_action,
        trailing_stop=stop,
        take_profit_active=not trail_cfg.enabled or trail_cfg.take_profit,
    )
    if signal.status == "ACTIVE" and view.source == "rule" and signal.action in ("BUY", "SELL"):
        await attach_best_close(view, signal, redis)
    return view


async def attach_best_close(view: SignalView, signal: Signal, redis: Redis) -> None:
    """Perkiraan CLOSE terbaik dari histori strategi ini (cache worker)."""
    profile = await cached_exit_profile(redis, signal.symbol, signal.strategy)
    plan = best_close(profile)
    if profile is None:
        view.best_close_note = "Perkiraan waktu CLOSE sedang dihitung dari histori strategi."
    elif plan is None:
        view.best_close_note = (
            f"Dari {profile.samples} transaksi historis, tidak ada waktu tutup tetap yang "
            "rata-ratanya untung — ikuti SL/TP dan sinyal CLOSE."
        )
    else:
        tf = Timeframe(signal.timeframe)
        view.best_close = BestCloseOut(
            hold=plan.hold,
            close_at=signal.candle_time + tf.delta * (1 + plan.hold),
            avg_pips=plan.pips,
            win_rate=plan.win_rate,
            samples=plan.samples,
            strategy_pips=profile.strategy_pips,
        )


async def _current_trailing_stop(
    session: AsyncSession,
    signal: Signal,
    instrument: Instrument,
    setting: InstrumentSetting | None,
    cfg: TrailingStopConfig,
) -> float | None:
    """SL terkini dari candle tutup sejak sinyal (sama persis dengan pengecekan exit)."""
    assert signal.entry is not None and signal.stop_loss is not None
    tf = Timeframe(signal.timeframe)
    rows = await candles_repo.get_candles(
        session, signal.symbol, tf, start=signal.candle_time + tf.delta, limit=5000
    )
    # Spread sama dengan yang dipakai mesin sinyal saat mengecek exit
    spread_pips = (
        setting.spread_pips
        if setting and setting.spread_pips is not None
        else instrument.typical_spread_pips
    )
    spread = spread_pips * instrument.pip_size
    stop = trailing_stops(
        Action(signal.action), signal.stop_loss, signal.entry, candles_to_frame(rows), spread, cfg
    )[-1]
    return instrument.round_price(stop) if stop != signal.stop_loss else None


# ---------- Kartu instrumen (layar utama) ----------


class AnalysisOut(BaseModel):
    analyzed_at: datetime
    timeframe: Timeframe = Field(default=Timeframe.M15, description="Timeframe entry analisis")
    candle_time: datetime | None
    reasons: list[str]
    filters: list[str]
    details: dict[str, Any]


class InstrumentCard(BaseModel):
    source: str = Field(default="rule", description="rule = strategi teruji, ai = AI Groq")
    instrument: InstrumentOut
    action: str = Field(description="BUY / SELL / CLOSE / WAIT yang ditampilkan di kartu")
    is_new_event: bool
    analysis: AnalysisOut | None
    signal: SignalView | None
    current_price: float | None = Field(description="Disesuaikan ke broker")
    price_source: str | None
    price_updated_at: datetime | None
    next_candle_close: datetime


async def build_card(
    session: AsyncSession,
    redis: Redis,
    instrument: Instrument,
    setting: InstrumentSetting | None,
    prefs: RiskPrefs,
    now: datetime,
    source: str = "rule",
) -> InstrumentCard:
    symbol = instrument.symbol
    snap = await get_latest_analysis(redis, symbol, source)
    signal: Signal | None = None
    if snap:
        if snap.get("is_new_event") and snap.get("event_ids"):
            signal = await session.get(Signal, snap["event_ids"][-1])
        elif snap.get("signal_id"):
            signal = await session.get(Signal, snap["signal_id"])
    if signal is None:
        signal = await signals_repo.get_active_for_symbol(session, symbol, source=source)

    if snap:
        action = snap["action"]
    else:
        action = signal.action if signal and signal.status == "ACTIVE" else "WAIT"

    price = await current_price(session, redis, symbol, now)
    offset = setting.price_offset if setting else 0.0
    view = (
        await load_signal_view(session, redis, signal, instrument, setting, prefs, now, price)
        if signal
        else None
    )
    analysis = (
        AnalysisOut(
            analyzed_at=snap["analyzed_at"],
            timeframe=snap.get("timeframe", Timeframe.M15),
            candle_time=snap.get("candle_time"),
            reasons=snap.get("reasons", []),
            filters=snap.get("filters", []),
            details=snap.get("details", {}),
        )
        if snap
        else None
    )
    return InstrumentCard(
        source=source,
        instrument=instrument_out(instrument, setting, now),
        action=action,
        is_new_event=bool(snap and snap.get("is_new_event")),
        analysis=analysis,
        signal=view,
        current_price=adjust_price(price.price, offset, instrument.digits) if price else None,
        price_source=price.source if price else None,
        price_updated_at=price.updated_at if price else None,
        next_candle_close=next_candle_close(now, Timeframe.M15),
    )
