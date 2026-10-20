"""État du bot partagé avec l'API : battement de cœur, analyse par paire, dernière erreur."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("forex_bot")
RETRIES = 5


class StateStore:
    def __init__(self, path: Path | str | None) -> None:
        self.path = Path(path) if path else None
        self.data: dict = {"heartbeat": None, "status": None, "last_error": None, "analyses": {}}
        if self.path and self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        # Écriture atomique : l'API ne lit jamais un fichier à moitié écrit. Sous Windows, le
        # remplacement échoue si un autre programme (tableau de bord, antivirus) lit le fichier
        # à ce moment-là : on réessaie, puis on passe son tour plutôt que d'arrêter le bot.
        for attempt in range(RETRIES):
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:
                time.sleep(0.2 * (attempt + 1))
        log.warning(
            "État du bot non enregistré (%s occupé), nouvel essai au prochain tour", self.path.name
        )

    @staticmethod
    def read(path: Path | str) -> dict:
        return StateStore(path).data
