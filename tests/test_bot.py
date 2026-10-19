"""Le bot en conditions réelles simulées, dont les bugs corrigés de la version crypto."""

from datetime import UTC, datetime

import pytest
from fakes import FakeBroker, trend_candles

from forex_bot.bot import TradingBot
from forex_bot.journal import SQLiteJournal
from forex_bot.state import StateStore

WEDNESDAY = datetime(2026, 10, 21, 12, tzinfo=UTC)


@pytest.fixture
def make_bot(settings):
    settings = settings.model_copy(
        update={"strategy": settings.strategy.model_copy(update={"rsi_long_max": 101})}
    )

    def factory(candles=None, now=WEDNESDAY, **overrides):
        s = settings.model_copy(update=overrides)
        broker = FakeBroker(candles or {"EUR_USD": trend_candles(400)})
        journal = SQLiteJournal(":memory:")
        bot = TradingBot(broker, journal, s, StateStore(s.state_path), clock=lambda: now)
        return bot, broker, journal

    return factory


def test_opens_long_with_stop_and_target(make_bot):
    bot, broker, journal = make_bot()
    bot.run_cycle()
    assert len(broker.orders) == 1
    order = broker.orders[0]
    assert order["units"] > 0 and order["sl"] < order["tp"]
    [trade] = journal.trades()
    assert trade["direction"] == "LONG" and trade["status"] == "OPEN"
    # risque réel proche de 1 % du capital
    assert trade["risk_amount"] == pytest.approx(100, rel=0.05)


def test_no_second_position_on_same_pair(make_bot):
    """Bug 1 de la version crypto : le bot rachetait alors qu'une position était ouverte."""
    bot, broker, _ = make_bot()
    bot.run_cycle()
    broker._candles["EUR_USD"] = trend_candles(401)  # nouvelle bougie, signal toujours présent
    bot.run_cycle()
    assert len(broker.orders) == 1
    assert "déjà ouverte" in bot.state.data["analyses"]["EUR_USD"]["action"]


def test_same_candle_not_processed_twice(make_bot):
    bot, broker, _ = make_bot()
    bot.run_cycle()
    broker.trades.clear()
    bot.run_cycle()
    assert len(broker.orders) == 1


def test_position_without_stop_is_closed(make_bot):
    """Bug 2 : une position ne doit jamais rester ouverte sans stop-loss."""
    bot, broker, journal = make_bot()
    broker.drop_stop_loss = True
    bot.run_cycle()
    assert broker.open_trades() == []
    assert journal.trades() == []


def test_reconcile_records_real_pnl(make_bot):
    """Bug 5 : le P&L vient du courtier, pas d'une estimation par proximité de prix."""
    bot, broker, journal = make_bot()
    bot.run_cycle()
    trade_id = journal.trades()[0]["broker_trade_id"]
    broker.hit(trade_id, "TP", 150.0)
    bot.reconcile()
    [trade] = journal.trades()
    assert trade["status"] == "CLOSED" and trade["pnl"] == 150.0 and trade["close_reason"] == "TP"


def test_daily_loss_limit_blocks_new_trades(make_bot):
    bot, broker, journal = make_bot()
    bot.run_cycle()
    trade_id = journal.trades()[0]["broker_trade_id"]
    broker.hit(trade_id, "SL", -400.0, when=WEDNESDAY)
    broker._candles["EUR_USD"] = trend_candles(401)
    bot.run_cycle()
    assert len(broker.orders) == 1
    assert "perte journalière" in bot.state.data["analyses"]["EUR_USD"]["action"]


def test_dry_run_sends_nothing(make_bot):
    bot, broker, _ = make_bot(dry_run=True)
    bot.run_cycle()
    assert broker.orders == []
    assert "simulation" in bot.state.data["analyses"]["EUR_USD"]["action"]


def test_weekend_does_nothing(make_bot):
    bot, broker, _ = make_bot(now=datetime(2026, 10, 24, 12, tzinfo=UTC))
    bot.run_cycle()
    assert broker.orders == []
    assert "fermé" in bot.state.data["status"]


def test_run_forever_stops_after_repeated_failures(make_bot, monkeypatch):
    """Le bot s'arrête après des erreurs répétées pour que le superviseur le relance."""
    from forex_bot import bot as bot_module

    bot, broker, _ = make_bot()
    monkeypatch.setattr(bot_module.time, "sleep", lambda s: None)

    def broken():
        raise ConnectionError("terminal MT5 fermé")

    broker.account = broken
    with pytest.raises(ConnectionError):
        bot.run_forever()
    assert "terminal MT5 fermé" in bot.state.data["last_error"]["message"]


def test_max_open_trades(make_bot):
    candles = {"EUR_USD": trend_candles(400), "GBP_USD": trend_candles(400, start=1.3)}
    bot, broker, _ = make_bot(
        candles=candles, instruments=["EUR_USD", "GBP_USD"], max_open_trades=1
    )
    bot.run_cycle()
    assert len(broker.orders) == 1
