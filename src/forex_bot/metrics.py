"""Statistiques de performance, communes au journal réel et au backtest."""

from __future__ import annotations

from collections.abc import Sequence


def trade_stats(pnls: Sequence[float], initial_balance: float | None = None) -> dict:
    """Win rate, profit factor, espérance et drawdown maximal des trades clôturés."""
    pnls = [float(p) for p in pnls]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)

    equity = initial_balance or 0.0
    peak = equity
    max_dd = 0.0
    max_dd_pct = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        drawdown = peak - equity
        if drawdown > max_dd:
            max_dd = drawdown
            max_dd_pct = drawdown / peak * 100 if peak > 0 else 0.0

    n = len(pnls)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 2) if n else 0.0,
        "total_pnl": round(sum(pnls), 2),
        "avg_win": round(gross_profit / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
        "expectancy": round(sum(pnls) / n, 2) if n else 0.0,
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2) if initial_balance else None,
    }
