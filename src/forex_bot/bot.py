"""Boucle de trading en direct.

À chaque bougie clôturée de chaque paire : synchronisation des positions fermées par le courtier,
calcul des indicateurs, décision, contrôles de risque, puis ordre au marché avec SL/TP attachés.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from forex_bot.brokers.base import Broker, BrokerAuthError, BrokerError
from forex_bot.config import Settings
from forex_bot.journal import Journal
from forex_bot.models import LONG, OpenTrade, to_iso, utcnow
from forex_bot.risk import daily_loss_reached, entry_window, market_open, position_units
from forex_bot.state import StateStore
from forex_bot.strategy import compute_indicators, evaluate, snapshot, stop_and_target

log = logging.getLogger("forex_bot")

EQUITY_EVERY = timedelta(minutes=30)
MAX_CONSECUTIVE_FAILURES = 5


class TradingBot:
    def __init__(
        self,
        broker: Broker,
        journal: Journal,
        settings: Settings,
        state: StateStore | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.broker = broker
        self.journal = journal
        self.settings = settings
        self.state = state or StateStore(None)
        self.clock = clock
        self._last_equity: datetime | None = None
        self.state.data.setdefault("last_processed", {})

    # --- Boucle principale ---
    def run_forever(self) -> None:
        s = self.settings
        mode = "SIMULATION (aucun ordre envoyé)" if s.dry_run else "ordres réels sur le compte"
        log.info(
            "Bot lancé : %s, %s, %s, %s",
            self.broker.name,
            ",".join(s.instruments),
            s.granularity,
            mode,
        )
        failures = 0
        while True:
            try:
                self.run_cycle()
                failures = 0
            except BrokerAuthError:
                log.critical("Identifiants refusés par le courtier : arrêt du bot")
                self._set_status("arrêté : identifiants refusés")
                raise
            except Exception as exc:  # coupure réseau, courtier indisponible...
                log.exception("Erreur pendant le cycle, nouvel essai au prochain tour")
                self.state.data["last_error"] = {"time": to_iso(self.clock()), "message": str(exc)}
                self.state.save()
                failures += 1
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    # ex. terminal MT5 fermé : on s'arrête pour que le superviseur relance
                    # le bot avec une connexion neuve
                    log.critical("%d erreurs de suite : arrêt du bot", failures)
                    raise
            time.sleep(s.poll_seconds if market_open(self.clock()) else 300)

    def run_cycle(self) -> None:
        now = self.clock()
        self.state.data["heartbeat"] = to_iso(now)
        if not market_open(now):
            self._set_status("marché fermé (week-end)")
            return

        self.reconcile()
        account = self.broker.account()
        if self._last_equity is None or now - self._last_equity >= EQUITY_EVERY:
            self.journal.record_equity(now, account.balance, account.nav)
            self._last_equity = now

        open_trades = self.broker.open_trades()
        for instrument in self.settings.instruments:
            try:
                self.process_instrument(instrument, now, open_trades, account.balance)
            except BrokerAuthError:
                raise
            except BrokerError as exc:
                log.error("%s : %s", instrument, exc)
                self._analysis(instrument, {"error": str(exc), "time": to_iso(now)}, merge=True)
        self._set_status("en marche")

    # --- Synchronisation avec le courtier ---
    def reconcile(self) -> list[str]:
        """Enregistre la sortie (prix, P&L réel, TP/SL) des positions fermées par le courtier."""
        still_open = {t.id for t in self.broker.open_trades()}
        closed_ids = []
        for trade in self.journal.open_trades(self.broker.name):
            trade_id = trade["broker_trade_id"]
            if trade_id in still_open:
                continue
            closed = self.broker.closed_trade(trade_id)
            if closed is None:
                continue
            self.journal.record_close(self.broker.name, closed)
            closed_ids.append(trade_id)
            log.info(
                "Position %s %s fermée (%s) : P&L %.2f",
                trade["instrument"],
                trade_id,
                closed.reason,
                closed.pnl,
            )
        return closed_ids

    # --- Une paire ---
    def process_instrument(
        self, instrument: str, now: datetime, open_trades: list[OpenTrade], balance: float
    ) -> None:
        s, p = self.settings, self.settings.strategy
        candles = self.broker.candles(instrument, s.granularity, s.candle_count)
        if candles.empty:
            return
        candle_time = to_iso(candles["time"].iloc[-1].to_pydatetime())
        if self.state.data["last_processed"].get(instrument) == candle_time:
            return  # bougie déjà analysée : on attend la suivante
        self.state.data["last_processed"][instrument] = candle_time

        row = compute_indicators(candles, p).iloc[-1]
        decision = evaluate(row, p)
        analysis = {
            "time": to_iso(now),
            "candle_time": candle_time,
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            **snapshot(row),
            "signal": decision.direction,
            "reason": decision.reason,
            "action": "aucune",
        }

        def skip(reason: str) -> None:
            analysis["action"] = reason
            self._analysis(instrument, analysis)
            log.info("%s : %s -> %s", instrument, decision.reason, reason)

        if decision.direction is None:
            return skip("aucune")

        # Contrôles de risque avant toute entrée
        if any(t.instrument == instrument for t in open_trades):
            return skip("ignoré : une position est déjà ouverte sur cette paire")
        if len(open_trades) >= s.max_open_trades:
            return skip(
                f"ignoré : déjà {len(open_trades)} positions ouvertes (max {s.max_open_trades})"
            )
        allowed, why = entry_window(now, s.friday_cutoff_utc, s.trading_hours_utc)
        if not allowed:
            return skip(f"ignoré : {why}")
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        realized_today = self.journal.realized_pnl_since(start_of_day)
        if daily_loss_reached(realized_today, balance, s.daily_loss_limit):
            return skip("ignoré : limite de perte journalière atteinte")

        quote = self.broker.quote(instrument)
        if not quote.tradeable:
            return skip("ignoré : paire non négociable en ce moment")
        atr_value = float(row["atr"])
        if quote.spread > s.max_spread_atr * atr_value:
            return skip(f"ignoré : spread trop large ({quote.spread:.5f})")

        is_long = decision.direction == LONG
        entry = quote.ask if is_long else quote.bid
        stop, target = stop_and_target(decision.direction, entry, atr_value, p)
        spec = self.broker.instrument_spec(instrument)
        digits = spec.price_precision
        stop, target = round(stop, digits), round(target, digits)
        side = "Achat" if is_long else "Vente"
        value_per_unit = self.broker.value_per_unit(instrument)
        units = position_units(
            balance=balance,
            risk_fraction=s.risk_per_trade,
            entry=entry,
            stop=stop,
            value_per_unit=value_per_unit,
            max_leverage=s.max_leverage,
            min_units=spec.min_units,
            units_step=spec.units_step,
        )
        if units <= 0:
            return skip("ignoré : taille de position inférieure au minimum du courtier")
        analysis.update(entry=entry, stop_loss=stop, take_profit=target, units=units)

        if s.dry_run:
            return skip(
                f"simulation : {side.lower()} de {units:g} unités à {entry:.{digits}f} "
                "(aucun ordre envoyé)"
            )

        fill = self.broker.market_order(instrument, units if is_long else -units, stop, target)

        # Garde-fou : une position sans stop-loss est refermée immédiatement
        opened = next((t for t in self.broker.open_trades() if t.id == fill.trade_id), None)
        if opened is not None and opened.stop_loss is None:
            self.broker.close_trade(fill.trade_id)
            log.error("%s : position %s sans stop-loss, refermée", instrument, fill.trade_id)
            return skip("annulé : le stop-loss n'a pas été posé, position refermée")

        self.journal.record_open(
            {
                "broker": self.broker.name,
                "broker_trade_id": fill.trade_id,
                "instrument": instrument,
                "direction": decision.direction,
                "units": abs(fill.units),
                "entry_time": to_iso(fill.time),
                "entry_price": fill.price,
                "stop_loss": stop,
                "take_profit": target,
                "risk_amount": round(abs(fill.price - stop) * abs(fill.units) * value_per_unit, 2),
                "signal_reason": decision.reason,
                "indicators": snapshot(row),
            }
        )
        open_trades.append(
            OpenTrade(fill.trade_id, instrument, fill.units, fill.price, stop, target)
        )
        analysis["action"] = f"{side} ouvert : {abs(fill.units):g} unités à {fill.price:.{digits}f}"
        self._analysis(instrument, analysis)
        log.info("%s : %s", instrument, analysis["action"])

    # --- État partagé ---
    def _analysis(self, instrument: str, data: dict, merge: bool = False) -> None:
        analyses = self.state.data.setdefault("analyses", {})
        analyses[instrument] = {**analyses.get(instrument, {}), **data} if merge else data
        self.state.save()

    def _set_status(self, status: str) -> None:
        self.state.data["status"] = status
        self.state.save()
