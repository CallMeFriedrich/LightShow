"""Frame-Clock für eine konstante Output-Rate (30–44 Hz).

Kompensiert Drift, indem die nächste Tick-Zeit relativ zum idealen Raster
berechnet wird — nicht relativ zum Ende der letzten Arbeit.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator


class FrameClock:
    def __init__(self, rate_hz: float) -> None:
        self.period = 1.0 / max(1.0, rate_hz)
        self._next: float | None = None

    async def tick(self) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        if self._next is None:
            self._next = now + self.period
        delay = self._next - now
        if delay > 0:
            await asyncio.sleep(delay)
            self._next += self.period
        else:
            # Zu spät — Raster neu ausrichten, um Aufholjagd zu vermeiden.
            self._next = now + self.period

    async def ticks(self) -> AsyncIterator[None]:
        while True:
            await self.tick()
            yield
