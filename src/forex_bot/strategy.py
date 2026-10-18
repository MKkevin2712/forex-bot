"""Stratégie de suivi de tendance, identique pour le bot en direct et pour le backtest.

Achat  : EMA rapide > EMA moyenne > EMA lente, RSI sous le seuil de surchauffe, volume au-dessus
         de sa moyenne.
Vente  : configuration symétrique (EMA alignées à la baisse, RSI au-dessus du seuil de survente).
Sortie : stop-loss à `atr_stop_mult` ATR, take-profit à `reward_risk` fois le risque.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from forex_bot.config import StrategyParams
from forex_bot.indicators import atr, ema, rsi
from forex_bot.models import LONG, SHORT

INDICATOR_COLUMNS = ["ema_fast", "ema_mid", "ema_slow", "rsi", "atr", "volume_sma"]


@dataclass(frozen=True)
class Decision:
    direction: str | None  # LONG, SHORT ou None
    reason: str


def compute_indicators(candles: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    df = candles.copy()
    df["ema_fast"] = ema(df["close"], params.ema_fast)
    df["ema_mid"] = ema(df["close"], params.ema_mid)
    df["ema_slow"] = ema(df["close"], params.ema_slow)
    df["rsi"] = rsi(df["close"], params.rsi_period)
    df["atr"] = atr(df, params.atr_period)
    df["volume_sma"] = df["volume"].rolling(params.volume_period).mean()
    return df


def evaluate(row: pd.Series, params: StrategyParams) -> Decision:
    """Décision sur une bougie clôturée dont les indicateurs sont déjà calculés."""
    if any(pd.isna(row[c]) for c in INDICATOR_COLUMNS) or row["atr"] <= 0:
        return Decision(None, "Historique insuffisant pour calculer les indicateurs")

    fast, mid, slow, rsi_value = row["ema_fast"], row["ema_mid"], row["ema_slow"], row["rsi"]
    volume_ok = not params.use_volume_filter or row["volume"] > row["volume_sma"]

    if fast > mid > slow:
        if rsi_value >= params.rsi_long_max:
            return Decision(None, f"Tendance haussière mais RSI trop élevé ({rsi_value:.1f})")
        if not volume_ok:
            return Decision(None, "Tendance haussière mais volume sous la moyenne")
        return Decision(LONG, f"Tendance haussière confirmée (RSI {rsi_value:.1f})")

    if fast < mid < slow:
        if rsi_value <= params.rsi_short_min:
            return Decision(None, f"Tendance baissière mais RSI trop bas ({rsi_value:.1f})")
        if not volume_ok:
            return Decision(None, "Tendance baissière mais volume sous la moyenne")
        return Decision(SHORT, f"Tendance baissière confirmée (RSI {rsi_value:.1f})")

    return Decision(None, "Moyennes mobiles non alignées : pas de tendance claire")


def stop_and_target(
    direction: str, entry: float, atr_value: float, params: StrategyParams
) -> tuple[float, float]:
    distance = atr_value * params.atr_stop_mult
    if not math.isfinite(distance) or distance <= 0:
        raise ValueError("ATR invalide pour calculer le stop-loss")
    if direction == LONG:
        return entry - distance, entry + distance * params.reward_risk
    return entry + distance, entry - distance * params.reward_risk


def snapshot(row: pd.Series) -> dict:
    """Valeurs des indicateurs, arrondies, pour le journal et le tableau de bord."""
    return {c: (None if pd.isna(row[c]) else round(float(row[c]), 6)) for c in INDICATOR_COLUMNS}
