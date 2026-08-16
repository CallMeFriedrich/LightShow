"""Licht-Pult-Layout mit Undo/Redo (§4 Interface 2).

Speichert das aktuelle Layout serverseitig (``data/console.json`` — überlebt
Neustart, §Fail-Safety) und hält Undo/Redo-Historie (in-memory, pro Serverlauf).
Ein Layout = ``{"columns": int, "controls": [ {id, type, label, action, ...} ]}``.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

_DEFAULT = {"columns": 6, "controls": []}
_MAX_HISTORY = 100


class ConsoleManager:
    def __init__(self, path: str | os.PathLike) -> None:
        self._path = Path(path)
        self._current = self._load()
        self._undo: list[dict] = []
        self._redo: list[dict] = []

    def _load(self) -> dict:
        if self._path.is_file():
            try:
                data = json.loads(self._path.read_text())
                if isinstance(data, dict):
                    return {**_DEFAULT, **data}
            except Exception:  # noqa: BLE001
                pass
        return copy.deepcopy(_DEFAULT)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._current, indent=2))
        os.replace(tmp, self._path)  # atomar

    def get(self) -> dict:
        return {
            "layout": self._current,
            "can_undo": bool(self._undo),
            "can_redo": bool(self._redo),
        }

    def set(self, layout: dict) -> dict:
        self._undo.append(copy.deepcopy(self._current))
        if len(self._undo) > _MAX_HISTORY:
            self._undo.pop(0)
        self._redo.clear()
        self._current = {**_DEFAULT, **layout}
        self._save()
        return self.get()

    def undo(self) -> dict:
        if self._undo:
            self._redo.append(copy.deepcopy(self._current))
            self._current = self._undo.pop()
            self._save()
        return self.get()

    def redo(self) -> dict:
        if self._redo:
            self._undo.append(copy.deepcopy(self._current))
            self._current = self._redo.pop()
            self._save()
        return self.get()
