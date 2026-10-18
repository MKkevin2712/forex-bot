"""Choix du courtier selon la configuration."""

from __future__ import annotations

from forex_bot.brokers.base import Broker, BrokerAuthError, BrokerError
from forex_bot.config import Settings

__all__ = ["Broker", "BrokerAuthError", "BrokerError", "create_broker"]


def create_broker(settings: Settings) -> Broker:
    if settings.broker == "oanda":
        from forex_bot.brokers.oanda import OandaBroker

        token = settings.oanda_token.get_secret_value() if settings.oanda_token else ""
        return OandaBroker(token, settings.oanda_account_id or "", settings.oanda_env)

    from forex_bot.brokers.mt5 import MT5Broker

    password = settings.mt5_password.get_secret_value() if settings.mt5_password else None
    return MT5Broker(
        login=settings.mt5_login,
        password=password,
        server=settings.mt5_server,
        path=settings.mt5_path,
        symbol_suffix=settings.mt5_symbol_suffix,
        magic=settings.mt5_magic,
        utc_offset_hours=settings.mt5_utc_offset,
    )
