"""Taille de position et règles de risque propres au forex."""

from __future__ import annotations

import math
from datetime import datetime


def position_units(
    *,
    balance: float,
    risk_fraction: float,
    entry: float,
    stop: float,
    value_per_unit: float,
    max_leverage: float,
    min_units: float = 1.0,
    units_step: float = 1.0,
) -> float:
    """Nombre d'unités (toujours positif) pour perdre `risk_fraction` du solde si le SL est touché.

    `value_per_unit` convertit un mouvement de prix de 1,0 sur 1 unité en devise du compte
    (1 pour EUR/USD sur un compte en USD, 1/prix pour USD/JPY, etc.). La taille est plafonnée
    par l'effet de levier maximal autorisé, puis arrondie au pas du courtier.
    """
    distance = abs(entry - stop)
    if balance <= 0 or distance <= 0 or value_per_unit <= 0 or entry <= 0:
        return 0.0
    units = balance * risk_fraction / (distance * value_per_unit)
    max_units = balance * max_leverage / (entry * value_per_unit)
    units = min(units, max_units)
    units = math.floor(units / units_step + 1e-9) * units_step
    return units if units >= min_units else 0.0


def market_open(now: datetime) -> bool:
    """Le forex est fermé du vendredi ~21h UTC au dimanche ~22h UTC (marge prudente été/hiver)."""
    weekday, hour = now.weekday(), now.hour
    if weekday == 5:
        return False
    if weekday == 4 and hour >= 21:
        return False
    if weekday == 6 and hour < 22:
        return False
    return True


def entry_window(
    now: datetime, friday_cutoff_utc: int, trading_hours_utc: str | None
) -> tuple[bool, str]:
    """Peut-on ouvrir une NOUVELLE position maintenant ? Renvoie (oui/non, raison)."""
    if not market_open(now):
        return False, "Marché fermé"
    if now.weekday() == 4 and now.hour >= friday_cutoff_utc:
        return False, "Vendredi soir : pas de nouvelle position avant le gap du week-end"
    if trading_hours_utc:
        start, end = (int(h) for h in trading_hours_utc.split("-"))
        if not start <= now.hour < end:
            return False, f"Hors des heures de trading ({trading_hours_utc} UTC)"
    return True, ""


def daily_loss_reached(realized_today: float, balance: float, limit_fraction: float) -> bool:
    """Coupe-circuit : plus de nouvelle position après une perte journalière de `limit_fraction`."""
    start_of_day_balance = balance - realized_today
    return realized_today <= -limit_fraction * start_of_day_balance
