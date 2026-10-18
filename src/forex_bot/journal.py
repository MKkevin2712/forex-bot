"""Journal de trading : chaque position avec son entrée, sa sortie et son P&L réel.

SQLite par défaut (aucun service externe), Supabase en option (schéma dans sql/supabase_schema.sql).
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from forex_bot.config import Settings
from forex_bot.models import ClosedTrade, to_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,
    broker_trade_id TEXT NOT NULL,
    instrument TEXT NOT NULL,
    direction TEXT NOT NULL,
    units REAL NOT NULL,
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    risk_amount REAL,
    signal_reason TEXT,
    indicators TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN',
    exit_time TEXT,
    exit_price REAL,
    pnl REAL,
    close_reason TEXT,
    UNIQUE (broker, broker_trade_id)
);
CREATE TABLE IF NOT EXISTS equity (
    time TEXT PRIMARY KEY,
    balance REAL NOT NULL,
    nav REAL NOT NULL
);
"""


class Journal(ABC):
    @abstractmethod
    def record_open(self, trade: dict) -> None:
        """Clés : broker, broker_trade_id, instrument, direction, units, entry_time, entry_price,
        stop_loss, take_profit, risk_amount, signal_reason, indicators (dict)."""

    @abstractmethod
    def open_trades(self, broker: str) -> list[dict]: ...

    @abstractmethod
    def record_close(self, broker: str, closed: ClosedTrade) -> None: ...

    @abstractmethod
    def trades(self, limit: int = 500, status: str | None = None) -> list[dict]: ...

    @abstractmethod
    def realized_pnl_since(self, since: datetime) -> float: ...

    @abstractmethod
    def record_equity(self, time: datetime, balance: float, nav: float) -> None: ...

    @abstractmethod
    def equity_curve(self, limit: int = 2000) -> list[dict]: ...

    def closed_pnls(self) -> list[float]:
        closed = self.trades(limit=100_000, status="CLOSED")
        return [
            t["pnl"] for t in sorted(closed, key=lambda t: t["exit_time"]) if t["pnl"] is not None
        ]


def _decode(row: dict) -> dict:
    if isinstance(row.get("indicators"), str):
        row["indicators"] = json.loads(row["indicators"])
    return row


class SQLiteJournal(Journal):
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def record_open(self, trade: dict) -> None:
        row = {**trade, "indicators": json.dumps(trade.get("indicators") or {})}
        columns = ", ".join(row)
        placeholders = ", ".join(f":{k}" for k in row)
        with self.conn:
            self.conn.execute(
                f"INSERT OR IGNORE INTO trades ({columns}) VALUES ({placeholders})", row
            )

    def open_trades(self, broker: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM trades WHERE status = 'OPEN' AND broker = ?", (broker,)
        ).fetchall()
        return [_decode(dict(r)) for r in rows]

    def record_close(self, broker: str, closed: ClosedTrade) -> None:
        with self.conn:
            self.conn.execute(
                """UPDATE trades SET status = 'CLOSED', exit_time = ?, exit_price = ?, pnl = ?,
                   close_reason = ? WHERE broker = ? AND broker_trade_id = ?""",
                (
                    to_iso(closed.exit_time),
                    closed.exit_price,
                    closed.pnl,
                    closed.reason,
                    broker,
                    closed.trade_id,
                ),
            )

    def trades(self, limit: int = 500, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM trades"
        params: tuple = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY entry_time DESC LIMIT ?"
        rows = self.conn.execute(query, (*params, limit)).fetchall()
        return [_decode(dict(r)) for r in rows]

    def realized_pnl_since(self, since: datetime) -> float:
        value = self.conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status = 'CLOSED' AND exit_time >= ?",
            (to_iso(since),),
        ).fetchone()[0]
        return float(value)

    def record_equity(self, time: datetime, balance: float, nav: float) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO equity (time, balance, nav) VALUES (?, ?, ?)",
                (to_iso(time), balance, nav),
            )

    def equity_curve(self, limit: int = 2000) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM (SELECT * FROM equity ORDER BY time DESC LIMIT ?) ORDER BY time",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


class SupabaseJournal(Journal):
    def __init__(self, url: str, key: str) -> None:
        try:
            from supabase import create_client
        except ImportError as exc:
            raise RuntimeError("Installez l'extra supabase : uv sync --extra supabase") from exc
        self.db = create_client(url, key)

    def record_open(self, trade: dict) -> None:
        self.db.table("trades").upsert(
            trade, on_conflict="broker,broker_trade_id", ignore_duplicates=True
        ).execute()

    def open_trades(self, broker: str) -> list[dict]:
        query = self.db.table("trades").select("*").eq("status", "OPEN").eq("broker", broker)
        return query.execute().data

    def record_close(self, broker: str, closed: ClosedTrade) -> None:
        self.db.table("trades").update(
            {
                "status": "CLOSED",
                "exit_time": to_iso(closed.exit_time),
                "exit_price": closed.exit_price,
                "pnl": closed.pnl,
                "close_reason": closed.reason,
            }
        ).eq("broker", broker).eq("broker_trade_id", closed.trade_id).execute()

    def trades(self, limit: int = 500, status: str | None = None) -> list[dict]:
        query = self.db.table("trades").select("*")
        if status:
            query = query.eq("status", status)
        return query.order("entry_time", desc=True).limit(limit).execute().data

    def realized_pnl_since(self, since: datetime) -> float:
        rows = (
            self.db.table("trades")
            .select("pnl")
            .eq("status", "CLOSED")
            .gte("exit_time", to_iso(since))
            .execute()
            .data
        )
        return float(sum(r["pnl"] or 0 for r in rows))

    def record_equity(self, time: datetime, balance: float, nav: float) -> None:
        self.db.table("equity").upsert(
            {"time": to_iso(time), "balance": balance, "nav": nav}
        ).execute()

    def equity_curve(self, limit: int = 2000) -> list[dict]:
        rows = self.db.table("equity").select("*").order("time", desc=True).limit(limit)
        return list(reversed(rows.execute().data))


def create_journal(settings: Settings) -> Journal:
    if settings.journal == "supabase":
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError(
                "SUPABASE_URL et SUPABASE_KEY sont obligatoires avec JOURNAL=supabase"
            )
        return SupabaseJournal(settings.supabase_url, settings.supabase_key.get_secret_value())
    return SQLiteJournal(settings.journal_path)
