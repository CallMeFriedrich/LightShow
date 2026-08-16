"""WebSocket-Hub — Live-State an die UIs, Kommandos zurück.

Ein einziger Broadcast-Task liest den Event-Bus (Analyse, Preview, Status) und
verteilt an alle verbundenen Clients. Der Bus entkoppelt bereits per
Drop-Oldest, sodass langsame Clients den Render-Loop nie ausbremsen.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import WebSocket, WebSocketDisconnect

from ..runtime import AppState

log = logging.getLogger(__name__)


class WsHub:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self._clients: set[WebSocket] = set()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._pump(), name="ws-pump")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        # Initialen Zustand senden.
        await self._safe_send(ws, {"type": "status", "data": self.state.status()})
        try:
            while True:
                msg = await ws.receive_json()
                await self._handle_command(msg)
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            log.debug("WS-Client-Fehler", exc_info=True)
        finally:
            self._clients.discard(ws)

    async def _handle_command(self, msg: dict) -> None:
        """Kommandos vom Client (Config anpassen, Basisfarbe setzen)."""
        action = msg.get("action")
        if action == "set_config":
            self.state.update_config(msg.get("changes", {}))
        elif action == "set_base_hue":
            self.state.show.set_base_hue(float(msg["hue"]))
        elif action == "player":
            await self.state.player_command(msg.get("cmd", ""), msg.get("value"))
        # weitere Kommandos folgen in Slice 3 (Pult, HA-Buttons)

    async def _pump(self) -> None:
        bus = self.state.bus
        sub_analysis = bus.subscribe("audio.analysis", maxsize=4)
        sub_preview = bus.subscribe("render.preview", maxsize=2)
        sub_show = bus.subscribe("show.status", maxsize=4)
        sub_player = bus.subscribe("player.state", maxsize=8)
        sub_status = bus.subscribe("system.status", maxsize=16)

        async def forward(sub, wrap) -> None:
            async for item in sub:
                await self._broadcast(wrap(item))

        await asyncio.gather(
            forward(sub_analysis, lambda a: {"type": "analysis", "data": a.to_dict()}),
            forward(sub_preview, lambda p: {"type": "preview", "data": p}),
            forward(sub_show, lambda s: {"type": "show", "data": s}),
            forward(sub_player, lambda p: {"type": "player", "data": p}),
            forward(sub_status, lambda s: {"type": "task", "data": s}),
        )

    async def _broadcast(self, payload: dict) -> None:
        if not self._clients:
            return
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def _safe_send(self, ws: WebSocket, payload: dict) -> None:
        with contextlib.suppress(Exception):
            await ws.send_json(payload)
