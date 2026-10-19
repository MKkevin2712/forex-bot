"""Bilan quotidien du bot (P&L du jour, trades, positions, signaux), envoyé sur Discord."""

from __future__ import annotations

from datetime import datetime, timedelta

import requests

from forex_bot.brokers.base import Broker, BrokerError
from forex_bot.config import Settings
from forex_bot.journal import Journal
from forex_bot.metrics import trade_stats
from forex_bot.models import utcnow

SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥", "CHF": "CHF"}
GREEN, RED, GREY = 0x2FC89A, 0xFF6B81, 0x8B93A3
FIELD_LIMIT = 1024  # limite Discord par champ


def money(value: float | None, currency: str = "EUR", signed: bool = False) -> str:
    if value is None:
        return "—"
    text = f"{abs(value):,.2f}".replace(",", " ").replace(".", ",")
    sign = (
        ("+" if value > 0 else "-" if value < 0 else "") if signed else ("-" if value < 0 else "")
    )
    return f"{sign}{text} {SYMBOLS.get(currency, currency)}"


def pair(instrument: str) -> str:
    return instrument.replace("_", "/")


def _parse(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso) if iso else None


def build_report(
    journal: Journal,
    settings: Settings,
    state: dict,
    broker: Broker | None = None,
    now: datetime | None = None,
) -> dict:
    """Données du bilan sur les 24 dernières heures."""
    now = now or utcnow()
    since = now - timedelta(hours=24)

    account, positions, broker_error = None, [], None
    if broker is not None:
        try:
            account = broker.account()
            positions = broker.open_trades()
        except BrokerError as exc:
            broker_error = str(exc)
    currency = account.currency if account else "EUR"

    closed_today = [
        t
        for t in journal.trades(limit=1000, status="CLOSED")
        if t["exit_time"] and _parse(t["exit_time"]) >= since
    ]
    opened_today = [t for t in journal.trades(limit=1000) if _parse(t["entry_time"]) >= since]
    signals = [s for s in state.get("signals", []) if s.get("time") and _parse(s["time"]) >= since]
    heartbeat = _parse(state.get("heartbeat"))

    return {
        "time": now,
        "dry_run": settings.dry_run,
        "currency": currency,
        "account": account,
        "positions": positions,
        "broker_error": broker_error,
        "realized_today": round(sum(t["pnl"] or 0 for t in closed_today), 2),
        "closed_today": closed_today,
        "opened_today": opened_today,
        "signals": signals,
        "stats": trade_stats(journal.closed_pnls()),
        "heartbeat": heartbeat,
        "bot_alive": heartbeat is not None and now - heartbeat < timedelta(minutes=10),
    }


def _lines(lines: list[str], empty: str) -> str:
    if not lines:
        return empty
    text = ""
    for i, line in enumerate(lines):
        rest = f"\n… et {len(lines) - i} autre(s)"
        if len(text) + len(line) + 1 + len(rest) > FIELD_LIMIT:
            return text + rest
        text += ("\n" if text else "") + line
    return text


def format_discord(report: dict) -> dict:
    """Message Discord (un « embed ») à partir du bilan."""
    ccy = report["currency"]
    pnl = report["realized_today"]
    account = report["account"]
    color = GREEN if pnl > 0 else RED if pnl < 0 else GREY

    description = []
    if report["dry_run"]:
        description.append("🧪 **Mode simulation** : aucun ordre n'est envoyé au courtier.")
    if not report["bot_alive"]:
        last = report["heartbeat"]
        when = last.strftime("%d/%m %H:%M UTC") if last else "jamais"
        description.append(f"⚠️ **Le bot ne répond plus** (dernier signe de vie : {when}).")
    if report["broker_error"]:
        description.append(f"⚠️ Courtier injoignable : {report['broker_error']}")

    fields = [
        {"name": "Résultat du jour", "value": money(pnl, ccy, signed=True), "inline": True},
        {
            "name": "Solde",
            "value": money(account.balance, ccy) if account else "—",
            "inline": True,
        },
        {
            "name": "Latent",
            "value": money(account.unrealized_pnl, ccy, signed=True) if account else "—",
            "inline": True,
        },
    ]

    closed = [
        f"{pair(t['instrument'])} {'Achat' if t['direction'] == 'LONG' else 'Vente'} · "
        f"{t['close_reason']} · **{money(t['pnl'], ccy, signed=True)}**"
        for t in report["closed_today"]
    ]
    fields.append(
        {"name": "Trades clôturés (24 h)", "value": _lines(closed, "Aucun"), "inline": False}
    )

    positions = [
        f"{pair(p.instrument)} {'Achat' if p.units > 0 else 'Vente'} "
        f"{f'{abs(p.units):,.0f}'.replace(',', ' ')} u. · "
        f"latent {money(p.unrealized_pnl, ccy, signed=True)}"
        for p in report["positions"]
    ]
    fields.append(
        {"name": "Positions ouvertes", "value": _lines(positions, "Aucune"), "inline": False}
    )

    signals = [
        f"`{_parse(s['time']).strftime('%H:%M')}` {pair(s['instrument'])} "
        f"{'Achat' if s['signal'] == 'LONG' else 'Vente'} → {s.get('action') or '—'}"
        for s in report["signals"]
    ]
    fields.append(
        {"name": "Signaux du jour (UTC)", "value": _lines(signals, "Aucun"), "inline": False}
    )

    st = report["stats"]
    pf = "—" if st["profit_factor"] is None else f"{st['profit_factor']:.2f}".replace(".", ",")
    win_rate = f"{st['win_rate']:.1f}".replace(".", ",")
    fields.append(
        {
            "name": "Depuis le début",
            "value": (
                f"{st['trades']} trades · réussite {win_rate} % · profit factor {pf} · "
                f"P&L {money(st['total_pnl'], ccy, signed=True)}"
            ),
            "inline": False,
        }
    )

    embed = {
        "title": f"Bilan du {report['time'].strftime('%d/%m/%Y')}",
        "color": color,
        "fields": fields,
        "footer": {"text": "forex-bot · bilan des 24 dernières heures"},
        "timestamp": report["time"].isoformat(),
    }
    if description:
        embed["description"] = "\n".join(description)
    return {"username": "Forex Bot", "embeds": [embed]}


def send_discord(webhook_url: str, payload: dict, timeout: float = 15) -> None:
    response = requests.post(webhook_url, json=payload, timeout=timeout)
    if response.status_code >= 400:
        raise RuntimeError(
            f"Discord a refusé le message ({response.status_code}) : {response.text[:200]}"
        )
