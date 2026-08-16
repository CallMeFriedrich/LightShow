"""Music-Assistant-Client (WebSocket).

Verbindet sich mit dem Music-Assistant-Server, hält den Zustand des aktiven
Players (Track-Metadaten, Cover, elapsed) aktuell und erlaubt Steuerung
(Play/Pause/Skip/Volume). **Autonome Reconnect-Logik** mit Backoff; fällt MASS
aus, geht der Client in den **Degraded-Mode** (`online=False`) — die Licht-Engine
läuft unbeeinflusst weiter.

Hinweis: Die Kommando-/Feldnamen orientieren sich an der Music-Assistant-2.x-
WebSocket-API. Alles wird **defensiv** geparst (`.get(...)`), sodass kleinere
Schema-Unterschiede zwischen MASS-Versionen den Betrieb nicht brechen. Zustand
wird zusätzlich **gepollt** (nicht nur eventgetrieben) → robust über Versionen.
"""
from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
from typing import Awaitable, Callable

import websockets

from .models import PlayerState, Track

log = logging.getLogger(__name__)

StateCallback = Callable[[PlayerState], Awaitable[None] | None]

# ── Kommando-Namen (MASS 2.x) ───────────────────────────────────────
_CMD_PLAYERS_ALL = "players/all"
_CMD_QUEUE_GET = "player_queues/get"
_CMD_PLAY = "players/cmd/play"
_CMD_PAUSE = "players/cmd/pause"
_CMD_PLAY_PAUSE = "players/cmd/play_pause"
_CMD_NEXT = "players/cmd/next"
_CMD_PREVIOUS = "players/cmd/previous"
_CMD_VOLUME = "players/cmd/volume_set"


def _ws_url(mass_url: str) -> str:
    """http(s)://host:port → ws(s)://host:port/ws."""
    u = mass_url.rstrip("/")
    if u.startswith("https://"):
        return "wss://" + u[len("https://"):] + "/ws"
    if u.startswith("http://"):
        return "ws://" + u[len("http://"):] + "/ws"
    if u.startswith("ws://") or u.startswith("wss://"):
        return u if u.endswith("/ws") else u + "/ws"
    return "ws://" + u + "/ws"


def _first_image(media: dict) -> str:
    """Extrahiert eine Cover-URL aus verschiedenen möglichen Feldern."""
    if not isinstance(media, dict):
        return ""
    if media.get("image_url"):
        return str(media["image_url"])
    meta = media.get("metadata") or {}
    images = meta.get("images") or media.get("images") or []
    if images:
        img = images[0]
        if isinstance(img, dict):
            return str(img.get("path") or img.get("url") or "")
        return str(img)
    return ""


def _artist_name(media: dict) -> str:
    artists = media.get("artists") or []
    if artists:
        a = artists[0]
        return str(a.get("name") if isinstance(a, dict) else a)
    return str(media.get("artist") or "")


def parse_track(current_item: dict) -> Track:
    """MASS current_item/media_item-Dict → Track (defensiv)."""
    media = current_item.get("media_item") or current_item.get("current_media") or current_item
    album = media.get("album") or {}
    return Track(
        id=str(media.get("uri") or media.get("item_id") or media.get("id") or ""),
        title=str(media.get("name") or media.get("title") or ""),
        artist=_artist_name(media),
        album=str(album.get("name") if isinstance(album, dict) else album or ""),
        image_url=_first_image(media),
        duration=float(current_item.get("duration") or media.get("duration") or 0.0),
    )


def parse_state(player: dict, queue: dict | None) -> PlayerState:
    """MASS player- (+ queue-)Dict → PlayerState (defensiv)."""
    st = PlayerState(
        online=True,
        player_id=str(player.get("player_id") or ""),
        player_name=str(player.get("display_name") or player.get("name") or ""),
        state=str(player.get("state") or "idle").lower(),
        volume=float(player.get("volume_level") or 0) / 100.0,
    )
    q = queue or {}
    st.elapsed = float(q.get("elapsed_time") or player.get("elapsed_time") or 0.0)
    current = q.get("current_item") or player.get("current_media") or {}
    if current:
        st.track = parse_track(current)
    return st


class MassClient:
    def __init__(self, mass_url: str, player_id: str = "", on_state: StateCallback | None = None) -> None:
        self.url = _ws_url(mass_url)
        self.preferred_player = player_id
        self.on_state = on_state
        self.state = PlayerState(online=False)
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}

    # ── Supervised-Task: verbindet und pollt, self-healing ──
    async def run(self) -> None:
        backoff = 1.0
        warned = False
        while True:
            try:
                async with websockets.connect(self.url, max_size=8 * 2**20) as ws:
                    self._ws = ws
                    await self._read_handshake(ws)
                    log.info("Music Assistant verbunden: %s", self.url)
                    warned = False
                    backoff = 1.0
                    await asyncio.gather(self._reader(ws), self._poller())
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                # Erste Meldung als WARNING (mit Hinweis), danach ruhig auf DEBUG.
                if not warned:
                    warned = True
                    hint = ""
                    if "404" in str(exc):
                        hint = (" — 404: prüfe LIGHTSHOW_MASS_URL (MASS-Server-Root, "
                                "Standard-Port 8095; WS-Pfad /ws wird automatisch angehängt)")
                    log.warning("MASS nicht verbunden (%s)%s — versuche weiter (Reconnect)", exc, hint)
                else:
                    log.debug("MASS Reconnect-Versuch fehlgeschlagen (%s)", exc)
            finally:
                self._ws = None
                self._fail_pending()
                if self.state.online:
                    self.state = PlayerState(online=False)
                    await self._emit()
            await asyncio.sleep(backoff)
            backoff = min(30.0, backoff * 2)

    async def _read_handshake(self, ws) -> None:
        # MASS sendet initial server_info (ohne message_id).
        with contextlib.suppress(asyncio.TimeoutError):
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            log.debug("MASS server_info: %s", raw[:200])

    async def _reader(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mid = msg.get("message_id")
            if mid is not None and mid in self._pending:
                fut = self._pending.pop(mid)
                if not fut.done():
                    fut.set_result(msg.get("result"))

    async def _poller(self) -> None:
        while True:
            try:
                await self._refresh()
            except Exception:  # noqa: BLE001
                log.debug("MASS Poll-Fehler", exc_info=True)
            await asyncio.sleep(1.0)

    async def _refresh(self) -> None:
        players = await self._request(_CMD_PLAYERS_ALL) or []
        player = self._pick_player(players)
        if not player:
            if self.state.online and self.state.player_id:
                self.state = PlayerState(online=True)
                await self._emit()
            return
        pid = player.get("player_id")
        queue = None
        with contextlib.suppress(Exception):
            queue = await self._request(_CMD_QUEUE_GET, {"queue_id": pid})
        self.state = parse_state(player, queue)
        await self._emit()

    def _pick_player(self, players: list) -> dict | None:
        if not isinstance(players, list) or not players:
            return None
        if self.preferred_player:
            for p in players:
                if p.get("player_id") == self.preferred_player:
                    return p
        # sonst: erster spielender, sonst erster verfügbarer
        for p in players:
            if str(p.get("state", "")).lower() == "playing":
                return p
        return players[0]

    # ── Request/Response ──
    async def _request(self, command: str, args: dict | None = None):
        ws = self._ws
        if ws is None:
            return None
        mid = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await ws.send(json.dumps({"message_id": mid, "command": command, "args": args or {}}))
        try:
            return await asyncio.wait_for(fut, timeout=5)
        except asyncio.TimeoutError:
            self._pending.pop(mid, None)
            return None

    def _fail_pending(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def _emit(self) -> None:
        if self.on_state:
            res = self.on_state(self.state)
            if asyncio.iscoroutine(res):
                await res

    # ── Steuerung ──
    async def _cmd_active(self, command: str, extra: dict | None = None) -> bool:
        pid = self.state.player_id
        if not pid:
            return False
        args = {"player_id": pid}
        if extra:
            args.update(extra)
        await self._request(command, args)
        return True

    async def play(self) -> bool:
        return await self._cmd_active(_CMD_PLAY)

    async def pause(self) -> bool:
        return await self._cmd_active(_CMD_PAUSE)

    async def play_pause(self) -> bool:
        return await self._cmd_active(_CMD_PLAY_PAUSE)

    async def next(self) -> bool:
        return await self._cmd_active(_CMD_NEXT)

    async def previous(self) -> bool:
        return await self._cmd_active(_CMD_PREVIOUS)

    async def set_volume(self, level: float) -> bool:
        return await self._cmd_active(_CMD_VOLUME, {"volume_level": int(max(0, min(1, level)) * 100)})
