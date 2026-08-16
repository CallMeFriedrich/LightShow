"""Netzwerkbasierte Audio-Quellen: Snapcast-Client & roher PCM/TCP-Stream.

Beide liefern rohes **S16LE**-PCM, das hier zu normierten float32-``PCMFrame``s
konvertiert wird. Die Blockgröße entspricht ``audio_block_size`` (pro Kanal).

Snapcast
--------
Music Assistant streamt an eine Snapcast-Player-Gruppe. Auf dem Licht-Host
liest LightShow die PCM-Ausgabe eines ``snapclient``-Subprozesses. Das hält
Beschallung und Lichtsteuerung **phasensynchron**, ohne Audiokabel.

Der ``snapclient`` wird mit dem *file*-Player gestartet, der rohes PCM nach
stdout schreibt. Bricht der Prozess/die Verbindung ab, endet der Generator —
der Task-Supervisor startet die Quelle mit Backoff neu (Reconnect-Logik).
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

import numpy as np

from ..config import Settings
from .models import PCMFrame
from .source import AudioSource

log = logging.getLogger(__name__)

_INT16_SCALE = 1.0 / 32768.0


def _bytes_to_frame(buf: bytes, channels: int, sample_rate: int) -> PCMFrame:
    """S16LE-Bytes → normierter ``PCMFrame`` (float32)."""
    arr = np.frombuffer(buf, dtype="<i2").astype(np.float32) * _INT16_SCALE
    if channels > 1:
        arr = arr.reshape(-1, channels)
    return PCMFrame(samples=arr, sample_rate=sample_rate, channels=channels)


async def _frames_from_reader(
    reader: asyncio.StreamReader,
    *,
    block_size: int,
    channels: int,
    sample_rate: int,
) -> AsyncIterator[PCMFrame]:
    """Liest exakt-große Blöcke aus einem StreamReader und yieldet Frames."""
    bytes_per_block = block_size * channels * 2  # 2 Byte pro S16-Sample
    while True:
        buf = await reader.readexactly(bytes_per_block)
        yield _bytes_to_frame(buf, channels, sample_rate)


class SnapcastSource(AudioSource):
    """PCM aus einem ``snapclient``-Subprozess (file-Player → stdout)."""

    name = "snapcast"

    def __init__(self, settings: Settings) -> None:
        self.s = settings

    async def frames(self) -> AsyncIterator[PCMFrame]:
        # Langform-Flags (--host/--port); der file-Player schreibt rohes PCM nach
        # stdout, --sampleformat resampled auf unser Analyseformat (unabhängig vom
        # Server-Codec, z. B. FLAC). Verifiziert gegen snapclient(1).
        cmd = [
            self.s.snapclient_bin,
            "--host",
            self.s.snapcast_host,
            "--port",
            str(self.s.snapcast_port),
            "--player",
            "file:filename=stdout&mode=w",
            "--sampleformat",
            f"{self.s.audio_sample_rate}:16:{self.s.audio_channels}",
        ]
        log.info("Starte snapclient: %s", " ".join(cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            log.error("snapclient-Binary nicht gefunden (%s) — bitte installieren", self.s.snapclient_bin)
            return
        assert proc.stdout is not None
        try:
            async for frame in _frames_from_reader(
                proc.stdout,
                block_size=self.s.audio_block_size,
                channels=self.s.audio_channels,
                sample_rate=self.s.audio_sample_rate,
            ):
                yield frame
        except asyncio.IncompleteReadError:
            log.warning("snapclient-Stream beendet — Reconnect via Supervisor")
        finally:
            # stderr des snapclient für die Diagnose einsammeln (Prozess i. d. R. beendet).
            if proc.stderr is not None:
                try:
                    err = await asyncio.wait_for(proc.stderr.read(), timeout=1.0)
                    if err:
                        log.warning("snapclient stderr: %s", err.decode(errors="replace").strip()[-600:])
                except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                    pass
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except asyncio.TimeoutError:  # pragma: no cover
                    proc.kill()
            elif proc.returncode != 0:
                log.warning("snapclient exit code: %s", proc.returncode)


class PcmTcpSource(AudioSource):
    """Roher S16LE-PCM-Stream über eine TCP-Verbindung."""

    name = "pcm_tcp"

    def __init__(self, settings: Settings) -> None:
        self.s = settings

    async def frames(self) -> AsyncIterator[PCMFrame]:
        log.info("Verbinde PCM/TCP %s:%s", self.s.pcm_tcp_host, self.s.pcm_tcp_port)
        reader, writer = await asyncio.open_connection(
            self.s.pcm_tcp_host, self.s.pcm_tcp_port
        )
        try:
            async for frame in _frames_from_reader(
                reader,
                block_size=self.s.audio_block_size,
                channels=self.s.audio_channels,
                sample_rate=self.s.audio_sample_rate,
            ):
                yield frame
        except asyncio.IncompleteReadError:
            log.warning("PCM/TCP-Verbindung beendet — Reconnect via Supervisor")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # pragma: no cover
                pass
