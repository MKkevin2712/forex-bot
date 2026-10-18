"""Faux courtier en mémoire pour tester le bot sans compte réel."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from forex_bot.brokers.base import CANDLE_COLUMNS, Broker
from forex_bot.models import Account, ClosedTrade, Fill, InstrumentSpec, OpenTrade, Quote


def trend_candles(
    n: int = 400,
    start: float = 1.0,
    step: float = 0.0005,
    noise: float = 0.0002,
    start_time: str = "2026-01-05",
    freq: str = "4h",
    seed: int = 0,
) -> pd.DataFrame:
    """Série en tendance régulière avec un peu de bruit et un volume croissant en fin de série."""
    rng = np.random.default_rng(seed)
    close = start + step * np.arange(n) + rng.normal(0, noise, n)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + abs(step) + noise
    low = np.minimum(open_, close) - abs(step) - noise
    volume = np.full(n, 1000.0)
    volume[-1] = 2000.0
    times = pd.date_range(start_time, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {"time": times, "open": open_, "high": high, "low": low, "close": close, "volume": volume},
        columns=CANDLE_COLUMNS,
    )


class FakeBroker(Broker):
    name = "fake"

    def __init__(self, candles: dict[str, pd.DataFrame], balance: float = 10_000.0) -> None:
        self._candles = candles
        self.balance = balance
        self.trades: dict[str, OpenTrade] = {}
        self.closed: dict[str, ClosedTrade] = {}
        self.orders: list[dict] = []
        self.drop_stop_loss = False  # simule un SL non posé
        self._next_id = 1

    def account(self) -> Account:
        return Account(self.balance, self.balance, "USD")

    def instrument_spec(self, instrument: str) -> InstrumentSpec:
        jpy = instrument.endswith("JPY")
        return InstrumentSpec(instrument, 0.01 if jpy else 0.0001, 3 if jpy else 5)

    def candles(self, instrument: str, granularity: str, count: int) -> pd.DataFrame:
        return self._candles[instrument].tail(count).reset_index(drop=True)

    def quote(self, instrument: str) -> Quote:
        last = float(self._candles[instrument]["close"].iloc[-1])
        return Quote(last - 0.00005, last + 0.00005)

    def value_per_unit(self, instrument: str) -> float:
        return 1.0

    def open_trades(self) -> list[OpenTrade]:
        return list(self.trades.values())

    def market_order(self, instrument, units, stop_loss, take_profit) -> Fill:
        trade_id = str(self._next_id)
        self._next_id += 1
        q = self.quote(instrument)
        price = q.ask if units > 0 else q.bid
        self.orders.append(
            {"instrument": instrument, "units": units, "sl": stop_loss, "tp": take_profit}
        )
        sl = None if self.drop_stop_loss else stop_loss
        self.trades[trade_id] = OpenTrade(trade_id, instrument, units, price, sl, take_profit)
        return Fill(trade_id, instrument, units, price, datetime.now(UTC))

    def closed_trade(self, trade_id: str) -> ClosedTrade | None:
        return self.closed.get(trade_id)

    def close_trade(self, trade_id: str) -> None:
        trade = self.trades.pop(trade_id)
        self.closed[trade_id] = ClosedTrade(
            trade_id, trade.entry_price, datetime.now(UTC), 0.0, "MANUEL"
        )

    def hit(self, trade_id: str, reason: str, pnl: float, when: datetime | None = None) -> None:
        """Simule la clôture d'une position par le courtier (SL ou TP)."""
        trade = self.trades.pop(trade_id)
        price = trade.stop_loss if reason == "SL" else trade.take_profit
        self.closed[trade_id] = ClosedTrade(trade_id, price, when or datetime.now(UTC), pnl, reason)
        self.balance += pnl
