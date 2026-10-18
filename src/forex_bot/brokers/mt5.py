"""Courtier MetaTrader 5 (Windows uniquement, le terminal MT5 doit être installé et connecté)."""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime

import pandas as pd

from forex_bot.brokers.base import CANDLE_COLUMNS, Broker, BrokerAuthError, BrokerError
from forex_bot.models import Account, ClosedTrade, Fill, InstrumentSpec, OpenTrade, Quote

TIMEFRAMES = {
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D": "TIMEFRAME_D1",
}


class MT5Broker(Broker):
    name = "mt5"

    def __init__(
        self,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
        path: str | None = None,
        symbol_suffix: str = "",
        magic: int = 240611,
        deviation: int = 20,
        utc_offset_hours: int | None = None,
        module=None,
    ) -> None:
        if module is None:
            try:
                import MetaTrader5 as module
            except ImportError as exc:
                raise BrokerError(
                    "Le package MetaTrader5 n'est pas installé : uv sync --extra mt5 (Windows)"
                ) from exc
        self.mt5 = module
        self.suffix = symbol_suffix
        self.magic = magic
        self.deviation = deviation
        self._utc_offset = utc_offset_hours

        kwargs: dict = {}
        if path:
            kwargs["path"] = path
        if login:
            kwargs.update(login=int(login), password=password or "", server=server or "")
        if not self.mt5.initialize(**kwargs):
            code, message = self.mt5.last_error()
            error = BrokerAuthError if login else BrokerError
            raise error(f"Connexion MT5 impossible ({code}) : {message}")

    # --- Symboles ---
    def _symbol(self, instrument: str) -> str:
        return instrument.replace("_", "") + self.suffix

    def _instrument(self, symbol: str) -> str:
        core = symbol[: len(symbol) - len(self.suffix)] if self.suffix else symbol
        return f"{core[:3]}_{core[3:6]}"

    # --- Heure du serveur ---
    def utc_offset(self) -> int:
        """Décalage en heures entre l'heure du serveur MT5 et UTC (souvent +2 ou +3).

        MT5 date les bougies, positions et transactions à l'heure du serveur. Le décalage est
        déduit du dernier tick d'EUR/USD ; s'il est trop ancien (week-end), on ne devine pas.
        """
        if self._utc_offset is None:
            tick = self.mt5.symbol_info_tick(self._symbol("EUR_USD"))
            diff = (getattr(tick, "time", 0) - time.time()) / 3600 if tick else 0.0
            hours = round(diff)
            if abs(diff - hours) > 0.25 or not -12 <= hours <= 14:
                return 0
            self._utc_offset = hours
        return self._utc_offset

    def _to_utc(self, server_epoch: float) -> datetime:
        return datetime.fromtimestamp(server_epoch - self.utc_offset() * 3600, UTC)

    def _info(self, instrument: str):
        symbol = self._symbol(instrument)
        self.mt5.symbol_select(symbol, True)
        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise BrokerError(f"Symbole inconnu dans MT5 : {symbol}")
        return info

    # --- Compte et instruments ---
    def account(self) -> Account:
        a = self.mt5.account_info()
        if a is None:
            raise BrokerError(f"Compte MT5 indisponible : {self.mt5.last_error()}")
        return Account(
            balance=float(a.balance),
            nav=float(a.equity),
            currency=a.currency,
            unrealized_pnl=float(a.profit),
            margin_used=float(a.margin),
        )

    def instrument_spec(self, instrument: str) -> InstrumentSpec:
        info = self._info(instrument)
        # un pip = 10 points sur les cotations à 3 ou 5 décimales
        pip = info.point * 10 if info.digits in (3, 5) else info.point
        size = info.trade_contract_size
        return InstrumentSpec(
            instrument=instrument,
            pip_size=pip,
            price_precision=int(info.digits),
            min_units=info.volume_min * size,
            units_step=info.volume_step * size,
        )

    def candles(self, instrument: str, granularity: str, count: int) -> pd.DataFrame:
        timeframe = getattr(self.mt5, TIMEFRAMES[granularity])
        # position de départ 1 : on saute la bougie en cours de formation
        rates = self.mt5.copy_rates_from_pos(self._symbol(instrument), timeframe, 1, count)
        if rates is None or len(rates) == 0:
            return pd.DataFrame(columns=CANDLE_COLUMNS)
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"] - self.utc_offset() * 3600, unit="s", utc=True)
        df["volume"] = df["tick_volume"].astype(float)
        return df[CANDLE_COLUMNS]

    def quote(self, instrument: str) -> Quote:
        info = self._info(instrument)
        # juste après l'ajout d'un symbole à l'observation du marché, MT5 renvoie 0
        # le temps de recevoir le premier prix
        for _ in range(10):
            tick = self.mt5.symbol_info_tick(self._symbol(instrument))
            if tick is not None and tick.bid > 0 and tick.ask > 0:
                break
            time.sleep(0.3)
        else:
            raise BrokerError(f"Pas de prix pour {instrument}")
        tradeable = info.trade_mode == self.mt5.SYMBOL_TRADE_MODE_FULL
        return Quote(bid=float(tick.bid), ask=float(tick.ask), tradeable=tradeable)

    def value_per_unit(self, instrument: str) -> float:
        info = self._info(instrument)
        tick_value = getattr(info, "trade_tick_value_loss", 0) or info.trade_tick_value
        return float(tick_value) / info.trade_tick_size / info.trade_contract_size

    # --- Positions ---
    def _positions(self, **kwargs) -> list:
        positions = self.mt5.positions_get(**kwargs) or []
        return [p for p in positions if p.magic == self.magic]

    def open_trades(self) -> list[OpenTrade]:
        trades = []
        for p in self._positions():
            instrument = self._instrument(p.symbol)
            size = self._info(instrument).trade_contract_size
            sign = 1 if p.type == self.mt5.POSITION_TYPE_BUY else -1
            trades.append(
                OpenTrade(
                    id=str(p.ticket),
                    instrument=instrument,
                    units=sign * p.volume * size,
                    entry_price=float(p.price_open),
                    stop_loss=float(p.sl) or None,
                    take_profit=float(p.tp) or None,
                    unrealized_pnl=float(p.profit),
                    open_time=self._to_utc(p.time),
                )
            )
        return trades

    def _filling(self, info) -> int:
        if info.filling_mode & 1:
            return self.mt5.ORDER_FILLING_FOK
        if info.filling_mode & 2:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    def _send(self, request: dict):
        result = self.mt5.order_send(request)
        if result is None or result.retcode != self.mt5.TRADE_RETCODE_DONE:
            detail = self.mt5.last_error() if result is None else (result.retcode, result.comment)
            raise BrokerError(f"Ordre MT5 refusé : {detail}")
        return result

    def market_order(
        self, instrument: str, units: float, stop_loss: float, take_profit: float
    ) -> Fill:
        info = self._info(instrument)
        tick = self.mt5.symbol_info_tick(self._symbol(instrument))
        lots = math.floor(abs(units) / info.trade_contract_size / info.volume_step)
        lots = round(lots * info.volume_step, 8)
        if lots < info.volume_min:
            raise BrokerError(f"Volume trop petit pour {instrument} : {lots} lot")
        buy = units > 0
        result = self._send(
            {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": self._symbol(instrument),
                "volume": lots,
                "type": self.mt5.ORDER_TYPE_BUY if buy else self.mt5.ORDER_TYPE_SELL,
                "price": tick.ask if buy else tick.bid,
                # SL et TP envoyés avec l'ordre : MT5 les exécute au marché côté serveur
                "sl": round(stop_loss, info.digits),
                "tp": round(take_profit, info.digits),
                "deviation": self.deviation,
                "magic": self.magic,
                "comment": "forex-bot",
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": self._filling(info),
            }
        )
        sign = 1 if buy else -1
        return Fill(
            trade_id=str(result.order),  # le ticket de position = ticket de l'ordre d'ouverture
            instrument=instrument,
            units=sign * result.volume * info.trade_contract_size,
            price=float(result.price),
            time=datetime.now(UTC),
        )

    def closed_trade(self, trade_id: str) -> ClosedTrade | None:
        ticket = int(trade_id)
        if self.mt5.positions_get(ticket=ticket):
            return None
        deals = self.mt5.history_deals_get(position=ticket) or []
        exits = [
            d for d in deals if d.entry in (self.mt5.DEAL_ENTRY_OUT, self.mt5.DEAL_ENTRY_OUT_BY)
        ]
        if not exits:
            return None
        last = exits[-1]
        if last.reason == self.mt5.DEAL_REASON_SL:
            reason = "SL"
        elif last.reason == self.mt5.DEAL_REASON_TP:
            reason = "TP"
        else:
            reason = "MANUEL"
        pnl = sum(d.profit + d.swap + d.commission + getattr(d, "fee", 0.0) for d in deals)
        return ClosedTrade(
            trade_id=trade_id,
            exit_price=float(last.price),
            exit_time=self._to_utc(last.time),
            pnl=float(pnl),
            reason=reason,
        )

    def close_trade(self, trade_id: str) -> None:
        positions = self.mt5.positions_get(ticket=int(trade_id))
        if not positions:
            return
        p = positions[0]
        info = self._info(self._instrument(p.symbol))
        tick = self.mt5.symbol_info_tick(p.symbol)
        is_buy = p.type == self.mt5.POSITION_TYPE_BUY
        self._send(
            {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": p.symbol,
                "volume": p.volume,
                "type": self.mt5.ORDER_TYPE_SELL if is_buy else self.mt5.ORDER_TYPE_BUY,
                "position": p.ticket,
                "price": tick.bid if is_buy else tick.ask,
                "deviation": self.deviation,
                "magic": self.magic,
                "comment": "forex-bot close",
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": self._filling(info),
            }
        )
