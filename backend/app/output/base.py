"""Output-Abstraktion: FrameBuffer, OutputDevice-ABC und OutputRouter.

Die ShowEngine rendert eine logische ``FrameBuffer``-Canvas. Der Router
mappt sie auf 1..n konkrete Geräte (WLED/virtuell/ArtNet) mit je eigener
Pixelzahl. Ein ausgefallenes Gerät wird übersprungen — die übrigen laufen.
"""
from __future__ import annotations

import abc
import logging

import numpy as np

log = logging.getLogger(__name__)


class FrameBuffer:
    """RGB-Pixelpuffer (uint8, Form (pixels, 3)) + Master-Helligkeit."""

    def __init__(self, pixels: int) -> None:
        self.pixels = pixels
        self.data = np.zeros((pixels, 3), dtype=np.uint8)
        self.brightness = 1.0  # 0..1, wird beim Senden angewendet

    def clear(self) -> None:
        self.data[:] = 0

    def resampled(self, target_pixels: int) -> np.ndarray:
        """Skaliert die Canvas per Nearest-Neighbor auf ``target_pixels``."""
        if target_pixels == self.pixels:
            out = self.data
        else:
            idx = (np.arange(target_pixels) * self.pixels // max(1, target_pixels))
            out = self.data[np.clip(idx, 0, self.pixels - 1)]
        if self.brightness < 0.999:
            out = (out.astype(np.float32) * self.brightness).astype(np.uint8)
        return np.ascontiguousarray(out, dtype=np.uint8)


class OutputDevice(abc.ABC):
    """Abstraktes Ausgabegerät."""

    #: True für physische Fixtures (WLED/ArtNet), auf die Strobe-Alternation wirkt.
    is_fixture: bool = True

    def __init__(self, device_id: str, name: str, pixels: int) -> None:
        self.id = device_id
        self.name = name
        self.pixels = pixels
        self.online = True

    @abc.abstractmethod
    async def send(self, rgb: np.ndarray) -> None:
        """Sendet ein (pixels, 3)-uint8-Array an das Gerät."""

    async def close(self) -> None:  # pragma: no cover — optional
        return None


class OutputRouter:
    """Verteilt eine gerenderte Canvas an alle registrierten Geräte."""

    def __init__(self) -> None:
        self._devices: dict[str, OutputDevice] = {}

    def add(self, device: OutputDevice) -> None:
        self._devices[device.id] = device

    def remove(self, device_id: str) -> None:
        self._devices.pop(device_id, None)

    @property
    def devices(self) -> list[OutputDevice]:
        return list(self._devices.values())

    async def broadcast(self, frame: FrameBuffer, fixture_gains: list[float] | None = None) -> None:
        """Sendet den Frame an alle Geräte — Fehler isoliert pro Gerät.

        ``fixture_gains`` (aus dem Strobe-Layer, §4) skaliert physische Fixtures
        einzeln, um zwei Strips abwechselnd blitzen zu lassen. Der virtuelle
        Preview-Output bleibt davon unberührt (zeigt die volle Canvas).
        """
        fx_index = 0
        for dev in self._devices.values():
            try:
                rgb = frame.resampled(dev.pixels)
                if dev.is_fixture and fixture_gains:
                    gain = fixture_gains[fx_index % len(fixture_gains)]
                    fx_index += 1
                    if gain < 0.999:
                        rgb = (rgb.astype("float32") * gain).astype("uint8")
                await dev.send(rgb)
                dev.online = True
            except Exception as exc:  # noqa: BLE001 — ein Gerät darf nicht alle stoppen
                if dev.online:
                    log.warning("Output %s (%s) Fehler: %s", dev.id, dev.name, exc)
                dev.online = False

    async def close(self) -> None:
        for dev in self._devices.values():
            await dev.close()
