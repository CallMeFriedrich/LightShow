"""ArtNet/DMX-Output (UDP, ArtDMX-Pakete).

Sendet den gerenderten RGB-Frame als DMX-Kanäle: 3 Kanäle je Pixel, 512 Kanäle
(=170 Pixel) je Universe; größere Strips verteilen sich auf fortlaufende
Universes. Verbindungslos → fehlertolerant. Für Nebel/Laser/Dimmer später über
ein Kanal-Mapping erweiterbar (siehe ARCHITECTURE §5.1).
"""
from __future__ import annotations

import logging
import socket

import numpy as np

from .base import OutputDevice

log = logging.getLogger(__name__)

_ARTNET_PORT = 6454
_CH_PER_UNIVERSE = 510  # durch 3 teilbar (170 Pixel)


def _artdmx(universe: int, data: bytes, seq: int) -> bytes:
    hdr = bytearray(b"Art-Net\x00")
    hdr += (0x5000).to_bytes(2, "little")   # OpCode ArtDMX
    hdr += (14).to_bytes(2, "big")          # Protokollversion
    hdr += bytes([seq & 0xFF, 0])           # Sequence, Physical
    hdr += bytes([universe & 0xFF, (universe >> 8) & 0xFF])  # SubUni, Net
    hdr += len(data).to_bytes(2, "big")     # Length
    return bytes(hdr) + data


class ArtnetOutput(OutputDevice):
    def __init__(self, device_id: str, name: str, host: str, pixels: int,
                 port: int = _ARTNET_PORT, universe: int = 0, **kw) -> None:
        super().__init__(device_id, name, pixels, **kw)
        self.host = host
        self.port = port
        self.universe = universe
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        self._seq = 0

    async def send(self, rgb: np.ndarray) -> None:
        data = np.ascontiguousarray(rgb, dtype=np.uint8).reshape(-1).tobytes()
        uni = self.universe
        for off in range(0, len(data), _CH_PER_UNIVERSE):
            chunk = data[off : off + _CH_PER_UNIVERSE]
            self._seq = (self._seq % 255) + 1
            self._sock.sendto(_artdmx(uni, chunk, self._seq), (self.host, self.port))
            uni += 1

    async def close(self) -> None:
        self._sock.close()
