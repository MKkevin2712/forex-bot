import pandas as pd
import pytest
from fakes import trend_candles

from forex_bot.backtest import conversion_pairs, run_backtest, value_per_unit


def _bt_settings(settings):
    return settings.model_copy(
        update={
            "strategy": settings.strategy.model_copy(
                update={"rsi_long_max": 101, "use_volume_filter": False}
            )
        }
    )


def test_uptrend_is_profitable_with_take_profits(settings):
    result = run_backtest({"EUR_USD": trend_candles(600)}, _bt_settings(settings))
    stats = result.stats
    assert stats["trades"] > 0
    assert all(t["direction"] == "LONG" for t in result.trades)
    assert result.final_balance > result.initial_balance
    assert {t["close_reason"] for t in result.trades} <= {"TP", "SL", "FIN"}


def test_stop_loss_wins_when_both_hit_same_bar(settings):
    s = _bt_settings(settings)
    df = trend_candles(400)
    # bougie suivante très large : touche le SL et le TP
    last = df.iloc[-1]
    big = {
        "time": last["time"] + pd.Timedelta(hours=4),
        "open": last["close"],
        "high": last["close"] + 0.05,
        "low": last["close"] - 0.05,
        "close": last["close"],
        "volume": 1000,
    }
    wide = pd.concat([df, pd.DataFrame([big])], ignore_index=True)
    result = run_backtest({"EUR_USD": wide}, s)
    assert result.trades[-1]["close_reason"] == "SL"
    assert result.trades[-1]["pnl"] < 0


def test_no_lookahead(settings):
    """Le résultat sur les N premières bougies ne dépend pas des bougies suivantes."""
    s = _bt_settings(settings)
    full = trend_candles(600)
    short = run_backtest({"EUR_USD": full.head(500)}, s)
    long = run_backtest({"EUR_USD": full}, s)
    closed_early = [t for t in short.trades if t["close_reason"] != "FIN"]
    assert closed_early == long.trades[: len(closed_early)]


def test_eur_account_converts_usd_gains(settings):
    """Compte en EUR : les gains en USD de GBP/USD sont convertis au cours EUR/USD du moment."""
    s = _bt_settings(settings)
    gbp = trend_candles(600, start=1.3)
    eurusd = trend_candles(600, start=1.25, step=0, noise=0)  # EUR/USD fixe à 1,25
    usd = run_backtest({"GBP_USD": gbp}, s, account_currency="USD")
    eur = run_backtest({"GBP_USD": gbp}, s, account_currency="EUR", conversions={"EUR_USD": eurusd})
    assert conversion_pairs(["GBP_USD", "USD_JPY"], "EUR") == ["EUR_JPY", "EUR_USD"]
    # même risque de 1 % en EUR : la taille en unités est 1,25 fois plus grande, le P&L en EUR
    # par trade identique en proportion du capital
    assert eur.trades[0]["units"] == pytest.approx(usd.trades[0]["units"] * 1.25, rel=0.01)
    assert eur.stats["total_pnl"] == pytest.approx(usd.stats["total_pnl"], rel=0.05)
    with pytest.raises(ValueError, match="EUR_USD"):
        run_backtest({"GBP_USD": gbp}, s, account_currency="EUR")


def test_value_per_unit():
    assert value_per_unit("EUR_USD", 1.1) == 1.0
    assert value_per_unit("USD_JPY", 150.0) == pytest.approx(1 / 150)
    with pytest.raises(ValueError):
        value_per_unit("EUR_GBP", 0.85)
