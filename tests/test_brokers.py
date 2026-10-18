"""Traduction des réponses OANDA et MT5, avec des réponses enregistrées (aucun appel réseau)."""

from types import SimpleNamespace

import pytest

from forex_bot.brokers.base import BrokerAuthError, BrokerError
from forex_bot.brokers.mt5 import MT5Broker
from forex_bot.brokers.oanda import OandaBroker

INSTRUMENT = {
    "instruments": [
        {
            "name": "EUR_USD",
            "pipLocation": -4,
            "displayPrecision": 5,
            "tradeUnitsPrecision": 0,
            "minimumTradeSize": "1",
        }
    ]
}


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code, self._payload, self.text = status, payload, str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls, self.headers = routes, [], {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for (m, fragment), (status, payload) in self.routes.items():
            if m == method and url.endswith(fragment):
                return FakeResponse(status, payload)
        raise AssertionError(f"route inattendue {method} {url}")


def oanda(routes):
    session = FakeSession(routes)
    return OandaBroker("token", "001", session=session), session


def test_oanda_candles_keep_only_complete():
    broker, _ = oanda(
        {
            ("GET", "/instruments/EUR_USD/candles"): (
                200,
                {
                    "candles": [
                        {
                            "complete": True,
                            "volume": 10,
                            "time": "2026-10-19T00:00:00.000000000Z",
                            "mid": {"o": "1.1", "h": "1.2", "l": "1.0", "c": "1.15"},
                        },
                        {
                            "complete": False,
                            "volume": 3,
                            "time": "2026-10-19T04:00:00.000000000Z",
                            "mid": {"o": "1.15", "h": "1.2", "l": "1.1", "c": "1.16"},
                        },
                    ]
                },
            )
        }
    )
    df = broker.candles("EUR_USD", "H4", 2)
    assert len(df) == 1 and df["close"].iloc[0] == 1.15
    assert str(df["time"].dt.tz) == "UTC"


def test_oanda_order_sends_stop_and_target_together():
    broker, session = oanda(
        {
            ("GET", "/accounts/001/instruments"): (200, INSTRUMENT),
            ("POST", "/accounts/001/orders"): (
                201,
                {
                    "orderFillTransaction": {
                        "price": "1.10012",
                        "time": "2026-10-19T08:00:01Z",
                        "tradeOpened": {"tradeID": "42", "units": "-20000", "price": "1.10012"},
                    }
                },
            ),
        }
    )
    fill = broker.market_order("EUR_USD", -20000.4, 1.103001, 1.0955)
    order = session.calls[-1][2]["json"]["order"]
    assert order["units"] == "-20000"
    assert order["stopLossOnFill"]["price"] == "1.10300"
    assert order["takeProfitOnFill"]["price"] == "1.09550"
    assert fill.trade_id == "42" and fill.units == -20000


def test_oanda_rejected_order_raises():
    broker, _ = oanda(
        {
            ("GET", "/accounts/001/instruments"): (200, INSTRUMENT),
            ("POST", "/accounts/001/orders"): (
                201,
                {"orderCancelTransaction": {"reason": "STOP_LOSS_ON_FILL_LOSS"}},
            ),
        }
    )
    with pytest.raises(BrokerError, match="STOP_LOSS_ON_FILL_LOSS"):
        broker.market_order("EUR_USD", 1000, 1.0, 1.2)


def test_oanda_closed_trade_reason_and_pnl():
    broker, _ = oanda(
        {
            ("GET", "/accounts/001/trades/42"): (
                200,
                {
                    "trade": {
                        "state": "CLOSED",
                        "averageClosePrice": "1.0955",
                        "closeTime": "2026-10-20T08:00:00Z",
                        "realizedPL": "90.0",
                        "financing": "-1.5",
                        "takeProfitOrder": {"state": "FILLED"},
                        "stopLossOrder": {"state": "CANCELLED"},
                    }
                },
            )
        }
    )
    closed = broker.closed_trade("42")
    assert closed.reason == "TP" and closed.pnl == 88.5


def test_oanda_auth_error():
    broker, _ = oanda({("GET", "/accounts/001/summary"): (401, {"errorMessage": "bad token"})})
    with pytest.raises(BrokerAuthError):
        broker.account()


def test_oanda_value_per_unit_from_home_conversions():
    broker, _ = oanda(
        {
            ("GET", "/accounts/001/summary"): (
                200,
                {"account": {"balance": "10000", "NAV": "10000", "currency": "USD"}},
            ),
            ("GET", "/accounts/001/pricing"): (
                200,
                {
                    "prices": [{}],
                    "homeConversions": [
                        {"currency": "JPY", "accountGain": "0.00666", "accountLoss": "0.00667"}
                    ],
                },
            ),
        }
    )
    assert broker.value_per_unit("USD_JPY") == pytest.approx(0.00667)
    assert broker.value_per_unit("EUR_USD") == 1.0


class FakeMT5:
    """Le strict nécessaire du module MetaTrader5."""

    TIMEFRAME_H4 = 16388
    SYMBOL_TRADE_MODE_FULL = 4
    POSITION_TYPE_BUY, ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 0, 1
    TRADE_ACTION_DEAL, ORDER_TIME_GTC, TRADE_RETCODE_DONE = 1, 0, 10009
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY, DEAL_REASON_SL, DEAL_REASON_TP = 1, 3, 4, 5

    def __init__(self):
        self.sent = []

    def initialize(self, **kwargs):
        return True

    def symbol_select(self, symbol, enable):
        return True

    def symbol_info(self, symbol):
        return SimpleNamespace(
            point=0.00001,
            digits=5,
            trade_contract_size=100_000,
            volume_min=0.01,
            volume_step=0.01,
            trade_tick_value=1.0,
            trade_tick_value_loss=1.0,
            trade_tick_size=0.00001,
            trade_mode=4,
            filling_mode=2,
        )

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(bid=1.1, ask=1.1001)

    def order_send(self, request):
        self.sent.append(request)
        return SimpleNamespace(
            retcode=10009, order=777, price=1.1001, volume=request["volume"], comment="done"
        )

    def positions_get(self, **kwargs):
        return []

    def history_deals_get(self, position):
        return [
            SimpleNamespace(
                entry=0,
                profit=0.0,
                swap=0.0,
                commission=-3.0,
                fee=0.0,
                price=1.1001,
                time=1_760_000_000,
                reason=3,
            ),
            SimpleNamespace(
                entry=1,
                profit=-100.0,
                swap=-0.5,
                commission=-3.0,
                fee=0.0,
                price=1.0951,
                time=1_760_100_000,
                reason=4,
            ),
        ]


def test_mt5_spec_value_and_order():
    module = FakeMT5()
    broker = MT5Broker(module=module, symbol_suffix=".m")
    spec = broker.instrument_spec("EUR_USD")
    assert spec.pip_size == pytest.approx(0.0001) and spec.min_units == 1000
    assert broker.value_per_unit("EUR_USD") == pytest.approx(1.0)
    fill = broker.market_order("EUR_USD", 20_000, 1.0951, 1.1076)
    request = module.sent[-1]
    assert request["symbol"] == "EURUSD.m" and request["volume"] == 0.2
    assert request["sl"] == 1.0951 and request["tp"] == 1.1076
    assert request["type_filling"] == module.ORDER_FILLING_IOC
    assert fill.trade_id == "777" and fill.units == pytest.approx(20_000)


def test_mt5_closed_trade_sums_costs():
    broker = MT5Broker(module=FakeMT5())
    closed = broker.closed_trade("777")
    assert closed.reason == "SL" and closed.pnl == pytest.approx(-106.5)
