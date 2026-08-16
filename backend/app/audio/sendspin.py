"""SendSpin-Audio-Capture (natives Music-Assistant-Protokoll).

Setzt auf die offizielle Bibliothek ``aiosendspin`` auf, die den kompletten
schweren Teil erledigt: Noise-``KKpsk2``-Handshake, WebSocket-Framing,
Clock-Sync und **Codec-Decoding** (FLAC/PCM → rohes PCM). Wir registrieren uns
als **Player** und erhalten dekodierte PCM-Chunks per Callback, die wir in die
Analyse-Pipeline schieben.

Unpaired-Betrieb: ``InMemoryClientPairingStore`` liefert die Sentinel-PSK, ein
Client mit ``trust_level='none'`` darf die ``playback``-Aktivität und damit den
Audio-Stream empfangen — **kein PIN-Pairing nötig**.

Zwei Modi:
* ``listen``  — wir werben per mDNS (`_sendspin._tcp.local.`), MASS verbindet sich
  zu uns (Standard-Discovery, wie bei anderen SendSpin-Playern).
* ``connect`` — wir wählen den Server aktiv an (``ws://host:port/sendspin``).

Hinweis: v0.1, nur gegen die Bibliothek getestet (kein Live-Server hier). Viel
Logging zur Iteration an der echten MASS-Instanz.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
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

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._key_path = Path(settings.data_dir) / "sendspin_key"

    # ── Identity-Persistenz (rohe 32-Byte X25519-Privatkey-Datei) ──
    def _load_identity(self):
        from aiosendspin.noise.keys import Identity

        if self._key_path.is_file():
            try:
                return Identity.from_private_bytes(self._key_path.read_bytes())
            except Exception:  # noqa: BLE001
                log.warning("SendSpin-Key unlesbar — erzeuge neuen")
        ident = Identity.generate()
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        self._key_path.write_bytes(ident.private_bytes)
        return ident

    def _player_support(self):
        from aiosendspin.models.player import ClientHelloPlayerSupport, SupportedAudioFormat
        from aiosendspin.models.types import AudioCodec

        sr, ch = self.s.audio_sample_rate, self.s.audio_channels
        # PCM bevorzugt (kein Decode nötig), FLAC als Fallback.
        formats = [
            SupportedAudioFormat(codec=AudioCodec.PCM, channels=ch, sample_rate=sr, bit_depth=16),
            SupportedAudioFormat(codec=AudioCodec.FLAC, channels=ch, sample_rate=sr, bit_depth=16),
        ]
        return ClientHelloPlayerSupport(
            supported_formats=formats,
            buffer_capacity=2_000_000,
            supported_commands=[],
        )

    def _on_audio(self, timestamp_us: int, pcm: bytes, fmt) -> None:
        """SDK-Callback (läuft im Event-Loop): dekodiertes PCM einreihen."""
        try:
            self._queue.put_nowait((pcm, fmt.pcm_format.sample_rate,
                                    fmt.pcm_format.channels, fmt.pcm_format.bit_depth))
        except asyncio.QueueFull:
            try:  # Drop-Oldest, damit die Analyse nie blockiert
                self._queue.get_nowait()
                self._queue.put_nowait((pcm, fmt.pcm_format.sample_rate,
                                        fmt.pcm_format.channels, fmt.pcm_format.bit_depth))
            except Exception:  # noqa: BLE001
                pass

    def _on_disconnect(self) -> None:
        try:
            self._queue.put_nowait(None)  # Sentinel → frames() endet → Supervisor-Restart
        except asyncio.QueueFull:
            pass

    def _build_client(self):
        from aiosendspin.client import SendspinClient
        from aiosendspin.models.types import Roles
        from aiosendspin.noise.session import NoiseCipherSuite
        from aiosendspin.noise.trust_store import InMemoryClientPairingStore

        identity = self._load_identity()
        client = SendspinClient(
            identity,
            self.s.sendspin_name,
            roles=[Roles.PLAYER],
            pairing_store=InMemoryClientPairingStore(),
            player_support=self._player_support(),
            cipher_suite=NoiseCipherSuite.CHACHAPOLY,
        )
        client.add_audio_chunk_listener(self._on_audio)
        client.add_disconnect_listener(self._on_disconnect)
        return client

    async def frames(self) -> AsyncIterator[PCMFrame]:
        client = self._build_client()
        try:
            stopper = await self._start(client)
        except Exception as exc:  # noqa: BLE001 — sauber statt Riesen-Traceback
            log.warning("SendSpin-Verbindung fehlgeschlagen (%s) — Reconnect via Supervisor", exc)
            with contextlib.suppress(Exception):
                await client.disconnect()  # schließt die aiohttp-Session
            return
        log.info("SendSpin-Client aktiv (mode=%s, id=%s)", self.s.sendspin_mode, client.identity.peer_id[:12])
        try:
            while True:
                item = await self._queue.get()
                if item is None:
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

        # listen-Modus: mDNS-Advertising, MASS verbindet sich zu uns.
        from aiosendspin.client import ClientListener

        port = self.s.sendspin_port or _LISTEN_PORT

        async def on_conn(ws) -> None:
            await client.attach_websocket(ws)

        listener = ClientListener(
            client_id=client.identity.peer_id,
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
