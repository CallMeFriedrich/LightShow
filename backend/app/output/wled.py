"""WLED-Output via DDP (Distributed Display Protocol, UDP).

DDP ist verbindungslos → ideal für Fehlertoleranz: Paketverlust ist unkritisch
und ``sendto`` blockiert praktisch nicht. WLED aktiviert DDP automatisch, sobald
Pakete auf UDP-Port 4048 eintreffen (Realtime-Override).

Pro Frame werden die Pixel in Chunks zu max. 480 RGB-Pixeln gesendet; das
Push-Flag sitzt nur im letzten Chunk.
"""
from __future__ import annotations

import logging
import socket

import numpy as np

from .base import OutputDevice

log = logging.getLogger(__name__)

_DDP_PORT = 4048
_VER1 = 0x40
_PUSH = 0x01
_MAX_PIXELS_PER_PACKET = 480  # 480 * 3 = 1440 Byte Nutzlast


class WledOutput(OutputDevice):
    def __init__(self, device_id: str, name: str, host: str, pixels: int, port: int = _DDP_PORT, **kw) -> None:
        super().__init__(device_id, name, pixels, **kw)
        self.host = host
        self.port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        self._seq = 0

    async def send(self, rgb: np.ndarray) -> None:
        flat = np.ascontiguousarray(rgb, dtype=np.uint8).reshape(-1, 3)
        total = flat.shape[0]
        offset_px = 0
        while offset_px < total:
            chunk = flat[offset_px : offset_px + _MAX_PIXELS_PER_PACKET]
            is_last = (offset_px + chunk.shape[0]) >= total
            self._seq = (self._seq % 15) + 1
            self._sock.sendto(
                self._make_packet(chunk, offset_px * 3, is_last),
                (self.host, self.port),
            )
            offset_px += chunk.shape[0]

    def _make_packet(self, chunk: np.ndarray, byte_offset: int, push: bool) -> bytes:
        data = chunk.tobytes()
        header = bytearray(10)
        header[0] = _VER1 | (_PUSH if push else 0)
        header[1] = self._seq
        header[2] = 0x00  # data type: raw RGB (WLED liest roh)
        header[3] = 0x01  # destination / output id
        header[4:8] = byte_offset.to_bytes(4, "big")
        header[8:10] = len(data).to_bytes(2, "big")
        return bytes(header) + data

    async def close(self) -> None:
        self._sock.close()
