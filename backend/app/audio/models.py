"""Datenmodelle der Audio-Pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(slots=True)
class PCMFrame:
    """Ein Block normierter Audio-Samples (float32, Bereich [-1, 1]).

    ``samples`` hat Form (n,) für mono oder (n, channels) für multichannel.
    """

    samples: np.ndarray
    sample_rate: int
    channels: int

    @property
    def mono(self) -> np.ndarray:
        if self.samples.ndim == 1:
            return self.samples
        return self.samples.mean(axis=1)


@dataclass(slots=True)
class AnalysisFrame:
    """Ergebnis der Realtime-Analyse eines PCM-Blocks.

    Enthält alle Features, die das Effekt-Regelwerk braucht: Frequenzbänder für
    das Spektrum, gruppierte Bass/Mitten/Höhen, Gesamt-``energy`` und ein
    langsames ``mood`` (Song-Charakter), Beat/BPM/Onset sowie Realtime-Drop.
    """

    # Spektrum / Rohwerte
    bands: list[float] = field(default_factory=list)  # normalisiert [0, 1]
    rms: float = 0.0
    peak: float = 0.0

    # Gruppierte Bänder (adaptiv normiert [0, 1]) — für Bass-Passagen & Wash
    bass: float = 0.0
    mids: float = 0.0
    highs: float = 0.0

    # Song-Charakter
    energy: float = 0.0  # geglättete Gesamtenergie [0, 1]
    mood: float = 0.0  # langsam, Spectral-Centroid-Proxy [0, 1]

    # Rhythmus / Ereignisse
    bpm: float = 0.0
    beat_now: bool = False
    onset: float = 0.0  # Spectral-Flux gesamt, normiert [0, 1]
    highs_onset: float = 0.0  # Flux nur in den Höhen (für Sparkles)
    drop_now: bool = False  # Realtime-Drop erkannt

    # Zeit / Zustand
    song_time: float = 0.0  # Sekunden seit (heuristischem) Song-Start
    silence: bool = False  # unter Idle-Schwelle

    def to_dict(self) -> dict:
        return {
            "bands": [round(b, 4) for b in self.bands],
            "rms": round(self.rms, 4),
            "peak": round(self.peak, 4),
            "bass": round(self.bass, 4),
            "mids": round(self.mids, 4),
            "highs": round(self.highs, 4),
            "energy": round(self.energy, 4),
            "mood": round(self.mood, 4),
            "bpm": round(self.bpm, 1),
            "beat": self.beat_now,
            "onset": round(self.onset, 4),
            "drop": self.drop_now,
            "song_time": round(self.song_time, 1),
            "silence": self.silence,
        }
