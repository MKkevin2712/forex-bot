import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from forex_bot.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    for var in ("BROKER", "INSTRUMENTS", "DRY_RUN", "JOURNAL", "TRADING_HOURS_UTC"):
        monkeypatch.delenv(var, raising=False)
    return Settings(
        _env_file=None,
        instruments=["EUR_USD"],
        journal_path=tmp_path / "journal.sqlite",
        state_path=tmp_path / "state.json",
    )
