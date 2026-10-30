from datetime import UTC, datetime, timedelta

from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.services.prediction_log import on_time_limit, result_pips


def test_on_time_limit_scales_with_timeframe() -> None:
    entry = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
    assert on_time_limit(entry, Timeframe.M1) == entry + timedelta(seconds=30)
    assert on_time_limit(entry, Timeframe.M15) == entry + timedelta(minutes=3)
    assert on_time_limit(entry, Timeframe.H4) == entry + timedelta(minutes=48)


def test_result_pips_net_of_spread(xauusd: Instrument) -> None:
    pip = xauusd.pip_size
    # BUY naik 10 pip, spread 2.5 → +7.5; SELL pada gerakan yang sama → -12.5
    assert result_pips(1, 4000.0, 4000.0 + 10 * pip, xauusd, 2.5) == 7.5
    assert result_pips(-1, 4000.0, 4000.0 + 10 * pip, xauusd, 2.5) == -12.5


async def test_record_then_resolve_forward_prediction(db_session, xauusd: Instrument) -> None:  # noqa: ANN001
    """Hammer terbukti → prediksi BUY dicatat tepat waktu, lalu hasilnya diisi setelah candle
    berikutnya tutup. Data sintetis bertanggal masa depan, transaksi di-rollback."""
    import json

    import numpy as np
    from fakeredis import FakeAsyncRedis
    from sqlalchemy import select

    from app.data.schemas import CandleDTO
    from app.db.models import PatternPrediction
    from app.repositories import candles as candles_repo
    from app.services.pattern_stats import CACHE_KEY, HORIZON
    from app.services.prediction_log import (
        prediction_summary,
        record_predictions,
        resolve_predictions,
    )

    tf = Timeframe.M1
    end = datetime(2027, 3, 3, 8, 0, tzinfo=UTC)  # Rabu, pasar buka
    n = 300
    close = 4100 - np.arange(n) * 0.4
    bars = [
        CandleDTO(end - timedelta(minutes=n - 1 - i), c + 0.3, c + 0.6, c - 0.6, float(c))
        for i, c in enumerate(close)
    ]
    base = bars[-2].close
    bars[-1] = CandleDTO(end, base, base + 0.35, base - 3.0, base + 0.3)  # Hammer
    await candles_repo.upsert_candles(db_session, xauusd.symbol, tf, bars, "test")

    redis = FakeAsyncRedis(decode_responses=True)
    key = CACHE_KEY.format(horizon=HORIZON, symbol=xauusd.symbol, timeframe=tf.value)
    await redis.set(key, json.dumps({"Hammer": {"samples": 200, "hits": 140}}))

    now = end + timedelta(minutes=1, seconds=10)  # candle Hammer baru tutup
    assert await record_predictions(db_session, redis, xauusd, tf, now) == 1
    assert await record_predictions(db_session, redis, xauusd, tf, now) == 0  # tidak dobel

    entry_close = base + 0.3
    nxt = CandleDTO(
        end + timedelta(minutes=1), entry_close, entry_close + 2, entry_close - 1, entry_close + 1.0
    )
    await candles_repo.upsert_candles(db_session, xauusd.symbol, tf, [nxt], "test")
    assert await resolve_predictions(db_session, end + timedelta(minutes=2, seconds=5)) == 1

    p = (
        await db_session.execute(
            select(PatternPrediction).where(
                PatternPrediction.symbol == xauusd.symbol, PatternPrediction.timeframe == "M1"
            )
        )
    ).scalar_one()
    assert p.direction == 1 and p.on_time and p.status == "done"
    assert p.result_pips == result_pips(
        1, entry_close, entry_close + 1.0, xauusd, xauusd.typical_spread_pips
    )
    summary = await prediction_summary(db_session, xauusd.symbol, tf)
    assert summary["done"] >= 1


def test_best_exit_picks_shortest_near_best_hold(xauusd: Instrument) -> None:
    from app.services.pattern_stats import PatternStat, best_exit

    pip = xauusd.pip_size
    # rata-rata gerak 2, 5, 9.5, 10, 8 … pip; spread 1 → bersih 9.0 (k=4) terbaik, 8.5 (k=3) ≥ 90%
    moves = tuple(m * pip for m in (2, 5, 9.5, 10, 8, 6, 4, 3))
    stat = PatternStat(
        100, 60, moves=moves, wins=(50, 55, 60, 62, 58, 55, 52, 50), hold_samples=100
    )
    plan = best_exit(stat, pip, 1.0)
    assert plan is not None and plan.hold == 3 and plan.pips == 8.5 and plan.win_rate == 0.6
    # Tidak ada yang untung setelah spread / data kurang → tanpa rencana
    assert (
        best_exit(
            PatternStat(100, 60, moves=(0.5 * pip,) * 8, wins=(0,) * 8, hold_samples=100), pip, 1.0
        )
        is None
    )
    assert (
        best_exit(PatternStat(100, 60, moves=moves, wins=(0,) * 8, hold_samples=10), pip, 1.0)
        is None
    )
    assert best_exit(PatternStat(100, 60), pip, 1.0) is None


async def test_resolve_uses_best_close_candle(db_session, xauusd: Instrument) -> None:  # noqa: ANN001
    """Prediksi dengan CLOSE setelah 3 candle dinilai dari close candle ke-3, bukan ke-1."""
    from app.data.schemas import CandleDTO
    from app.db.models import PatternPrediction
    from app.repositories import candles as candles_repo
    from app.services.prediction_log import resolve_predictions

    tf = Timeframe.M1
    entry = datetime(2027, 3, 4, 8, 0, tzinfo=UTC)
    p = PatternPrediction(
        symbol=xauusd.symbol,
        timeframe="M1",
        pattern="Hammer",
        direction=1,
        chance=0.6,
        samples=100,
        pattern_time=entry - tf.delta,
        entry_time=entry,
        close_time=entry + 3 * tf.delta,
        entry_price=4000.0,
        spread_pips=0.0,
        status="open",
        on_time=True,
    )
    db_session.add(p)
    closes = [4000.5, 4001.0, 4002.0]
    bars = [CandleDTO(entry + i * tf.delta, c, c + 1, c - 1, c) for i, c in enumerate(closes[:2])]
    await candles_repo.upsert_candles(db_session, xauusd.symbol, tf, bars, "test")
    now = entry + 3 * tf.delta + timedelta(seconds=5)
    assert await resolve_predictions(db_session, now) == 0  # candle ke-3 belum tersimpan
    c = closes[2]
    await candles_repo.upsert_candles(
        db_session, xauusd.symbol, tf, [CandleDTO(entry + 2 * tf.delta, c, c + 1, c - 1, c)], "test"
    )
    assert await resolve_predictions(db_session, now) == 1
    assert p.exit_price == 4002.0 and p.result_pips == result_pips(1, 4000.0, 4002.0, xauusd, 0.0)
