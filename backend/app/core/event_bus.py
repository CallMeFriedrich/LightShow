"""Async Pub/Sub Event-Bus.

Entkoppelt Producer und Consumer über typisierte Topics. Jeder Subscriber
erhält eine eigene bounded Queue mit **Drop-Oldest**-Semantik: langsame
Consumer (z. B. UI-Clients) können den latenzkritischen Hot Path niemals
ausbremsen — statt Backpressure wird das älteste Event verworfen.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, AsyncIterator

log = logging.getLogger(__name__)


class Subscription:
    """Ein Subscriber-Handle mit eigener bounded Queue (Drop-Oldest)."""

    def __init__(self, topic: str, maxsize: int) -> None:
        self.topic = topic
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0

    def _put(self, item: Any) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            # Drop-Oldest: ältestes Element entfernen, neues einreihen.
            try:
                self._queue.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:  # pragma: no cover
                pass
            try:
                self._queue.put_nowait(item)
            except asyncio.QueueFull:  # pragma: no cover
                pass

    async def get(self) -> Any:
        return await self._queue.get()

    async def __aiter__(self) -> AsyncIterator[Any]:
        while True:
            yield await self._queue.get()


class EventBus:
    """Zentraler async Pub/Sub-Bus."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Subscription]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def subscribe(self, topic: str, maxsize: int = 8) -> Subscription:
        """Registriert einen Subscriber für ``topic``."""
        sub = Subscription(topic, maxsize)
        self._subs[topic].append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        subs = self._subs.get(sub.topic)
        if subs and sub in subs:
            subs.remove(sub)

    def publish(self, topic: str, item: Any) -> None:
        """Veröffentlicht ``item`` auf ``topic`` (non-blocking, fire-and-forget)."""
        for sub in self._subs.get(topic, ()):  # tolerant gegen 0 Subscriber
            sub._put(item)

    def subscriber_count(self, topic: str) -> int:
        return len(self._subs.get(topic, ()))
