import json

from forex_bot import state as state_module
from forex_bot.state import StateStore


def test_save_retries_when_file_is_locked(tmp_path, monkeypatch):
    """Sous Windows, state.json peut être verrouillé un instant (lecture par l'API, antivirus)."""
    monkeypatch.setattr(state_module.time, "sleep", lambda s: None)
    real_replace = state_module.os.replace
    calls = []

    def flaky_replace(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("[WinError 5] Accès refusé")
        real_replace(src, dst)

    monkeypatch.setattr(state_module.os, "replace", flaky_replace)
    store = StateStore(tmp_path / "state.json")
    store.data["status"] = "en marche"
    store.save()
    assert len(calls) == 3
    assert (
        json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["status"] == "en marche"
    )


def test_save_never_crashes_the_bot(tmp_path, monkeypatch):
    monkeypatch.setattr(state_module.time, "sleep", lambda s: None)

    def always_locked(src, dst):
        raise PermissionError("[WinError 5] Accès refusé")

    monkeypatch.setattr(state_module.os, "replace", always_locked)
    StateStore(tmp_path / "state.json").save()  # ne lève pas d'exception
