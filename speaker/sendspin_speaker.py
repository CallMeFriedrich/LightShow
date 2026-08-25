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
from aiosendspin.models.types import AudioCodec, Roles

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
            supported_commands=[],
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
        )
        client.add_audio_chunk_listener(self._on_audio)
        self._client = client
        return client

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

    async def run(self) -> None:
        client = self._build_client()
        # Freien Port suchen (8928 ist evtl. von einer alten SendSpin-App belegt).
        # MASS liest den tatsächlichen Port per mDNS — jeder Port funktioniert.
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
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()


def _list_devices() -> None:
    print(sd.query_devices())


def main() -> None:
    args = [a for a in sys.argv[1:]]
    if args and args[0] in ("--devices", "-l"):
        _list_devices()
        return
    name = args[0] if args else socket.gethostname()
    device = None
    if len(args) > 1:  # optionaler Ausgabe-Device-Index
        try:
            device = int(args[1])
        except ValueError:
            pass
    speaker = SendspinSpeaker(name, device)
    try:
        asyncio.run(speaker.run())
    except KeyboardInterrupt:
        print("\n[sendspin-speaker] beendet.")


if __name__ == "__main__":
    main()
