"""État du bot partagé avec l'API : battement de cœur, analyse par paire, dernière erreur."""

from __future__ import annotations

import json
import os
from pathlib import Path


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
        # écriture atomique : l'API ne lit jamais un fichier à moitié écrit
        os.replace(tmp, self.path)

    @staticmethod
    def read(path: Path | str) -> dict:
        return StateStore(path).data
