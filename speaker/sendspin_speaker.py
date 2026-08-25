"""SendSpin-Speaker für Windows/Linux — gibt den SendSpin-Stream auf die Soundkarte aus.

Gegenstück zu LightShow: registriert sich als SendSpin-**Player** (per mDNS, wie
LightShow), empfängt den dekodierten PCM-Stream von Music Assistant und spielt ihn
über die Soundkarte ab. Damit lässt sich der Rechner mit LightShow in eine
SendSpin-Sync-Gruppe legen → Ton + Licht synchron.

WICHTIG: Nutzt bewusst **aiosendspin 6.0.5** — dieselbe Version, die Music Assistant
2.9.x bündelt (ohne Verschlüsselung). Die neue "Sendspin for Windows"-App (SDK 9.x)
ist damit inkompatibel; dieser Client passt.

Start:  python sendspin_speaker.py "Laptop"
Stopp:  Strg+C
"""
from __future__ import annotations

import asyncio
import contextlib
import socket
import sys
import threading
import uuid
from pathlib import Path

import numpy as np
import sounddevice as sd

from aiosendspin.client import ClientListener, SendspinClient
from aiosendspin.models.player import ClientHelloPlayerSupport, SupportedAudioFormat
from aiosendspin.models.types import AudioCodec, PlayerCommand, PlayerStateType, Roles

_PORT = 8928                    # mDNS/Listen-Port (Standard für SendSpin-Clients)
_MAX_BUFFER_S = 0.5            # Audio-Puffer deckeln (Latenz/Sync)


class SendspinSpeaker:
    def __init__(self, name: str, device: int | None = None) -> None:
        self.name = name
        self.device = device
        self._id = self._load_id()
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stream: sd.OutputStream | None = None
        self._sr = 48000
        self._ch = 2
        self._client: SendspinClient | None = None
        self._vol = 1.0        # 0..1, von MASS gesteuert
        self._muted = False
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── stabile Client-ID (damit MASS uns wiedererkennt) ──
    def _load_id(self) -> str:
        p = Path.home() / ".sendspin_speaker_id"
        if p.is_file():
            cid = p.read_text().strip()
            if cid:
                return cid
        cid = f"speaker-{uuid.uuid4().hex[:12]}"
        p.write_text(cid)
        return cid

    def _player_support(self) -> ClientHelloPlayerSupport:
        # PCM anbieten → MASS sendet rohes PCM (kein Decode nötig).
        return ClientHelloPlayerSupport(
            supported_formats=[
                SupportedAudioFormat(codec=AudioCodec.PCM, channels=2, sample_rate=48000, bit_depth=16),
            ],
            buffer_capacity=2_000_000,
            supported_commands=[PlayerCommand.VOLUME, PlayerCommand.MUTE],
        )

    # ── Audio-Ausgabe (PortAudio/sounddevice) ──
    def _ensure_stream(self, sr: int, ch: int) -> None:
        if self._stream is not None and self._sr == sr and self._ch == ch:
            return
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        self._sr, self._ch = sr, ch
        self._stream = sd.OutputStream(
            samplerate=sr, channels=ch, dtype="int16",
            blocksize=int(sr * 0.01), device=self.device, callback=self._sd_callback,
        )
        self._stream.start()

    def _sd_callback(self, outdata, frames, time_info, status) -> None:
        need = frames * self._ch * 2
        with self._lock:
            take = bytes(self._buf[:need])
            del self._buf[:need]
        arr = np.frombuffer(take, dtype="<i2")
        if arr.size < frames * self._ch:  # Unterlauf → mit Stille auffüllen
            arr = np.concatenate([arr, np.zeros(frames * self._ch - arr.size, dtype=np.int16)])
        gain = 0.0 if self._muted else self._vol
        if gain != 1.0:  # Lautstärke von MASS anwenden
            arr = (arr.astype(np.float32) * gain).astype(np.int16)
        outdata[:] = arr.reshape(frames, self._ch)

    def _on_audio(self, timestamp_us: int, pcm: bytes, fmt) -> None:
        self._ensure_stream(fmt.pcm_format.sample_rate, fmt.pcm_format.channels)
        max_bytes = int(_MAX_BUFFER_S * self._sr * self._ch * 2)
        with self._lock:
            self._buf += pcm
            if len(self._buf) > max_bytes:  # zu viel Rückstand → auf max kürzen
                del self._buf[: len(self._buf) - max_bytes]

    # ── SendSpin-Client ──
    def _build_client(self) -> SendspinClient:
        client = SendspinClient(
            self._id, self.name, roles=[Roles.PLAYER], player_support=self._player_support(),
            initial_volume=int(self._vol * 100), initial_muted=self._muted,
        )
        client.add_audio_chunk_listener(self._on_audio)
        client.add_server_command_listener(self._on_command)
        self._client = client
        return client

    def _on_command(self, payload) -> None:
        """Volume/Mute-Kommando von MASS → auf die Ausgabe anwenden + zurückmelden."""
        p = getattr(payload, "player", None)
        if p is None:
            return
        cmd = getattr(p, "command", None)
        if cmd == PlayerCommand.VOLUME and p.volume is not None:
            self._vol = max(0.0, min(1.0, p.volume / 100.0))
        elif cmd == PlayerCommand.MUTE and p.mute is not None:
            self._muted = bool(p.mute)
        else:
            return
        if self._loop is not None:  # aktuellen Stand an MASS zurückmelden
            self._loop.create_task(self._reflect_state())

    async def _reflect_state(self) -> None:
        c = self._client
        if c is not None and c.connected:
            with contextlib.suppress(Exception):
                await c.send_player_state(
                    state=PlayerStateType.SYNCHRONIZED,
                    volume=int(self._vol * 100), muted=self._muted,
                )

    def _on_connection(self, client: SendspinClient):
        async def handler(ws) -> None:
            closed = asyncio.Event()
            remove = client.add_disconnect_listener(closed.set)
            print("[sendspin-speaker] Music Assistant verbunden — spiele bei Wiedergabe.")
            try:
                # attach_websocket blockiert NICHT → Verbindung offen halten.
                await client.attach_websocket(ws)
                await closed.wait()
            finally:
                remove()
                with self._lock:
                    self._buf.clear()
                print("[sendspin-speaker] getrennt (wartet auf neue Verbindung).")

        return handler

    async def run(self, connect_host: str | None = None, connect_port: int = 8927) -> None:
        self._loop = asyncio.get_running_loop()
        if connect_host:
            await self._run_connect(connect_host, connect_port)
        else:
            await self._run_listen()

    async def _run_listen(self) -> None:
        """mDNS/Listen-Modus: MASS entdeckt uns und verbindet sich (nur im lokalen LAN)."""
        client = self._build_client()
        # Freien Port suchen (8928 ist evtl. von einer alten SendSpin-App belegt).
        listener = None
        last_err: Exception | None = None
        for port in range(_PORT, _PORT + 12):
            candidate = ClientListener(
                client_id=self._id, on_connection=self._on_connection(client),
                port=port, client_name=self.name,
            )
            try:
                await candidate.start()
                listener = candidate
                break
            except OSError as exc:
                last_err = exc
                with contextlib.suppress(Exception):
                    await candidate.stop()
        if listener is None:
            print("[sendspin-speaker] Kein freier Port 8928–8939. Läuft evtl. noch eine "
                  "alte SendSpin-App? Bitte im Task-Manager beenden.")
            raise last_err  # type: ignore[misc]
        print(f"[sendspin-speaker] '{self.name}' aktiv (mDNS, Port {listener.port}).")
        print("  → In Music Assistant als SendSpin-Gerät sichtbar. Mit LightShow gruppieren und abspielen.")
        print("  → Beenden mit Strg+C.")
        try:
            await asyncio.Event().wait()  # läuft bis Strg+C
        finally:
            await listener.stop()
            await client.disconnect()
            self._close_stream()

    async def _run_connect(self, host: str, port: int) -> None:
        """Connect-Modus: wir wählen MASS aktiv per IP an (VPN-tauglich, nur ausgehend)."""
        url = f"ws://{host}:{port}/sendspin"
        backoff = 1.0
        print(f"[sendspin-speaker] '{self.name}' — Direktverbindung zu {url}")
        print("  → Beenden mit Strg+C.")
        try:
            while True:
                client = self._build_client()
                try:
                    await client.connect(url)
                    print("[sendspin-speaker] Music Assistant verbunden — spiele bei Wiedergabe.")
                    backoff = 1.0
                    closed = asyncio.Event()
                    remove = client.add_disconnect_listener(closed.set)
                    try:
                        await closed.wait()
                    finally:
                        remove()
                    print("[sendspin-speaker] getrennt.")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    print(f"[sendspin-speaker] Verbindung fehlgeschlagen: {exc}")
                finally:
                    with contextlib.suppress(Exception):
                        await client.disconnect()
                    with self._lock:
                        self._buf.clear()
                print(f"[sendspin-speaker] neuer Versuch in {backoff:.0f}s...")
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)
        finally:
            self._close_stream()

    def _close_stream(self) -> None:
        if self._stream is not None:
            with contextlib.suppress(Exception):
                self._stream.stop()
                self._stream.close()
            self._stream = None


def _list_devices() -> None:
    print(sd.query_devices())


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="SendSpin-Speaker für Music Assistant")
    parser.add_argument("name", nargs="?", default=socket.gethostname(),
                        help="Anzeigename des Geräts in Music Assistant")
    parser.add_argument("--connect", "-c", metavar="HOST[:PORT]",
                        help="Direktverbindung zu MASS per IP (für VPN / getrennte Netze). "
                             "Standard-Port 8927. Ohne diese Option: automatische mDNS-Erkennung.")
    parser.add_argument("--device", "-d", type=int, help="Audio-Ausgabegerät (Index, siehe --devices)")
    parser.add_argument("--devices", "-l", action="store_true", help="Audio-Ausgabegeräte auflisten")
    args = parser.parse_args()

    if args.devices:
        _list_devices()
        return

    host: str | None = None
    port = 8927
    if args.connect:
        if ":" in args.connect:
            h, p = args.connect.rsplit(":", 1)
            if p.isdigit():
                host, port = h, int(p)
            else:
                host = args.connect
        else:
            host = args.connect

    speaker = SendspinSpeaker(args.name, args.device)
    try:
        asyncio.run(speaker.run(connect_host=host, connect_port=port))
    except KeyboardInterrupt:
        print("\n[sendspin-speaker] beendet.")


if __name__ == "__main__":
    main()
