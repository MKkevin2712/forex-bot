# Forex Bot

Bot de trading algorithmique sur le marché des changes (EUR/USD, GBP/USD, USD/JPY…), avec
gestion du risque, backtest, API FastAPI et tableau de bord React.

Il fonctionne avec **OANDA** (API REST v20) ou **MetaTrader 5**, sur compte **démo** par défaut.

> Projet personnel d'apprentissage. Ce n'est pas un conseil en investissement : le trading
> sur marge peut faire perdre plus que la mise.

## Ce que fait le bot

À chaque bougie clôturée (H4 par défaut), pour chaque paire :

1. **Synchronise** les positions fermées par le courtier (SL ou TP) et enregistre le P&L réel,
   swaps compris.
2. **Calcule** les EMA 20/50/200, le RSI 14 (Wilder), l'ATR 14 (Wilder) et le volume moyen.
3. **Décide** :
   - achat si EMA20 > EMA50 > EMA200, RSI < 60 et volume au-dessus de sa moyenne ;
   - vente à découvert dans la configuration symétrique (RSI > 40) ;
   - sinon rien, avec la raison affichée sur le tableau de bord.
4. **Contrôle le risque** avant d'entrer :
   - une seule position par paire et au maximum 3 au total ;
   - pas de nouvelle position le vendredi soir (gap du week-end) ni marché fermé ;
   - coupe-circuit à −3 % de perte dans la journée ;
   - spread refusé s'il dépasse 15 % de l'ATR.
5. **Dimensionne** la position pour risquer 1 % du capital : `unités = risque / (distance SL × valeur d'une unité)`,
   avec conversion de devise (USD/JPY, etc.) et plafond d'effet de levier.
6. **Envoie l'ordre au marché avec SL et TP attachés dans le même ordre** : la position n'existe
   jamais sans protection. Si le SL manque malgré tout, la position est refermée immédiatement.

## Architecture

```
src/forex_bot/
├── brokers/        interface commune + OANDA (REST) + MetaTrader 5
├── strategy.py     indicateurs → décision (même code pour le direct et le backtest)
├── risk.py         taille de position, horaires du forex, coupe-circuit
├── bot.py          boucle de trading
├── backtest.py     simulation bougie par bougie (spread, gaps, SL prioritaire)
├── journal.py      journal des trades : SQLite (défaut) ou Supabase
├── metrics.py      win rate, profit factor, espérance, drawdown
├── api.py          API FastAPI lue par le tableau de bord
└── cli.py          forex-bot run | backtest | download | reset | api
web/                tableau de bord React + TypeScript (Vite, lightweight-charts)
tests/              46 tests pytest (faux courtier, réponses OANDA/MT5 enregistrées)
```

## Installation

Prérequis : [uv](https://docs.astral.sh/uv/) et Node.js 20+.

```bash
uv sync                      # Python 3.12 + dépendances
uv sync --extra mt5          # en plus, pour MetaTrader 5 (Windows)
cd web && npm install && npm run build
```

Copiez `.env.example` en `.env` et renseignez votre courtier.

- **OANDA** : créez un compte *practice* gratuit, puis un jeton dans *Manage API Access*.
- **MetaTrader 5** : ouvrez un compte démo chez un courtier MT5, installez le terminal et
  cochez *Algo Trading*. Si les symboles ont un suffixe (`EURUSD.m`), renseignez `MT5_SYMBOL_SUFFIX`.

## Utilisation

```bash
uv run forex-bot backtest                 # backtest sur 5000 bougies téléchargées chez le courtier
uv run forex-bot run --dry-run --once     # une analyse, sans envoyer d'ordre
uv run forex-bot run                      # le bot en continu
uv run forex-bot api                      # tableau de bord sur http://127.0.0.1:8000
uv run forex-bot reset                    # ferme les positions ouvertes par le bot
```

En développement du front : `uv run forex-bot api` dans un terminal et `npm run dev` dans
`web/` (les appels `/api` sont redirigés vers le port 8000).

## Tableau de bord

- solde, valeur liquidative, P&L réalisé, taux de réussite, profit factor, drawdown ;
- graphique en bougies avec EMA, volume, RSI et les entrées/sorties du bot ;
- dernière analyse de chaque paire, avec la raison de la décision ;
- positions ouvertes, courbe du capital et journal complet ;
- onglet **Backtest** pour tester d'autres réglages sans toucher au code.

## Backtest : hypothèses

- le signal est pris à la clôture, l'entrée à l'ouverture de la bougie suivante (aucune donnée future) ;
- achat à l'ask, vente au bid, avec un spread fixe par paire ;
- si le SL et le TP sont touchés dans la même bougie, on retient le SL ;
- un gap au-delà du SL est exécuté au prix d'ouverture ;
- les swaps ne sont pas simulés, et seules les paires contenant la devise du compte sont gérées.

## Tests

```bash
uv run pytest
uv run ruff check src tests
```

## Limites connues

- une seule stratégie, sans optimisation des paramètres ni validation *walk-forward* ;
- pas de filtre sur les annonces économiques (NFP, BCE…) ;
- pas de contrôle de corrélation entre paires (EUR/USD et GBP/USD bougent souvent ensemble) ;
- le bot doit tourner sur une machine allumée en permanence (VPS) ; MT5 impose Windows.
