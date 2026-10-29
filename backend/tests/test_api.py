"""Test API via ASGI (butuh PostgreSQL & Redis compose; dilewati bila tidak tersedia)."""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import redis as redis_module
from app.db.session import engine
from app.main import app
from app.services.risk_prefs import get_risk_prefs, save_risk_prefs


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    original = await get_risk_prefs(db_session)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await save_risk_prefs(db_session, original)
    # Pool DB & klien Redis global terikat event loop test ini; tutup agar test berikutnya
    # (event loop baru) membuat koneksi baru.
    await redis_module.close_redis()
    await engine.dispose()


async def test_risk_settings_roundtrip(client: httpx.AsyncClient) -> None:
    resp = await client.put("/settings/risk", json={"capital": 2500, "risk_percent": 1.5})
    assert resp.status_code == 200
    assert (await client.get("/settings/risk")).json() == {"capital": 2500.0, "risk_percent": 1.5}

    bad = await client.put("/settings/risk", json={"capital": -1, "risk_percent": 50})
    assert bad.status_code == 422


async def test_dashboard_shape(client: httpx.AsyncClient) -> None:
    resp = await client.get("/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert 0 <= body["seconds_to_next_candle"] <= 900
    symbols = [card["instrument"]["symbol"] for card in body["cards"]]
    assert {"XAUUSD", "EURUSD", "GBPUSD", "USDJPY"} <= set(symbols)
    for card in body["cards"]:
        assert card["action"] in {"BUY", "SELL", "CLOSE", "WAIT"}


async def test_candles_with_indicator_series(client: httpx.AsyncClient) -> None:
    resp = await client.get(
        "/candles",
        params={
            "symbol": "EURUSD",
            "timeframe": "H1",
            "limit": 50,
            "indicators": "true",
            "include_live": "false",
        },  # fmt: skip
    )
    assert resp.status_code == 200
    body = resp.json()
    if not body["candles"]:
        pytest.skip("Belum ada candle EURUSD H1 di database")
    times = [c["time"] for c in body["candles"]]
    ind = body["indicators"]
    assert set(ind) >= {"ema20", "ema200", "bb_upper", "rsi", "macd_hist"}
    # Deret indikator sejajar dengan candle yang ditampilkan dan sudah 'panas' (ada warm-up)
    assert [p["time"] for p in ind["ema20"]] == times
    assert all(0 <= p["value"] <= 100 for p in ind["rsi"])


async def test_unknown_symbol_and_signal(client: httpx.AsyncClient) -> None:
    assert (await client.get("/signals/latest", params={"symbol": "NOPE"})).status_code == 404
    assert (await client.get("/signals/999999999")).status_code == 404


async def test_ai_cooldown_returns_retry_after(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fakeredis import FakeAsyncRedis

    from app.api import ai as ai_api

    fake = FakeAsyncRedis()
    await fake.set("ai:cooldown:XAUUSD", "1", ex=30)
    monkeypatch.setattr(ai_api, "get_redis", lambda: fake)
    monkeypatch.setattr(ai_api, "ai_signals_enabled", lambda: True)

    resp = await client.post("/analysis/ai?symbol=XAUUSD")
    assert resp.status_code == 429
    assert 0 < int(resp.headers["retry-after"]) <= 30
    assert "Tunggu" in resp.json()["detail"]


async def test_candles_explain_exhausted_daily_quota(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import market
    from app.data.providers import get_provider
    from app.data.providers.mock import MockProvider

    class Exhausted(MockProvider):
        async def remaining_daily_credits(self) -> int | None:
            return 0

    async def no_refresh(*_: object) -> None:  # jangan menulis candle mock ke DB
        return None

    monkeypatch.setattr(market, "refresh_if_stale", no_refresh)
    app.dependency_overrides[get_provider] = Exhausted
    try:
        resp = await client.get("/candles?symbol=XAUUSD&timeframe=H4&include_live=false")
    finally:
        app.dependency_overrides.pop(get_provider, None)
    assert resp.status_code == 200
    assert resp.json()["warning"] == market.quota_exhausted_warning("mock")


async def test_switch_data_provider(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import settings as settings_api
    from app.core.config import get_settings
    from app.data.providers import SwitchableProvider, get_provider
    from app.data.providers.mock import MockProvider

    saved: dict[str, str] = {}

    async def load() -> str | None:
        return saved.get("data_provider")

    async def fake_set(_: object, key: str, value: str) -> None:  # jangan ubah DB pengguna
        saved[key] = value

    sw = SwitchableProvider(
        {"twelvedata": MockProvider(), "tiingo": MockProvider()}, "twelvedata", load
    )
    monkeypatch.setattr(settings_api.app_settings, "set_value", fake_set)
    monkeypatch.setattr(get_settings(), "tiingo_api_key", type(get_settings().tiingo_api_key)("k"))
    app.dependency_overrides[get_provider] = lambda: sw
    try:
        state = (await client.get("/settings/data-provider")).json()
        assert state["active"] == "twelvedata" and {o["id"] for o in state["options"]} == {
            "twelvedata",
            "tiingo",
        }
        resp = await client.put("/settings/data-provider", json={"provider": "tiingo"})
        assert resp.status_code == 200 and resp.json()["active"] == "tiingo"
        assert (
            await client.put("/settings/data-provider", json={"provider": "oanda"})
        ).status_code == 422
    finally:
        app.dependency_overrides.pop(get_provider, None)
