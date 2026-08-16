"""Synthetische Audio-Quelle — Testsignal ohne Hardware.

Erzeugt einen wechselnden Klang mit periodischem „Beat" (Bass-Impuls), damit
FFT/Beat/Onset auch unter WSL/Docker ohne Snapcast sinnvolle Daten liefern.
"""
from __future__ import annotations

import asyncio
import math
from typing import AsyncIterator

import numpy as np

from ..config import Settings
from .models import PCMFrame
from .source import AudioSource


class SyntheticSource(AudioSource):
    name = "synthetic"

    def __init__(self, settings: Settings) -> None:
        self.sr = settings.audio_sample_rate
        self.block = settings.audio_block_size
        self.channels = 1
        self._phase = 0.0
        self._t = 0.0
        self._bpm = 124.0

    async def frames(self) -> AsyncIterator[PCMFrame]:
        block_dt = self.block / self.sr
        beat_period = 60.0 / self._bpm
        while True:
            n = np.arange(self.block, dtype=np.float32)
            t = self._t + n / self.sr

            # Wandernder Melodie-Ton
            melody = 0.15 * np.sin(2 * np.pi * (220 + 110 * math.sin(self._t * 0.3)) * t)

            # Perkussiver Bass-Impuls im Beat-Raster (kurzer Envelope-Kick)
            beat_phase = (t % beat_period) / beat_period
            env = np.exp(-beat_phase * 18.0).astype(np.float32)
            kick = 0.6 * env * np.sin(2 * np.pi * 60 * t)

            # Etwas Hi-Hat-Rauschen auf dem Offbeat
            hat_env = np.exp(-((beat_phase - 0.5) ** 2) * 400.0).astype(np.float32)
            hat = 0.08 * hat_env * np.random.uniform(-1, 1, self.block).astype(np.float32)

            samples = (melody + kick + hat).astype(np.float32)
            np.clip(samples, -1.0, 1.0, out=samples)

            self._t += block_dt
            yield PCMFrame(samples=samples, sample_rate=self.sr, channels=1)
            await asyncio.sleep(block_dt)
