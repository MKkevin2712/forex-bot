"""Backtest de la stratégie sur bougies historiques, avec les mêmes règles que le bot en direct.

Hypothèses (volontairement prudentes) :
- le signal est calculé à la clôture d'une bougie, l'entrée se fait à l'ouverture de la suivante ;
- achat au prix ask, vente au prix bid (spread fixe en pips par paire) ;
- si le SL et le TP sont touchés dans la même bougie, on considère que le SL l'a été en premier ;
- un gap au-delà du SL est exécuté au prix d'ouverture (glissement défavorable).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from forex_bot.config import Settings
from forex_bot.metrics import trade_stats
from forex_bot.models import LONG, SHORT, split_instrument, to_iso
from forex_bot.risk import daily_loss_reached, entry_window, position_units
from forex_bot.strategy import compute_indicators, evaluate, stop_and_target

DEFAULT_SPREAD_PIPS = {"EUR_USD": 1.0, "GBP_USD": 1.4, "USD_JPY": 1.2, "AUD_USD": 1.3}


def pip_size(instrument: str) -> float:
    return 0.01 if split_instrument(instrument)[1] == "JPY" else 0.0001


def value_per_unit(instrument: str, price: float, account_currency: str = "USD") -> float:
    base, quote = split_instrument(instrument)
    if quote == account_currency:
        return 1.0
    if base == account_currency:
        return 1.0 / price
    raise ValueError(
        f"Backtest : {instrument} ne contient pas la devise du compte ({account_currency})"
    )


@dataclass
class _Position:
    instrument: str
    direction: str
    units: float
    entry_time: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: float
    signal_reason: str


@dataclass
class BacktestResult:
    initial_balance: float
    final_balance: float
    trades: list[dict] = field(default_factory=list)
    equity: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    per_instrument: dict = field(default_factory=dict)
    period: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "initial_balance": self.initial_balance,
            "final_balance": round(self.final_balance, 2),
            "total_return_pct": round((self.final_balance / self.initial_balance - 1) * 100, 2),
            "stats": self.stats,
            "per_instrument": self.per_instrument,
            "period": self.period,
            "trades": self.trades,
            "equity": self.equity,
        }


def run_backtest(
    data: dict[str, pd.DataFrame],
    settings: Settings,
    initial_balance: float = 10_000.0,
    spread_pips: dict[str, float] | None = None,
    account_currency: str = "USD",
) -> BacktestResult:
    s, p = settings, settings.strategy
    spreads = {**DEFAULT_SPREAD_PIPS, **(spread_pips or {})}
    frames = {inst: compute_indicators(df, p).reset_index(drop=True) for inst, df in data.items()}
    rows_by_time: dict[pd.Timestamp, list[tuple[str, int]]] = {}
    for inst, df in frames.items():
        for i, t in enumerate(df["time"]):
            rows_by_time.setdefault(t, []).append((inst, i))

    balance = initial_balance
    positions: dict[str, _Position] = {}
    pending: dict[str, tuple[str, float, str]] = {}  # paire -> (sens, ATR, raison)
    trades: list[dict] = []
    equity = []
    realized_by_day: dict = {}

    def half_spread(inst: str) -> float:
        return spreads.get(inst, 1.5) * pip_size(inst) / 2

    def close(pos: _Position, time: pd.Timestamp, price: float, reason: str) -> None:
        nonlocal balance
        sign = 1 if pos.direction == LONG else -1
        pnl = (
            (price - pos.entry_price)
            * sign
            * pos.units
            * value_per_unit(pos.instrument, price, account_currency)
        )
        balance += pnl
        realized_by_day[time.date()] = realized_by_day.get(time.date(), 0.0) + pnl
        trades.append(
            {
                "instrument": pos.instrument,
                "direction": pos.direction,
                "units": pos.units,
                "entry_time": to_iso(pos.entry_time.to_pydatetime()),
                "entry_price": round(pos.entry_price, 6),
                "stop_loss": round(pos.stop_loss, 6),
                "take_profit": round(pos.take_profit, 6),
                "exit_time": to_iso(time.to_pydatetime()),
                "exit_price": round(price, 6),
                "close_reason": reason,
                "pnl": round(pnl, 2),
                "signal_reason": pos.signal_reason,
            }
        )
        equity.append({"time": to_iso(time.to_pydatetime()), "balance": round(balance, 2)})
        del positions[pos.instrument]

    for t in sorted(rows_by_time):
        for inst, i in rows_by_time[t]:
            bar = frames[inst].iloc[i]
            hs = half_spread(inst)

            # 1. Entrée en attente : à l'ouverture de cette bougie
            if inst in pending:
                direction, atr_value, reason = pending.pop(inst)
                entry = bar["open"] + hs if direction == LONG else bar["open"] - hs
                stop, target = stop_and_target(direction, entry, atr_value, p)
                vpu = value_per_unit(inst, entry, account_currency)
                units = position_units(
                    balance=balance,
                    risk_fraction=s.risk_per_trade,
                    entry=entry,
                    stop=stop,
                    value_per_unit=vpu,
                    max_leverage=s.max_leverage,
                )
                if units > 0:
                    positions[inst] = _Position(
                        inst, direction, units, t, entry, stop, target, reason
                    )

            # 2. Gestion de la position ouverte sur cette bougie
            pos = positions.get(inst)
            if pos is not None:
                if pos.direction == LONG:  # sortie au bid
                    o, lo, hi = bar["open"] - hs, bar["low"] - hs, bar["high"] - hs
                    if o <= pos.stop_loss:
                        close(pos, t, o, "SL")
                    elif lo <= pos.stop_loss:
                        close(pos, t, pos.stop_loss, "SL")
                    elif o >= pos.take_profit:
                        close(pos, t, o, "TP")
                    elif hi >= pos.take_profit:
                        close(pos, t, pos.take_profit, "TP")
                else:  # sortie à l'ask
                    o, lo, hi = bar["open"] + hs, bar["low"] + hs, bar["high"] + hs
                    if o >= pos.stop_loss:
                        close(pos, t, o, "SL")
                    elif hi >= pos.stop_loss:
                        close(pos, t, pos.stop_loss, "SL")
                    elif o <= pos.take_profit:
                        close(pos, t, o, "TP")
                    elif lo <= pos.take_profit:
                        close(pos, t, pos.take_profit, "TP")

            # 3. Signal à la clôture de cette bougie
            if inst in positions or inst in pending:
                continue
            decision = evaluate(bar, p)
            if decision.direction not in (LONG, SHORT):
                continue
            if len(positions) + len(pending) >= s.max_open_trades:
                continue
            close_time = (t + s.candle_delta).to_pydatetime()
            allowed, _ = entry_window(close_time, s.friday_cutoff_utc, s.trading_hours_utc)
            if not allowed:
                continue
            if daily_loss_reached(
                realized_by_day.get(close_time.date(), 0.0), balance, s.daily_loss_limit
            ):
                continue
            pending[inst] = (decision.direction, float(bar["atr"]), decision.reason)

    # Positions encore ouvertes à la fin des données : clôture au dernier cours
    for inst, pos in list(positions.items()):
        last = frames[inst].iloc[-1]
        hs = half_spread(inst)
        price = last["close"] - hs if pos.direction == LONG else last["close"] + hs
        close(pos, last["time"], price, "FIN")

    trades.sort(key=lambda tr: tr["exit_time"])
    pnls = [tr["pnl"] for tr in trades]
    per_instrument = {
        inst: trade_stats([tr["pnl"] for tr in trades if tr["instrument"] == inst])
        for inst in frames
    }
    all_times = [df["time"] for df in frames.values() if not df.empty]
    period = (
        {
            "start": to_iso(min(ts.iloc[0] for ts in all_times).to_pydatetime()),
            "end": to_iso(max(ts.iloc[-1] for ts in all_times).to_pydatetime()),
            "bars": int(sum(len(ts) for ts in all_times)),
            "granularity": s.granularity,
        }
        if all_times
        else {}
    )
    return BacktestResult(
        initial_balance=initial_balance,
        final_balance=balance,
        trades=trades,
        equity=equity,
        stats=trade_stats(pnls, initial_balance),
        per_instrument=per_instrument,
        period=period,
    )


def load_csv(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df[["time", "open", "high", "low", "close", "volume"]]
