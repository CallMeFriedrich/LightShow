"""SendSpin-Audio-Capture (natives Music-Assistant-Protokoll).

Setzt auf die offizielle Bibliothek ``aiosendspin`` auf. **Wichtig:** Die
Version muss zur MASS-Version passen — MASS 2.9.x bündelt ``aiosendspin 6.0.5``.
In 6.0.5 ist der Client bewusst einfach gehalten (noch **ohne** Noise/Pairing):
``client_id`` ist ein simpler, stabiler String; wir registrieren uns als
**Player** und bekommen dekodierte PCM-Chunks per Callback in die Analyse.

Wir bieten **PCM** an → MASS streamt uns rohes PCM (kein Decode/av nötig).

Zwei Modi:
* ``listen``  — wir werben per mDNS, MASS verbindet sich zu uns (Standard-Discovery,
  funktioniert, wenn der Host direkt im LAN hängt — z. B. Linux-VM, nicht WSL-NAT).
* ``connect`` — wir wählen den Server aktiv an (``ws://host:port/sendspin``).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from pathlib import Path
from typing import AsyncIterator

import numpy as np

from ..config import Settings
from .models import PCMFrame
from .source import AudioSource

log = logging.getLogger(__name__)

_LISTEN_PORT = 8928
_CONNECT_PORT = 8927


class SendSpinSource(AudioSource):
    name = "sendspin"

    def __init__(self, settings: Settings, on_metadata=None) -> None:
        self.s = settings
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._id_path = Path(settings.data_dir) / "sendspin_id"
        self._chunks = 0
        self._on_metadata = on_metadata  # Callback(dict) für Player-Metadaten
        self._client = None              # aktueller SendSpin-Client (für Steuerung)

    # ── stabile client_id (persistiert, damit MASS uns wiedererkennt) ──
    def _client_id(self) -> str:
        if self._id_path.is_file():
            cid = self._id_path.read_text().strip()
            if cid:
                return cid
        cid = f"lightshow-{uuid.uuid4().hex[:12]}"
        self._id_path.parent.mkdir(parents=True, exist_ok=True)
        self._id_path.write_text(cid)
        return cid

    def _player_support(self):
        from aiosendspin.models.player import ClientHelloPlayerSupport, SupportedAudioFormat
        from aiosendspin.models.types import AudioCodec, PlayerCommand

        sr, ch = self.s.audio_sample_rate, self.s.audio_channels
        # Nur PCM anbieten → MASS transkodiert serverseitig, wir bekommen rohes PCM.
        return ClientHelloPlayerSupport(
            supported_formats=[
                SupportedAudioFormat(codec=AudioCodec.PCM, channels=ch, sample_rate=sr, bit_depth=16),
            ],
            buffer_capacity=2_000_000,
            # Volume/Mute anbieten, damit der (Gruppen-)Lautstärkeregler in MASS
            # aktiv ist. LightShow gibt keinen Ton aus → wird ignoriert.
            supported_commands=[PlayerCommand.VOLUME, PlayerCommand.MUTE],
        )

    def _on_audio(self, timestamp_us: int, pcm: bytes, fmt) -> None:
        """SDK-Callback (Event-Loop): dekodiertes PCM einreihen (Drop-Oldest)."""
        self._chunks += 1
        if self._chunks == 1:
            log.info("SendSpin Audio-Stream aktiv: %d Bytes %dHz/%dch/%dbit",
                     len(pcm), fmt.pcm_format.sample_rate,
                     fmt.pcm_format.channels, fmt.pcm_format.bit_depth)
        item = (pcm, fmt.pcm_format.sample_rate, fmt.pcm_format.channels, fmt.pcm_format.bit_depth)
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            with contextlib.suppress(Exception):
                self._queue.get_nowait()
                self._queue.put_nowait(item)

    def _on_disconnect(self) -> None:
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(None)  # Sentinel → frames() endet → Supervisor-Restart

    def _build_client(self):
        from aiosendspin.client import SendspinClient
        from aiosendspin.models.types import Roles

        # PLAYER (Audio) + METADATA (Titel/Cover) + CONTROLLER (Play/Pause/Skip).
        client = SendspinClient(
            self._client_id(),
            self.s.sendspin_name,
            roles=[Roles.PLAYER, Roles.METADATA, Roles.CONTROLLER],
            player_support=self._player_support(),
        )
        client.add_audio_chunk_listener(self._on_audio)
        client.add_disconnect_listener(self._on_disconnect)
        client.add_metadata_listener(self._on_metadata_msg)
        client.add_group_update_listener(self._on_group_msg)
        self._client = client
        return client

    async def command(self, action: str, value: float | None = None) -> bool:
        """Playback-Steuerung über SendSpin (Controller-Rolle). True bei Erfolg."""
        from aiosendspin.models.types import MediaCommand

        client = self._client
        if client is None or not client.connected:
            return False
        if action == "volume" and value is not None:
            await client.send_group_command(MediaCommand.VOLUME, volume=int(max(0.0, min(1.0, value)) * 100))
            return True
        mapping = {
            "play": MediaCommand.PLAY, "pause": MediaCommand.PAUSE,
            "next": MediaCommand.NEXT, "previous": MediaCommand.PREVIOUS,
        }
        cmd = mapping.get(action)
        if cmd is None:
            return False
        await client.send_group_command(cmd)
        return True

    # ── Metadaten → Callback (Titel/Cover/Playback-State) ──
    def _on_metadata_msg(self, payload) -> None:
        meta = getattr(payload, "metadata", None)
        if meta is None or self._on_metadata is None:
            return
        out: dict = {"online": True}
        for src, dst in (("title", "title"), ("artist", "artist"), ("album", "album")):
            val = getattr(meta, src, None)
            if isinstance(val, str):
                out[dst] = val
        art = getattr(meta, "artwork_url", None)
        if isinstance(art, str):
            out["image_url"] = art
        prog = getattr(meta, "progress", None)
        if prog is not None and hasattr(prog, "track_progress"):
            out["elapsed"] = prog.track_progress / 1000.0
            out["duration"] = prog.track_duration / 1000.0
            out["state"] = "playing" if getattr(prog, "playback_speed", 0) > 0 else "paused"
        self._safe_meta(out)

    def _on_group_msg(self, payload) -> None:
        if self._on_metadata is None:
            return
        state = getattr(payload, "playback_state", None)
        if state is not None:
            name = getattr(state, "value", str(state))
            self._safe_meta({"online": True, "state": "idle" if name == "stopped" else name})

    def _safe_meta(self, out: dict) -> None:
        try:
            self._on_metadata(out)
        except Exception:  # noqa: BLE001
            log.debug("on_metadata-Callback-Fehler", exc_info=True)

    async def frames(self) -> AsyncIterator[PCMFrame]:
        client = self._build_client()
        try:
            stopper = await self._start(client)
        except Exception as exc:  # noqa: BLE001 — sauber statt Riesen-Traceback
            log.warning("SendSpin-Verbindung fehlgeschlagen (%s) — Reconnect via Supervisor", exc)
            with contextlib.suppress(Exception):
                await client.disconnect()
            return
        log.info("SendSpin-Client aktiv (mode=%s, id=%s)", self.s.sendspin_mode, self._client_id())
        listen = self.s.sendspin_mode == "listen"
        try:
            while True:
                item = await self._queue.get()
                if item is None:
                    # Verbindung zu MASS zu. Im listen-Modus bleibt der Listener
                    # aktiv (MASS macht Discovery-Probes + verbindet zum Streamen neu).
                    if listen:
                        continue
                    log.warning("SendSpin-Verbindung beendet — Reconnect via Supervisor")
                    break
                frame = self._to_frame(item)
                if frame is not None:
                    yield frame
        finally:
            await stopper()

    async def _start(self, client):
        """Startet listen- oder connect-Modus; gibt eine Stop-Coroutine zurück."""
        if self.s.sendspin_mode == "connect":
            host = self.s.sendspin_host or self.s.snapcast_host
            port = self.s.sendspin_port or _CONNECT_PORT
            url = f"ws://{host}:{port}/sendspin"
            log.info("SendSpin verbinde aktiv: %s", url)
            await client.connect(url)

            async def stop() -> None:
                await client.disconnect()

            return stop

        from aiosendspin.client import ClientListener

        port = self.s.sendspin_port or _LISTEN_PORT

        async def on_conn(ws) -> None:
            # WICHTIG: attach_websocket() blockiert NICHT — der Handler muss die
            # Verbindung offen halten, bis sie schließt. Sonst schließt aiohttp den
            # WebSocket sofort und MASS zeigt den Player als „nicht verfügbar".
            closed = asyncio.Event()
            remove = client.add_disconnect_listener(closed.set)
            try:
                await client.attach_websocket(ws)
                await closed.wait()
            finally:
                remove()

        listener = ClientListener(
            client_id=self._client_id(),
            on_connection=on_conn,
            port=port,
            client_name=self.s.sendspin_name,
        )
        await listener.start()
        log.info("SendSpin lauscht (mDNS) auf Port %d — warte auf MASS-Verbindung", port)

        async def stop() -> None:
            await listener.stop()
            await client.disconnect()

        return stop

    def _to_frame(self, item) -> PCMFrame | None:
        pcm, sr, ch, bit_depth = item
        if bit_depth == 16:
            arr = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        elif bit_depth == 32:
            arr = np.frombuffer(pcm, dtype="<i4").astype(np.float32) / 2147483648.0
        else:
            log.warning("SendSpin: unerwartete bit_depth=%s — Chunk verworfen", bit_depth)
            return None
        if ch > 1:
            arr = arr.reshape(-1, ch)
        return PCMFrame(samples=arr, sample_rate=sr, channels=ch)
