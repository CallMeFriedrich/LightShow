"""Task-Supervisor.

Startet, überwacht und restartet die entkoppelten async Tasks der Anwendung.
Ein abgestürzter Task reißt die App nicht mit: er wird mit exponentiellem
Backoff (+ Jitter) neu gestartet. Status wird auf den Event-Bus gemeldet.
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .event_bus import EventBus

log = logging.getLogger(__name__)

TaskFactory = Callable[[], Awaitable[None]]


@dataclass
class _Supervised:
    name: str
    factory: TaskFactory
    restart: bool = True
    task: asyncio.Task | None = None
    restarts: int = 0
    state: str = "pending"  # pending | running | crashed | stopped


@dataclass
class Engine:
    bus: EventBus
    _tasks: dict[str, _Supervised] = field(default_factory=dict)
    _stopping: bool = False
    max_backoff: float = 10.0

    def register(self, name: str, factory: TaskFactory, *, restart: bool = True) -> None:
        self._tasks[name] = _Supervised(name=name, factory=factory, restart=restart)

    def start(self) -> None:
        self._stopping = False
        for sup in self._tasks.values():
            if sup.task is None or sup.task.done():
                sup.task = asyncio.create_task(self._runner(sup), name=sup.name)

    async def _runner(self, sup: _Supervised) -> None:
        backoff = 0.5
        while not self._stopping:
            sup.state = "running"
            self._emit(sup)
            try:
                await sup.factory()
                sup.state = "stopped"
                self._emit(sup)
                return
            except asyncio.CancelledError:
                sup.state = "stopped"
                self._emit(sup)
                raise
            except Exception:  # noqa: BLE001 — Supervisor darf alles fangen
                log.exception("Task %r crashed", sup.name)
                sup.state = "crashed"
                sup.restarts += 1
                self._emit(sup)
                if not sup.restart or self._stopping:
                    return
                sleep = min(self.max_backoff, backoff) * (1.0 + random.random() * 0.3)
                await asyncio.sleep(sleep)
                backoff = min(self.max_backoff, backoff * 2)

    def _emit(self, sup: _Supervised) -> None:
        self.bus.publish(
            "system.status",
            {
                "type": "task",
                "name": sup.name,
                "state": sup.state,
                "restarts": sup.restarts,
            },
        )

    def status(self) -> list[dict]:
        return [
            {"name": s.name, "state": s.state, "restarts": s.restarts}
            for s in self._tasks.values()
        ]

    async def stop(self) -> None:
        self._stopping = True
        tasks = [s.task for s in self._tasks.values() if s.task and not s.task.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
