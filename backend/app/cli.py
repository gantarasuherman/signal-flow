"""Perintah manual. Contoh (di dalam container):

python -m app.cli price XAUUSD
python -m app.cli sync
python -m app.cli backfill --timeframe M15 --days 365
python -m app.cli backfill --symbols XAUUSD,EURUSD --timeframe H1 --days 400
python -m app.cli analyze                 # jalankan analisis sekarang (menyimpan sinyal)
python -m app.cli scan --days 10          # replay strategi pada data tersimpan (tanpa simpan)
python -m app.cli backtest --days 365     # backtest lengkap + in/out-of-sample (tanpa simpan)
python -m app.cli prune                   # hapus candle di luar jam pasar (mis. akhir pekan)
python -m app.cli research --days 365     # uji kandidat strategi per instrumen (IS/OOS)
"""

import argparse
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.analysis.config import get_analysis_config, get_strategy_for
from app.analysis.replay import replay
from app.backtest.ai_eval import evaluate_ai
from app.backtest.research import run_research
from app.backtest.runner import BacktestRequest, run_backtest
from app.core.config import get_settings
from app.core.instruments import Instrument, get_instruments
from app.core.logging import setup_logging
from app.core.market_hours import candle_has_trading
from app.core.redis import close_redis, get_redis
from app.core.timeframes import Timeframe
from app.data.providers import close_provider, get_provider
from app.data.providers.base import MAX_BATCH
from app.db.session import SessionLocal, engine
from app.repositories import candles as candles_repo
from app.services.candle_sync import only_closed, sync_candles
from app.services.signal_engine import analyze_instrument, candles_to_frame

logger = logging.getLogger("cli")


def _select(symbols: str | None) -> list[Instrument]:
    instruments = get_instruments()
    if not symbols:
        return list(instruments.values())
    selected = []
    for symbol in symbols.upper().split(","):
        if symbol not in instruments:
            raise SystemExit(f"Instrumen {symbol} tidak terdaftar. Tersedia: {sorted(instruments)}")
        selected.append(instruments[symbol])
    return selected


async def cmd_price(args: argparse.Namespace) -> None:
    provider = get_provider()
    for instrument in _select(args.symbols):
        quote = await provider.fetch_price(instrument)
        print(
            f"{instrument.symbol}: {quote.price} ({provider.name}, {quote.timestamp:%H:%M:%S} UTC)"
        )


async def cmd_sync(args: argparse.Namespace) -> None:
    provider = get_provider()
    async with SessionLocal() as session:
        for instrument in _select(args.symbols):
            for timeframe in (Timeframe.M15, Timeframe.H1, Timeframe.H4):
                r = await sync_candles(session, provider, instrument, timeframe, datetime.now(UTC))
                print(
                    f"{r.symbol} {r.timeframe}: +{r.stored} candle, terakhir {r.latest_open_time}, "
                    f"terbaru={r.up_to_date}, bolong={len(r.gaps)}"
                )


async def cmd_backfill(args: argparse.Namespace) -> None:
    provider = get_provider()
    timeframe = Timeframe(args.timeframe)
    now = datetime.now(UTC)
    start = now - timedelta(days=args.days)
    window = timeframe.delta * MAX_BATCH

    async with SessionLocal() as session:
        for instrument in _select(args.symbols):
            total = 0
            cursor = start
            while cursor < now:
                chunk_end = min(cursor + window, now)
                candles = await provider.fetch_candles(
                    instrument, timeframe, start=cursor, end=chunk_end, limit=MAX_BATCH
                )
                closed = only_closed(candles, timeframe, now, instrument.asset_class)
                total += await candles_repo.upsert_candles(
                    session, instrument.symbol, timeframe, closed, provider.name
                )
                await session.commit()
                print(
                    f"{instrument.symbol} {timeframe}: "
                    f"{cursor:%Y-%m-%d} → {chunk_end:%Y-%m-%d} +{len(closed)}"
                )
                cursor = chunk_end
            print(f"{instrument.symbol} {timeframe}: selesai, {total} candle disimpan")


async def cmd_prune(args: argparse.Namespace) -> None:
    async with SessionLocal() as session:
        for instrument in _select(args.symbols):
            for timeframe in Timeframe:
                rows = await candles_repo.get_candles(
                    session, instrument.symbol, timeframe, limit=1_000_000
                )
                closed_market = [
                    r.open_time
                    for r in rows
                    if not candle_has_trading(instrument.asset_class, r.open_time, timeframe)
                ]
                if closed_market:
                    n = await candles_repo.delete_candles(
                        session, instrument.symbol, timeframe, closed_market
                    )
                    await session.commit()
                    print(f"{instrument.symbol} {timeframe}: {n} candle di luar jam pasar dihapus")


async def cmd_analyze(args: argparse.Namespace) -> None:
    async with SessionLocal() as session:
        for instrument in _select(args.symbols):
            snap = await analyze_instrument(session, get_redis(), instrument, datetime.now(UTC))
            print(f"\n{instrument.symbol}: {snap['action']}  (signal_id={snap['signal_id']})")
            for reason in snap["reasons"]:
                print(f"  - {reason}")
            for block in snap["filters"]:
                print(f"  ! filter: {block}")


async def cmd_scan(args: argparse.Namespace) -> None:
    cfg = get_analysis_config()
    start = datetime.now(UTC) - timedelta(days=args.days)
    async with SessionLocal() as session:
        for instrument in _select(args.symbols):
            frames = {
                tf: candles_to_frame(
                    await candles_repo.get_candles(session, instrument.symbol, tf, limit=50000)
                )
                for tf in (Timeframe.M15, Timeframe.H1, Timeframe.H4)
            }
            trades = replay(
                get_strategy_for(instrument.symbol),
                instrument,
                frames[Timeframe.M15],
                frames[Timeframe.H1],
                frames[Timeframe.H4],
                spread_pips=instrument.typical_spread_pips,
                filters=cfg.filters,
                max_hold_candles=cfg.max_hold_candles,
                profit_close=cfg.profit_close,
                start=start,
            )
            closed = [t for t in trades if t.result_pips is not None]
            wins = [t for t in closed if t.result_pips and t.result_pips > 0]
            total = sum(t.result_pips or 0 for t in closed)
            print(
                f"\n{instrument.symbol}: {len(trades)} sinyal dalam {args.days} hari, "
                f"{len(wins)}/{len(closed)} menang, total {total:+.1f} pip"
            )
            for t in trades[-args.show :]:
                print(
                    f"  {t.entry_time:%Y-%m-%d %H:%M} {t.action:<4} entry {t.entry} "
                    f"SL {t.stop_loss} TP {t.take_profit} conf {t.confidence:.2f} → "
                    f"{t.status} {t.result_pips if t.result_pips is not None else ''} "
                    f"{t.close_reason or ''}"
                )
    print(
        "\nCatatan: scan ini replay cepat tanpa slippage & filter berita, bukan backtest lengkap."
    )


def _fmt(m: dict) -> str:  # type: ignore[type-arg]
    def v(key: str, suffix: str = "") -> str:
        return "-" if m.get(key) is None else f"{m[key]}{suffix}"

    return (
        f"{m['trades']:>4} trade | win {v('win_rate', '%'):>6} | PF {v('profit_factor'):>5} | "
        f"exp {v('expectancy_r', 'R'):>7} | total {m['total_r']:>6}R {m['net_pips']:>8} pip | "
        f"DD {m['max_drawdown_pct']:>5}% | Sharpe {v('sharpe'):>5} | RR {v('avg_rr_realized')}"
    )


async def cmd_backtest(args: argparse.Namespace) -> None:
    req = BacktestRequest(
        symbols=args.symbols.split(",") if args.symbols else None,
        days=args.days,
        optimize=args.optimize,
    )
    async with SessionLocal() as session:
        summary = await run_backtest(session, req)
    period = summary["period"]
    print(f"\nBacktest {summary['strategy']['name']} {period['start'][:10]} → {period['end'][:10]}")
    for symbol, res in [*summary["instruments"].items(), ("PORTOFOLIO", summary["portfolio"])]:
        print(f"\n== {symbol}")
        print(f"  Semua         {_fmt(res['all'])}")
        print(f"  In-sample     {_fmt(res['in_sample'])}")
        print(f"  Out-of-sample {_fmt(res['out_of_sample'])}")
        for i, w in enumerate(res["windows"], 1):
            print(f"  Jendela {i} ({w['start'][:10]}) {_fmt(w)}")
        if opt := res.get("optimization"):
            print(f"  Optimasi IS → {opt['best_params']}")
            print(f"    IS  {_fmt(opt['best_in_sample'])}")
            print(f"    OOS {_fmt(opt['best_out_of_sample'])}")
    for note in summary["notes"]:
        print(f"* {note}")


async def cmd_ai_eval(args: argparse.Namespace) -> None:
    async with SessionLocal() as session:
        for symbol in args.symbols.upper().split(","):
            r = await evaluate_ai(
                session,
                symbol,
                args.days,
                max_calls=args.max_calls,
                votes=args.votes,
                call_gap_seconds=args.gap,
            )
            print(f"\n== {symbol} {r['period']['start'][:10]} → {r['period']['end'][:16]}")
            print(
                f"   Calon setup: {r['setups']} | ditanyakan ke AI: {r['ai_asked']} | "
                f"disetujui AI: {r['ai_accepted']} | panggilan API: {r['ai_calls']}"
            )
            print(f"   Tanpa AI (semua setup) {_fmt(r['baseline'])}")
            print(f"   Dengan AI             {_fmt(r['ai'])}")
    print("\n* Baseline = semua calon setup kode; AI = hanya yang disetujui AI.")


async def cmd_research(args: argparse.Namespace) -> None:
    async with SessionLocal() as session:
        result = await run_research(
            session,
            args.symbols.upper().split(",") if args.symbols else None,
            args.days,
            only=args.only,
        )
    print(f"\nRiset strategi {result['start'][:10]} → {result['end'][:10]} (IS 70% | OOS 30%)")
    for symbol, res in result["instruments"].items():
        print(f"\n== {symbol}")
        for c in res["candidates"]:
            mark = "→" if res["chosen"] and c["label"] == res["chosen"]["label"] else " "
            print(f" {mark} {c['label']:<30} IS  {_fmt(c['in_sample'])}")
            print(f"   {'':<30} OOS {_fmt(c['out_of_sample'])}")
        print(f"   Keputusan: {res['reason']}")
    if args.output:
        import json
        from pathlib import Path

        Path(args.output).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        print(f"\nHasil lengkap disimpan ke {args.output}")


async def run(args: argparse.Namespace) -> None:
    try:
        await args.handler(args)
    finally:
        await close_provider()
        await close_redis()
        await engine.dispose()


def main() -> None:
    setup_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(required=True)

    p_price = sub.add_parser("price", help="Tampilkan harga terkini dari provider")
    p_price.add_argument("symbols", nargs="?", help="Mis. XAUUSD,EURUSD (default: semua)")
    p_price.set_defaults(handler=cmd_price)

    p_sync = sub.add_parser("sync", help="Sinkronkan candle M15/H1/H4 sekarang")
    p_sync.add_argument("--symbols")
    p_sync.set_defaults(handler=cmd_sync)

    p_back = sub.add_parser("backfill", help="Ambil data historis (untuk backtest)")
    p_back.add_argument("--symbols")
    p_back.add_argument("--timeframe", default="M15", choices=[tf.value for tf in Timeframe])
    p_back.add_argument("--days", type=int, default=365)
    p_back.set_defaults(handler=cmd_backfill)

    p_analyze = sub.add_parser("analyze", help="Jalankan analisis sinyal sekarang")
    p_analyze.add_argument("--symbols")
    p_analyze.set_defaults(handler=cmd_analyze)

    p_scan = sub.add_parser("scan", help="Replay strategi pada candle tersimpan")
    p_scan.add_argument("--symbols")
    p_scan.add_argument("--days", type=int, default=10)
    p_scan.add_argument("--show", type=int, default=10, help="Jumlah sinyal terakhir ditampilkan")
    p_scan.set_defaults(handler=cmd_scan)

    p_bt = sub.add_parser("backtest", help="Backtest lengkap dengan in/out-of-sample")
    p_bt.add_argument("--symbols")
    p_bt.add_argument("--days", type=int, default=365)
    p_bt.add_argument("--optimize", action="store_true", help="Optimasi parameter di in-sample")
    p_bt.set_defaults(handler=cmd_backtest)

    p_prune = sub.add_parser("prune", help="Hapus candle di luar jam pasar")
    p_prune.add_argument("--symbols")
    p_prune.set_defaults(handler=cmd_prune)

    p_research = sub.add_parser("research", help="Uji kandidat strategi per instrumen (IS/OOS)")
    p_research.add_argument("--symbols")
    p_research.add_argument("--days", type=int, default=365)
    p_research.add_argument("--output", help="Simpan hasil lengkap ke file JSON")
    p_research.add_argument("--only", help="Hanya kandidat dengan label/strategi ini")
    p_research.set_defaults(handler=cmd_research)

    p_ai = sub.add_parser("ai-eval", help="Uji historis: apakah AI Groq menambah nilai?")
    p_ai.add_argument("--symbols", required=True)
    p_ai.add_argument("--days", type=int, default=30)
    p_ai.add_argument("--max-calls", type=int, default=120, help="Batas panggilan Groq")
    p_ai.add_argument("--votes", type=int, default=1)
    p_ai.add_argument("--gap", type=float, default=9.0, help="Jeda antar panggilan (detik)")
    p_ai.set_defaults(handler=cmd_ai_eval)

    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
