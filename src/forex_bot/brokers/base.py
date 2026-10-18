"""Interface commune à tous les courtiers : le bot et le backtest ne connaissent que celle-ci."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from forex_bot.models import Account, ClosedTrade, Fill, InstrumentSpec, OpenTrade, Quote

CANDLE_COLUMNS = ["time", "open", "high", "low", "close", "volume"]


class BrokerError(Exception):
    """Erreur renvoyée par le courtier (ordre refusé, réseau, symbole inconnu...)."""


class BrokerAuthError(BrokerError):
    """Identifiants refusés : inutile de réessayer."""


class Broker(ABC):
    name: str

    @abstractmethod
    def account(self) -> Account: ...

    @abstractmethod
    def instrument_spec(self, instrument: str) -> InstrumentSpec: ...

    @abstractmethod
    def candles(self, instrument: str, granularity: str, count: int) -> pd.DataFrame:
        """Bougies CLÔTURÉES uniquement (prix médians), colonnes CANDLE_COLUMNS, temps en UTC."""

    @abstractmethod
    def quote(self, instrument: str) -> Quote: ...

    @abstractmethod
    def value_per_unit(self, instrument: str) -> float:
        """Gain ou perte, en devise du compte, d'1 unité quand le prix bouge de 1,0."""

    @abstractmethod
    def open_trades(self) -> list[OpenTrade]:
        """Positions ouvertes par le bot."""

    @abstractmethod
    def market_order(
        self, instrument: str, units: float, stop_loss: float, take_profit: float
    ) -> Fill:
        """Ordre au marché avec SL et TP attachés DANS LE MÊME ORDRE (jamais de position nue)."""

    @abstractmethod
    def closed_trade(self, trade_id: str) -> ClosedTrade | None:
        """Détails de clôture d'une position, ou None si elle est encore ouverte."""

    @abstractmethod
    def close_trade(self, trade_id: str) -> None: ...

    def close_all(self) -> list[str]:
        closed = []
        for trade in self.open_trades():
            self.close_trade(trade.id)
            closed.append(trade.id)
        return closed
