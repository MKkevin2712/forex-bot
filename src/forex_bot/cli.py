"""Ligne de commande : forex-bot run | backtest | download | reset | api."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from forex_bot.config import ROOT, Settings


def _setup_logging(level: str, log_file: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        )
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def cmd_run(settings: Settings, args: argparse.Namespace) -> None:
    from forex_bot.bot import TradingBot
    from forex_bot.brokers import create_broker
    from forex_bot.journal import create_journal
    from forex_bot.state import StateStore

    if args.dry_run:
        settings = settings.model_copy(update={"dry_run": True})
    if settings.broker == "oanda" and settings.oanda_env == "live" and not settings.dry_run:
        logging.warning("ATTENTION : compte OANDA RÉEL, les ordres engagent de l'argent réel")
    bot = TradingBot(
        create_broker(settings), create_journal(settings), settings, StateStore(settings.state_path)
    )
    if args.once:
        bot.run_cycle()
        print(json.dumps(bot.state.data.get("analyses", {}), ensure_ascii=False, indent=2))
    else:
        bot.run_forever()


def cmd_download(settings: Settings, args: argparse.Namespace) -> None:
    from forex_bot.brokers import create_broker

    broker = create_broker(settings)
    out = Path(args.out or settings.candles_dir)
    out.mkdir(parents=True, exist_ok=True)
    for instrument in args.instruments or settings.instruments:
        df = broker.candles(instrument, settings.granularity, args.count)
        path = out / f"{instrument}_{settings.granularity}.csv"
        df.to_csv(path, index=False)
        print(f"{instrument} : {len(df)} bougies -> {path}")


def cmd_backtest(settings: Settings, args: argparse.Namespace) -> None:
    from forex_bot.backtest import conversion_pairs, load_csv, run_backtest

    instruments = args.instruments or settings.instruments
    if args.csv_dir:
        currency = args.currency or "USD"

        def load(instrument: str):
            return load_csv(Path(args.csv_dir) / f"{instrument}_{settings.granularity}.csv")
    else:
        from forex_bot.brokers import create_broker

        broker = create_broker(settings)
        currency = args.currency or broker.account().currency

        def load(instrument: str):
            return broker.candles(instrument, settings.granularity, args.count)

    data = {i: load(i) for i in instruments}
    conversions = {pair: load(pair) for pair in conversion_pairs(instruments, currency)}
    result = run_backtest(
        data, settings, args.balance, account_currency=currency, conversions=conversions
    ).to_dict()
    print(f"Devise        : {currency}")

    stats = result["stats"]
    print(f"Période       : {result['period'].get('start')} -> {result['period'].get('end')}")
    print(
        f"Capital       : {result['initial_balance']:.2f} -> {result['final_balance']:.2f} "
        f"({result['total_return_pct']:+.2f} %)"
    )
    print(f"Trades        : {stats['trades']} (win rate {stats['win_rate']} %)")
    print(f"Profit factor : {stats['profit_factor']}")
    print(f"Drawdown max  : {stats['max_drawdown']:.2f} ({stats['max_drawdown_pct']} %)")
    for inst, st in result["per_instrument"].items():
        print(
            f"  {inst:8s} {st['trades']:4d} trades  win {st['win_rate']:6.2f} %  "
            f"P&L {st['total_pnl']:+.2f}"
        )
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Résultat complet -> {args.out}")


def cmd_reset(settings: Settings, args: argparse.Namespace) -> None:
    from forex_bot.brokers import create_broker

    broker = create_broker(settings)
    trades = broker.open_trades()
    if not trades:
        print("Aucune position ouverte par le bot.")
        return
    for t in trades:
        print(f"  {t.id} {t.instrument} {t.direction} {abs(t.units):g} unités")
    if not args.yes and input(f"Fermer ces {len(trades)} positions ? [o/N] ").lower() != "o":
        print("Annulé.")
        return
    for trade_id in broker.close_all():
        print(f"Position {trade_id} fermée.")


def cmd_api(settings: Settings, args: argparse.Namespace) -> None:
    import uvicorn

    from forex_bot.api import create_app

    uvicorn.run(create_app(settings), host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="forex-bot", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="lance le bot en continu")
    run.add_argument("--dry-run", action="store_true", help="analyse sans envoyer d'ordre")
    run.add_argument("--once", action="store_true", help="un seul cycle puis arrêt")
    run.set_defaults(func=cmd_run)

    dl = sub.add_parser("download", help="télécharge l'historique en CSV")
    dl.add_argument("--instruments", nargs="+")
    dl.add_argument("--count", type=int, default=5000)
    dl.add_argument("--out")
    dl.set_defaults(func=cmd_download)

    bt = sub.add_parser("backtest", help="teste la stratégie sur l'historique")
    bt.add_argument("--instruments", nargs="+")
    bt.add_argument("--count", type=int, default=5000)
    bt.add_argument("--balance", type=float, default=10_000)
    bt.add_argument("--currency", help="devise du compte (par défaut celle du courtier, ou USD)")
    bt.add_argument("--csv-dir", help="dossier de CSV (sinon téléchargement depuis le courtier)")
    bt.add_argument("--out", default=str(ROOT / "reports" / "backtest.json"))
    bt.set_defaults(func=cmd_backtest)

    reset = sub.add_parser("reset", help="ferme toutes les positions ouvertes par le bot")
    reset.add_argument("--yes", action="store_true")
    reset.set_defaults(func=cmd_reset)

    api = sub.add_parser("api", help="lance l'API et le tableau de bord")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.set_defaults(func=cmd_api)

    args = parser.parse_args(argv)
    settings = Settings()
    _setup_logging(settings.log_level, settings.log_file)
    from forex_bot.brokers import BrokerError

    try:
        args.func(settings, args)
    except KeyboardInterrupt:
        print("\nArrêt demandé.")
        sys.exit(0)
    except BrokerError as exc:
        print(f"Erreur courtier : {exc}\nVérifiez votre fichier .env (voir .env.example).")
        sys.exit(1)


if __name__ == "__main__":
    main()
