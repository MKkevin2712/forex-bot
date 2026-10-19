from datetime import UTC, datetime, timedelta

from fakes import FakeBroker, trend_candles

from forex_bot.journal import SQLiteJournal
from forex_bot.models import ClosedTrade, OpenTrade
from forex_bot.report import build_report, format_discord, money, send_discord

NOW = datetime(2026, 10, 21, 20, tzinfo=UTC)


def _journal():
    journal = SQLiteJournal(":memory:")
    for trade_id, entry, exit_, pnl, reason in [
        ("old", NOW - timedelta(days=3), NOW - timedelta(days=2), -50.0, "SL"),
        ("t1", NOW - timedelta(hours=10), NOW - timedelta(hours=2), 150.0, "TP"),
        ("t2", NOW - timedelta(hours=9), NOW - timedelta(hours=1), -80.25, "SL"),
    ]:
        journal.record_open(
            {
                "broker": "fake",
                "broker_trade_id": trade_id,
                "instrument": "EUR_USD",
                "direction": "LONG",
                "units": 20000,
                "entry_time": entry.isoformat(),
                "entry_price": 1.1,
                "stop_loss": 1.09,
                "take_profit": 1.115,
            }
        )
        journal.record_close("fake", ClosedTrade(trade_id, 1.1, exit_, pnl, reason))
    return journal


def test_report_counts_only_last_24h(settings):
    broker = FakeBroker({"EUR_USD": trend_candles(10)}, balance=50_000)
    broker.trades["9"] = OpenTrade("9", "USD_JPY", -3000, 158.0, 159.0, 156.0, 12.5)
    state = {
        "heartbeat": (NOW - timedelta(minutes=1)).isoformat(),
        "signals": [
            {
                "time": (NOW - timedelta(days=2)).isoformat(),
                "instrument": "EUR_USD",
                "signal": "LONG",
                "action": "vieux",
            },
            {
                "time": (NOW - timedelta(hours=4)).isoformat(),
                "instrument": "GBP_USD",
                "signal": "SHORT",
                "action": "simulation : vente",
            },
        ],
    }
    report = build_report(_journal(), settings, state, broker, now=NOW)
    assert report["realized_today"] == 69.75
    assert [t["broker_trade_id"] for t in report["closed_today"]] == ["t2", "t1"]
    assert [s["action"] for s in report["signals"]] == ["simulation : vente"]
    assert report["bot_alive"] is True and report["stats"]["trades"] == 3

    embed = format_discord(report)["embeds"][0]
    values = {f["name"]: f["value"] for f in embed["fields"]}
    assert values["Résultat du jour"] == "+69,75 $"  # le faux courtier est en USD
    assert "TP · **+150,00 $**" in values["Trades clôturés (24 h)"]
    assert values["Positions ouvertes"] == "USD/JPY Vente 3 000 u. · latent +12,50 $"
    assert "GBP/USD Vente" in values["Signaux du jour (UTC)"]
    assert embed["color"] == 0x2FC89A


def test_report_warns_when_bot_silent_and_broker_down(settings):
    state = {"heartbeat": (NOW - timedelta(hours=5)).isoformat()}
    report = build_report(SQLiteJournal(":memory:"), settings, state, broker=None, now=NOW)
    embed = format_discord(report)["embeds"][0]
    assert "ne répond plus" in embed["description"]
    assert {f["name"]: f["value"] for f in embed["fields"]}["Trades clôturés (24 h)"] == "Aucun"


def test_long_lists_fit_discord_limit(settings):
    state = {
        "heartbeat": NOW.isoformat(),
        "signals": [
            {
                "time": (NOW - timedelta(minutes=i)).isoformat(),
                "instrument": "EUR_USD",
                "signal": "LONG",
                "action": "x" * 60,
            }
            for i in range(100)
        ],
    }
    report = build_report(SQLiteJournal(":memory:"), settings, state, now=NOW)
    for field in format_discord(report)["embeds"][0]["fields"]:
        assert len(field["value"]) <= 1024


def test_money_format():
    assert money(1234.5, "EUR") == "1 234,50 €"
    assert money(-80.25, "EUR", signed=True) == "-80,25 €"
    assert money(0, "EUR", signed=True) == "0,00 €"


def test_send_discord(monkeypatch):
    sent = {}

    class Response:
        status_code = 204
        text = ""

    def fake_post(url, json, timeout):
        sent.update(url=url, json=json)
        return Response()

    monkeypatch.setattr("forex_bot.report.requests.post", fake_post)
    send_discord("https://discord.com/api/webhooks/x", {"content": "ok"})
    assert sent["json"] == {"content": "ok"}
