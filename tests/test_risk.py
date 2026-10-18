from datetime import UTC, datetime

import pytest

from forex_bot.metrics import trade_stats
from forex_bot.risk import daily_loss_reached, entry_window, market_open, position_units


def test_units_eur_usd():
    # 1 % de 10 000 = 100 USD de risque, SL à 50 pips -> 20 000 unités
    units = position_units(
        balance=10_000,
        risk_fraction=0.01,
        entry=1.1000,
        stop=1.0950,
        value_per_unit=1.0,
        max_leverage=30,
    )
    assert units == 20_000


def test_units_usd_jpy_uses_conversion():
    # SL à 75 pips (0,75 JPY), 1 JPY = 1/150 USD -> 100 / (0,75/150) = 20 000 unités
    units = position_units(
        balance=10_000,
        risk_fraction=0.01,
        entry=150.0,
        stop=149.25,
        value_per_unit=1 / 150,
        max_leverage=30,
    )
    assert units == pytest.approx(20_000, abs=1)


def test_units_capped_by_leverage():
    # SL très serré : la taille brute (1 000 000) est plafonnée à 10x le solde
    units = position_units(
        balance=10_000,
        risk_fraction=0.01,
        entry=1.0,
        stop=0.9999,
        value_per_unit=1.0,
        max_leverage=10,
    )
    assert units == 100_000


def test_units_rounded_and_minimum():
    units = position_units(
        balance=10_000,
        risk_fraction=0.01,
        entry=1.1,
        stop=1.0950,
        value_per_unit=1.0,
        max_leverage=30,
        units_step=1000,
    )
    assert units == 20_000 - 20_000 % 1000
    assert (
        position_units(
            balance=10,
            risk_fraction=0.01,
            entry=1.1,
            stop=1.0,
            value_per_unit=1.0,
            max_leverage=30,
            min_units=1000,
        )
        == 0
    )


@pytest.mark.parametrize(
    "when, is_open",
    [
        (datetime(2026, 10, 21, 12, tzinfo=UTC), True),  # mercredi
        (datetime(2026, 10, 24, 12, tzinfo=UTC), False),  # samedi
        (datetime(2026, 10, 23, 21, 30, tzinfo=UTC), False),  # vendredi soir
        (datetime(2026, 10, 25, 20, tzinfo=UTC), False),  # dimanche avant l'ouverture
        (datetime(2026, 10, 25, 22, 30, tzinfo=UTC), True),  # dimanche soir
    ],
)
def test_market_open(when, is_open):
    assert market_open(when) is is_open


def test_entry_window():
    friday = datetime(2026, 10, 23, 19, tzinfo=UTC)
    assert entry_window(friday, 18, None)[0] is False
    tuesday_night = datetime(2026, 10, 20, 2, tzinfo=UTC)
    assert entry_window(tuesday_night, 18, None)[0] is True
    assert entry_window(tuesday_night, 18, "07-20")[0] is False


def test_daily_loss_limit():
    assert daily_loss_reached(-300, 9_700, 0.03) is True
    assert daily_loss_reached(-100, 9_900, 0.03) is False


def test_trade_stats():
    stats = trade_stats([100, -50, 100, -50, -50], initial_balance=1000)
    assert stats["win_rate"] == 40.0
    assert stats["profit_factor"] == pytest.approx(200 / 150, abs=0.01)
    assert stats["max_drawdown"] == 100
    assert stats["total_pnl"] == 50
