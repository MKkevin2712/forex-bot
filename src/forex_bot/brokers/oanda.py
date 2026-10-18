"""Courtier OANDA via l'API REST v20 (compte « practice » = argent virtuel)."""

from __future__ import annotations

import math

import pandas as pd
import requests

from forex_bot.brokers.base import CANDLE_COLUMNS, Broker, BrokerAuthError, BrokerError
from forex_bot.models import (
    Account,
    ClosedTrade,
    Fill,
    InstrumentSpec,
    OpenTrade,
    Quote,
    split_instrument,
)

HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}


def _time(value: str) -> pd.Timestamp:
    return pd.Timestamp(value).tz_convert("UTC")


class OandaBroker(Broker):
    name = "oanda"

    def __init__(
        self,
        token: str,
        account_id: str,
        environment: str = "practice",
        session: requests.Session | None = None,
        timeout: float = 15,
    ) -> None:
        if not token or not account_id:
            raise BrokerAuthError("OANDA_TOKEN et OANDA_ACCOUNT_ID sont obligatoires")
        self.base_url = f"{HOSTS[environment]}/v3"
        self.account_id = account_id
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept-Datetime-Format": "RFC3339",
            }
        )
        self._specs: dict[str, InstrumentSpec] = {}
        self._currency: str | None = None

    # --- HTTP ---
    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self.session.request(
                method, self.base_url + path, timeout=self.timeout, **kwargs
            )
        except requests.RequestException as exc:
            raise BrokerError(f"OANDA injoignable : {exc}") from exc
        if response.status_code in (401, 403):
            raise BrokerAuthError("OANDA a refusé le jeton ou le numéro de compte")
        if response.status_code >= 400:
            raise BrokerError(f"OANDA {response.status_code} : {response.text[:300]}")
        return response.json()

    def _account_path(self, suffix: str = "") -> str:
        return f"/accounts/{self.account_id}{suffix}"

    # --- Compte et instruments ---
    def account(self) -> Account:
        a = self._request("GET", self._account_path("/summary"))["account"]
        self._currency = a["currency"]
        return Account(
            balance=float(a["balance"]),
            nav=float(a["NAV"]),
            currency=a["currency"],
            unrealized_pnl=float(a.get("unrealizedPL", 0)),
            margin_used=float(a.get("marginUsed", 0)),
        )

    def _account_currency(self) -> str:
        if self._currency is None:
            self.account()
        return self._currency  # type: ignore[return-value]

    def instrument_spec(self, instrument: str) -> InstrumentSpec:
        if instrument not in self._specs:
            data = self._request(
                "GET", self._account_path("/instruments"), params={"instruments": instrument}
            )
            if not data.get("instruments"):
                raise BrokerError(f"Instrument inconnu chez OANDA : {instrument}")
            i = data["instruments"][0]
            step = 10 ** -int(i.get("tradeUnitsPrecision", 0))
            self._specs[instrument] = InstrumentSpec(
                instrument=instrument,
                pip_size=10 ** int(i["pipLocation"]),
                price_precision=int(i["displayPrecision"]),
                min_units=float(i.get("minimumTradeSize", 1)),
                units_step=step,
            )
        return self._specs[instrument]

    def candles(self, instrument: str, granularity: str, count: int) -> pd.DataFrame:
        data = self._request(
            "GET",
            f"/instruments/{instrument}/candles",
            params={
                "granularity": granularity,
                "count": min(count, 5000),
                "price": "M",
                # bougies H4/D alignées sur minuit UTC (par défaut OANDA aligne sur New York)
                "dailyAlignment": 0,
                "alignmentTimezone": "UTC",
            },
        )
        rows = [
            {
                "time": _time(c["time"]),
                "open": float(c["mid"]["o"]),
                "high": float(c["mid"]["h"]),
                "low": float(c["mid"]["l"]),
                "close": float(c["mid"]["c"]),
                "volume": float(c.get("volume", 0)),
            }
            for c in data.get("candles", [])
            if c.get("complete")
        ]
        return pd.DataFrame(rows, columns=CANDLE_COLUMNS)

    def _pricing(self, instrument: str, home_conversions: bool = False) -> dict:
        params = {"instruments": instrument}
        if home_conversions:
            params["includeHomeConversions"] = "true"
        return self._request("GET", self._account_path("/pricing"), params=params)

    def quote(self, instrument: str) -> Quote:
        prices = self._pricing(instrument).get("prices", [])
        if not prices:
            raise BrokerError(f"Pas de prix pour {instrument}")
        p = prices[0]
        bid = float(p["bids"][0]["price"]) if p.get("bids") else float(p["closeoutBid"])
        ask = float(p["asks"][0]["price"]) if p.get("asks") else float(p["closeoutAsk"])
        return Quote(bid=bid, ask=ask, tradeable=bool(p.get("tradeable", True)))

    def value_per_unit(self, instrument: str) -> float:
        _, quote_ccy = split_instrument(instrument)
        if quote_ccy == self._account_currency():
            return 1.0
        data = self._pricing(instrument, home_conversions=True)
        for conversion in data.get("homeConversions", []):
            if conversion.get("currency") == quote_ccy:
                # facteur de conversion d'une perte : le plus prudent pour dimensionner le risque
                return float(conversion["accountLoss"])
        factors = (data.get("prices") or [{}])[0].get("quoteHomeConversionFactors")
        if factors:
            return float(factors["negativeUnits"])
        raise BrokerError(f"Conversion {quote_ccy} -> devise du compte introuvable")

    # --- Positions ---
    def open_trades(self) -> list[OpenTrade]:
        trades = self._request("GET", self._account_path("/openTrades")).get("trades", [])
        return [
            OpenTrade(
                id=str(t["id"]),
                instrument=t["instrument"],
                units=float(t["currentUnits"]),
                entry_price=float(t["price"]),
                stop_loss=float(t["stopLossOrder"]["price"]) if t.get("stopLossOrder") else None,
                take_profit=(
                    float(t["takeProfitOrder"]["price"]) if t.get("takeProfitOrder") else None
                ),
                unrealized_pnl=float(t.get("unrealizedPL", 0)),
                open_time=_time(t["openTime"]).to_pydatetime() if t.get("openTime") else None,
            )
            for t in trades
        ]

    def _format_units(self, instrument: str, units: float) -> str:
        step = self.instrument_spec(instrument).units_step
        decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
        return f"{units:.{decimals}f}"

    def _format_price(self, instrument: str, price: float) -> str:
        return f"{price:.{self.instrument_spec(instrument).price_precision}f}"

    def market_order(
        self, instrument: str, units: float, stop_loss: float, take_profit: float
    ) -> Fill:
        body = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": self._format_units(instrument, units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                # SL et TP sont créés par OANDA au moment du remplissage : la position
                # n'existe jamais sans protection. Le SL OANDA s'exécute au marché.
                "stopLossOnFill": {
                    "price": self._format_price(instrument, stop_loss),
                    "timeInForce": "GTC",
                },
                "takeProfitOnFill": {
                    "price": self._format_price(instrument, take_profit),
                    "timeInForce": "GTC",
                },
                "clientExtensions": {"tag": "forex-bot"},
            }
        }
        data = self._request("POST", self._account_path("/orders"), json=body)
        fill = data.get("orderFillTransaction")
        if not fill or not fill.get("tradeOpened"):
            cancel = data.get("orderCancelTransaction") or data.get("orderRejectTransaction") or {}
            raise BrokerError(f"Ordre non exécuté : {cancel.get('reason', 'raison inconnue')}")
        opened = fill["tradeOpened"]
        return Fill(
            trade_id=str(opened["tradeID"]),
            instrument=instrument,
            units=float(opened["units"]),
            price=float(opened.get("price", fill["price"])),
            time=_time(fill["time"]).to_pydatetime(),
        )

    def closed_trade(self, trade_id: str) -> ClosedTrade | None:
        t = self._request("GET", self._account_path(f"/trades/{trade_id}"))["trade"]
        if t.get("state") != "CLOSED":
            return None
        if (t.get("stopLossOrder") or {}).get("state") == "FILLED":
            reason = "SL"
        elif (t.get("takeProfitOrder") or {}).get("state") == "FILLED":
            reason = "TP"
        else:
            reason = "MANUEL"
        return ClosedTrade(
            trade_id=str(trade_id),
            exit_price=float(t["averageClosePrice"]),
            exit_time=_time(t["closeTime"]).to_pydatetime(),
            pnl=float(t.get("realizedPL", 0)) + float(t.get("financing", 0)),
            reason=reason,
        )

    def close_trade(self, trade_id: str) -> None:
        self._request("PUT", self._account_path(f"/trades/{trade_id}/close"), json={"units": "ALL"})
