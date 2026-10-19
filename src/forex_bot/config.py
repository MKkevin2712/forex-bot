"""Configuration du bot, lue depuis les variables d'environnement et le fichier .env.

Les paramètres de stratégie se surchargent avec le préfixe STRATEGY__
(ex. STRATEGY__ATR_STOP_MULT=2).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

Granularity = Literal["M15", "M30", "H1", "H4", "D"]

GRANULARITY_DELTA: dict[str, timedelta] = {
    "M15": timedelta(minutes=15),
    "M30": timedelta(minutes=30),
    "H1": timedelta(hours=1),
    "H4": timedelta(hours=4),
    "D": timedelta(days=1),
}


class StrategyParams(BaseModel):
    """Suivi de tendance : EMA alignées + RSI + volume, sortie par SL/TP basés sur l'ATR."""

    ema_fast: int = 20
    ema_mid: int = 50
    ema_slow: int = 200
    rsi_period: int = 14
    atr_period: int = 14
    volume_period: int = 20
    rsi_long_max: float = 60.0  # pas d'achat si le marché est déjà en surchauffe
    rsi_short_min: float = 40.0  # pas de vente si le marché est déjà survendu
    use_volume_filter: bool = True  # volume en tick sur le forex : approximation de l'activité
    atr_stop_mult: float = 1.5
    reward_risk: float = 1.5


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # --- Marché ---
    broker: Literal["oanda", "mt5"] = "oanda"
    instruments: Annotated[list[str], NoDecode] = ["EUR_USD", "GBP_USD", "USD_JPY"]
    granularity: Granularity = "H4"
    candle_count: int = 500

    # --- Gestion du risque ---
    risk_per_trade: float = Field(0.01, gt=0, le=0.05)
    max_leverage: float = Field(10.0, gt=0)
    max_open_trades: int = Field(3, ge=1)
    daily_loss_limit: float = Field(0.03, gt=0, le=1)
    max_spread_atr: float = 0.15  # spread maximal accepté, en fraction de l'ATR
    trading_hours_utc: str | None = None  # ex. "07-20" pour ne trader que Londres + New York
    friday_cutoff_utc: int = 18  # pas de nouvelle position avant le gap du week-end

    # --- Fonctionnement ---
    poll_seconds: int = 60
    dry_run: bool = False
    log_level: str = "INFO"
    log_file: Path | None = None  # journal technique en fichier (rotation à 2 Mo)
    strategy: StrategyParams = StrategyParams()

    # --- OANDA ---
    oanda_token: SecretStr | None = None
    oanda_account_id: str | None = None
    oanda_env: Literal["practice", "live"] = "practice"

    # --- MetaTrader 5 ---
    mt5_login: int | None = None
    mt5_password: SecretStr | None = None
    mt5_server: str | None = None
    mt5_path: str | None = None
    mt5_symbol_suffix: str = ""
    mt5_magic: int = 240611
    mt5_utc_offset: int | None = None  # heure serveur - UTC ; détecté automatiquement si vide

    # --- Stockage ---
    journal: Literal["sqlite", "supabase"] = "sqlite"
    journal_path: Path = ROOT / "data" / "journal.sqlite"
    state_path: Path = ROOT / "data" / "state.json"
    candles_dir: Path = ROOT / "data" / "candles"
    supabase_url: str | None = None
    supabase_key: SecretStr | None = None

    # --- Bilan quotidien ---
    discord_webhook_url: SecretStr | None = None

    @field_validator("instruments", mode="before")
    @classmethod
    def _split_instruments(cls, value: object) -> object:
        if isinstance(value, str):
            return [v.strip().upper() for v in value.split(",") if v.strip()]
        return value

    @field_validator("trading_hours_utc")
    @classmethod
    def _check_hours(cls, value: str | None) -> str | None:
        if value:
            start, end = (int(h) for h in value.split("-"))
            if not (0 <= start < 24 and 0 < end <= 24 and start < end):
                raise ValueError("trading_hours_utc doit être de la forme 'HH-HH', ex. '07-20'")
        return value or None

    @property
    def candle_delta(self) -> timedelta:
        return GRANULARITY_DELTA[self.granularity]

    def public_dict(self) -> dict:
        """Configuration sans aucun secret, exposée par l'API."""
        return {
            "broker": self.broker,
            "instruments": self.instruments,
            "granularity": self.granularity,
            "risk_per_trade": self.risk_per_trade,
            "max_leverage": self.max_leverage,
            "max_open_trades": self.max_open_trades,
            "daily_loss_limit": self.daily_loss_limit,
            "max_spread_atr": self.max_spread_atr,
            "trading_hours_utc": self.trading_hours_utc,
            "friday_cutoff_utc": self.friday_cutoff_utc,
            "dry_run": self.dry_run,
            "oanda_env": self.oanda_env if self.broker == "oanda" else None,
            "strategy": self.strategy.model_dump(),
        }
