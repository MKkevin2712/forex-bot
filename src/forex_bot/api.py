"""API FastAPI lue par le tableau de bord React (et qui sert le site compilé de web/dist)."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from forex_bot.backtest import conversion_pairs, run_backtest
from forex_bot.brokers import Broker, BrokerError, create_broker
from forex_bot.config import ROOT, Granularity, Settings, StrategyParams
from forex_bot.journal import Journal, create_journal
from forex_bot.metrics import trade_stats
from forex_bot.models import to_iso, utcnow
from forex_bot.risk import market_open
from forex_bot.state import StateStore
from forex_bot.strategy import compute_indicators

WEB_DIST = ROOT / "web" / "dist"


def _clean(value):
    """NaN/inf -> None et horodatages -> ISO pour que la réponse soit du JSON valide."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, pd.Timestamp | datetime):
        return to_iso(value)
    return value


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


class BacktestRequest(BaseModel):
    instruments: list[str] | None = None
    granularity: Granularity | None = None
    count: int = Field(3000, ge=300, le=5000)
    initial_balance: float = Field(10_000, gt=0)
    risk_per_trade: float | None = Field(None, gt=0, le=0.05)
    strategy: dict = Field(default_factory=dict)


def create_app(
    settings: Settings | None = None,
    broker_factory: Callable[[Settings], Broker] = create_broker,
    journal: Journal | None = None,
) -> FastAPI:
    settings = settings or Settings()
    journal = journal or create_journal(settings)
    app = FastAPI(title="Forex Bot API", version="0.1.0")
    cache: dict[str, Broker] = {}

    def broker() -> Broker:
        if "broker" not in cache:
            try:
                cache["broker"] = broker_factory(settings)
            except BrokerError as exc:
                raise HTTPException(503, f"Courtier indisponible : {exc}") from exc
        return cache["broker"]

    def drop_broker() -> None:
        """Après une erreur (ex. MT5 fermé puis rouvert), la prochaine requête se reconnecte."""
        stale = cache.pop("broker", None)
        if stale is not None:
            try:
                stale.close()
            except Exception:
                pass

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "time": to_iso(utcnow())}

    @app.get("/api/config")
    def config() -> dict:
        return settings.public_dict()

    @app.get("/api/overview")
    def overview() -> dict:
        state = StateStore.read(settings.state_path)
        account, positions, broker_error = None, [], None
        try:
            b = broker()
            account = b.account().__dict__
            positions = [
                {**t.__dict__, "direction": t.direction, "open_time": _clean(t.open_time)}
                for t in b.open_trades()
            ]
        except HTTPException as exc:
            broker_error = exc.detail
        except BrokerError as exc:
            broker_error = str(exc)
            drop_broker()
        return {
            "account": account,
            "positions": positions,
            "broker_error": broker_error,
            "stats": trade_stats(journal.closed_pnls()),
            "bot": {
                "heartbeat": state.get("heartbeat"),
                "status": state.get("status"),
                "last_error": state.get("last_error"),
                "analyses": state.get("analyses", {}),
            },
            "market_open": market_open(utcnow()),
        }

    @app.get("/api/trades")
    def trades(status: str | None = None, limit: int = 500) -> list[dict]:
        return [{k: _clean(v) for k, v in t.items()} for t in journal.trades(limit, status)]

    @app.get("/api/equity")
    def equity() -> list[dict]:
        return journal.equity_curve()

    @app.get("/api/candles/{instrument}")
    def candles(instrument: str, granularity: Granularity | None = None, count: int = 300) -> dict:
        instrument = instrument.upper()
        try:
            df = broker().candles(
                instrument, granularity or settings.granularity, settings.candle_count
            )
        except BrokerError as exc:
            drop_broker()
            raise HTTPException(502, str(exc)) from exc
        df = compute_indicators(df, settings.strategy).tail(count)
        markers = [
            {
                k: _clean(t[k])
                for k in (
                    "direction",
                    "entry_time",
                    "entry_price",
                    "exit_time",
                    "exit_price",
                    "close_reason",
                    "pnl",
                )
            }
            for t in journal.trades(1000)
            if t["instrument"] == instrument
        ]
        return {"instrument": instrument, "candles": _records(df), "trades": markers}

    @app.post("/api/backtest")
    def backtest(request: BacktestRequest) -> dict:
        overrides: dict = {
            "strategy": StrategyParams(**{**settings.strategy.model_dump(), **request.strategy})
        }
        if request.granularity:
            overrides["granularity"] = request.granularity
        if request.risk_per_trade:
            overrides["risk_per_trade"] = request.risk_per_trade
        run_settings = settings.model_copy(update=overrides)
        instruments = [i.upper() for i in (request.instruments or settings.instruments)]
        try:
            account_ccy = broker().account().currency
            gran = run_settings.granularity
            data = {i: broker().candles(i, gran, request.count) for i in instruments}
            conversions = {
                pair: broker().candles(pair, gran, request.count)
                for pair in conversion_pairs(instruments, account_ccy)
            }
            result = run_backtest(
                data,
                run_settings,
                request.initial_balance,
                account_currency=account_ccy,
                conversions=conversions,
            )
        except BrokerError as exc:
            drop_broker()
            raise HTTPException(502, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return result.to_dict()

    if WEB_DIST.exists():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
