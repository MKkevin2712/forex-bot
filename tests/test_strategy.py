import pandas as pd
import pytest
from fakes import trend_candles

from forex_bot.config import StrategyParams
from forex_bot.indicators import atr, ema, rsi
from forex_bot.models import LONG, SHORT
from forex_bot.strategy import compute_indicators, evaluate, stop_and_target

P = StrategyParams()


def test_rsi_bounds_and_pure_uptrend():
    close = pd.Series(range(1, 60), dtype=float)
    values = rsi(close).dropna()
    assert values.between(0, 100).all()
    assert values.iloc[-1] == 100.0  # aucune baisse


def test_atr_positive_and_ema_matches_pandas():
    df = trend_candles(100)
    assert (atr(df).dropna() > 0).all()
    expected = df["close"].ewm(span=20, adjust=False).mean()
    pd.testing.assert_series_equal(ema(df["close"], 20).iloc[19:], expected.iloc[19:])


def test_uptrend_gives_long_and_downtrend_gives_short():
    params = StrategyParams(rsi_long_max=101, rsi_short_min=-1)  # isole le filtre de tendance
    up = compute_indicators(trend_candles(400, step=0.0005), params).iloc[-1]
    down = compute_indicators(trend_candles(400, start=2.0, step=-0.0005), params).iloc[-1]
    assert evaluate(up, params).direction == LONG
    assert evaluate(down, params).direction == SHORT


def test_overbought_uptrend_is_skipped():
    row = compute_indicators(trend_candles(400, noise=0), P).iloc[-1]
    decision = evaluate(row, P)
    assert decision.direction is None
    assert "RSI" in decision.reason


def test_volume_filter():
    params = StrategyParams(rsi_long_max=101)
    df = trend_candles(400)
    df.loc[df.index[-1], "volume"] = 10.0
    decision = evaluate(compute_indicators(df, params).iloc[-1], params)
    assert decision.direction is None and "volume" in decision.reason
    no_filter = params.model_copy(update={"use_volume_filter": False})
    assert evaluate(compute_indicators(df, no_filter).iloc[-1], no_filter).direction == LONG


def test_not_enough_history():
    row = compute_indicators(trend_candles(50), P).iloc[-1]
    assert evaluate(row, P).direction is None


def test_stop_and_target_are_symmetric():
    sl, tp = stop_and_target(LONG, 1.1000, 0.0020, P)
    assert sl == pytest.approx(1.0970) and tp == pytest.approx(1.1045)
    sl, tp = stop_and_target(SHORT, 1.1000, 0.0020, P)
    assert sl == pytest.approx(1.1030) and tp == pytest.approx(1.0955)
