"""Virtueller Output — spiegelt den letzten Frame für UI-Preview & Tests.

Sendet nichts ans Netzwerk, hält aber den zuletzt gerenderten Zustand vor,
den der WS-Hub als Live-Preview ausliefern kann.
"""
from __future__ import annotations

import numpy as np

from .base import OutputDevice


class VirtualOutput(OutputDevice):
    is_fixture = False  # zeigt immer die volle Canvas (keine Strobe-Alternation)

    def __init__(self, device_id: str = "virtual", name: str = "Preview", pixels: int = 60) -> None:
        super().__init__(device_id, name, pixels)
        self.last: np.ndarray = np.zeros((pixels, 3), dtype=np.uint8)

    async def send(self, rgb: np.ndarray) -> None:
        self.last = rgb

    def as_hex(self) -> list[str]:
        return ["#%02x%02x%02x" % (r, g, b) for r, g, b in self.last]
