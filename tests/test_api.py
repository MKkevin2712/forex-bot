from datetime import UTC, datetime

from fakes import FakeBroker, trend_candles
from fastapi.testclient import TestClient

from forex_bot.api import create_app
from forex_bot.journal import SQLiteJournal
from forex_bot.models import ClosedTrade


def make_client(settings):
    broker = FakeBroker({"EUR_USD": trend_candles(600)})
    journal = SQLiteJournal(":memory:")
    journal.record_open(
        {
            "broker": "fake",
            "broker_trade_id": "1",
            "instrument": "EUR_USD",
            "direction": "LONG",
            "units": 1000,
            "entry_time": "2026-10-19T08:00:00+00:00",
            "entry_price": 1.1,
            "stop_loss": 1.09,
            "take_profit": 1.115,
            "risk_amount": 10,
            "signal_reason": "test",
            "indicators": {"rsi": 55},
        }
    )
    journal.record_close(
        "fake", ClosedTrade("1", 1.115, datetime(2026, 10, 20, tzinfo=UTC), 15.0, "TP")
    )
    app = create_app(settings, broker_factory=lambda s: broker, journal=journal)
    return TestClient(app)


def test_overview(settings):
    data = make_client(settings).get("/api/overview").json()
    assert data["account"]["balance"] == 10_000
    assert data["stats"]["trades"] == 1 and data["stats"]["win_rate"] == 100.0
    assert data["broker_error"] is None


def test_config_has_no_secrets(settings):
    data = make_client(settings).get("/api/config").json()
    assert "oanda_token" not in data and data["instruments"] == ["EUR_USD"]


def test_candles_are_valid_json(settings):
    data = make_client(settings).get("/api/candles/EUR_USD?count=100").json()
    assert len(data["candles"]) == 100
    assert data["trades"][0]["close_reason"] == "TP"


def test_trades(settings):
    trades = make_client(settings).get("/api/trades").json()
    assert trades[0]["indicators"] == {"rsi": 55}


def test_backtest_endpoint(settings):
    response = make_client(settings).post(
        "/api/backtest",
        json={"count": 600, "strategy": {"rsi_long_max": 101, "use_volume_filter": False}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["trades"] > 0 and body["equity"]


def test_broker_down_still_returns_journal(settings):
    from forex_bot.brokers import BrokerError

    def failing(_):
        raise BrokerError("pas de connexion")

    app = create_app(settings, broker_factory=failing, journal=SQLiteJournal(":memory:"))
    data = TestClient(app).get("/api/overview").json()
    assert data["account"] is None and "pas de connexion" in data["broker_error"]
