"""Objets échangés entre le bot, les courtiers et le journal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

LONG = "LONG"
SHORT = "SHORT"


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds")


def split_instrument(instrument: str) -> tuple[str, str]:
    """'EUR_USD' -> ('EUR', 'USD') : devise de base, devise de cotation."""
    base, quote = instrument.upper().split("_")
    return base, quote


@dataclass(frozen=True)
class Account:
    balance: float
    nav: float  # valeur liquidative : solde + P&L latent
    currency: str
    unrealized_pnl: float = 0.0
    margin_used: float = 0.0


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    tradeable: bool = True

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class InstrumentSpec:
    instrument: str
    pip_size: float
    price_precision: int
    min_units: float = 1.0
    units_step: float = 1.0


@dataclass(frozen=True)
class OpenTrade:
    id: str
    instrument: str
    units: float  # positif = achat, négatif = vente
    entry_price: float
    stop_loss: float | None
    take_profit: float | None
    unrealized_pnl: float = 0.0
    open_time: datetime | None = None

    @property
    def direction(self) -> str:
        return LONG if self.units > 0 else SHORT


@dataclass(frozen=True)
class Fill:
    trade_id: str
    instrument: str
    units: float
    price: float
    time: datetime


@dataclass(frozen=True)
class ClosedTrade:
    trade_id: str
    exit_price: float
    exit_time: datetime
    pnl: float  # en devise du compte, swaps et commissions inclus
    reason: str  # TP, SL ou MANUEL
