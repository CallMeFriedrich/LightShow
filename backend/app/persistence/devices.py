"""Persistenz der Ausgabegeräte (WLED) als JSON — UI-verwaltbar.

Ein Gerät: ``{"id", "name", "host", "pixels", "port"}``. Erstbefüllung aus der
ENV (``all_wled_nodes``); danach verwaltet das UI die Datei ``data/devices.json``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def load_devices(path: str | os.PathLike) -> list[dict]:
    p = Path(path)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def save_devices(path: str | os.PathLike, devices: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(devices, indent=2))
    os.replace(tmp, p)  # atomarer Write
