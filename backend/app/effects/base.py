"""Effekt-Fundament: Render-Kontext, Layer-ABC und Farb-/Zeichen-Helfer.

Die Show wird in einer **float-Canvas** (pixels, 3) im Bereih [0, 1] komponiert;
erst am Ende (Compositor) wird nach uint8 quantisiert. Layer *addieren* i. d. R.
ihren Beitrag (additives Licht), Basis-Layer *schreiben* den Grund.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass

import numpy as np

from ..audio.models import AnalysisFrame
from .config import ShowConfig


@dataclass
class RenderContext:
    pixels: int
    t: float                 # Sekunden seit Start
    dt: float                # Zeit seit letztem Frame
    a: AnalysisFrame         # aktuelle Analyse
    cfg: ShowConfig
    eff_intensity: float     # intensity × (0.35 + 0.65 × mood) × (1 + buildup)  (§1)
    base_hue: float          # Basisfarbe (Album-Cover-Farbe), 0..1
    direction: int = 1       # Chase-Richtung (+1/-1), pro Szene
    drop: bool = False       # effektiver Drop (realtime ODER prädiktiv, §9)
    buildup: float = 0.0     # Look-ahead Build-up [0,1] vor bekanntem Drop (§9)
    rng: np.random.Generator = None  # type: ignore[assignment]

    @property
    def beat_len(self) -> float:
        """Sekunden pro Beat (Fallback 120 BPM)."""
        bpm = self.a.bpm if self.a.bpm >= 40 else 120.0
        return 60.0 / bpm


class Layer(abc.ABC):
    """Ein Kompositions-Layer. Schreibt additiv in die float-Canvas."""

    gain: float = 1.0

    @abc.abstractmethod
    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        ...


# ── Farb-Helfer (vektorisiert, float [0,1]) ─────────────────────────
def hsv_to_rgb(h: np.ndarray, s: float | np.ndarray, v: np.ndarray | float) -> np.ndarray:
    """(h, v) als Arrays/Skalare in [0,1] → RGB-Array (…, 3) in [0,1]."""
    h = np.asarray(h, dtype=np.float32)
    v = np.asarray(v, dtype=np.float32) * np.ones_like(h)
    s = np.asarray(s, dtype=np.float32) * np.ones_like(h)
    i = np.floor(h * 6.0).astype(int)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i = i % 6
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.clip(np.stack([r, g, b], axis=-1), 0.0, 1.0)


def hue_gradient(pixels: int, center: float, span: float) -> np.ndarray:
    """Hue-Verlauf der Breite ``span`` um ``center`` über den Streifen."""
    return center + np.linspace(-span / 2.0, span / 2.0, pixels)


def add(canvas: np.ndarray, rgb: np.ndarray) -> None:
    """Additiv mischen (Licht) mit Clamp."""
    np.add(canvas, rgb, out=canvas)
    np.clip(canvas, 0.0, 1.0, out=canvas)


def comet_profile(pixels: int, head: float, tail: float, direction: int) -> np.ndarray:
    """Helligkeitsprofil eines Kometen (Kopf bei ``head`` in [0,1], Schweif hinten)."""
    x = np.linspace(0.0, 1.0, pixels)
    # Distanz „hinter" dem Kopf (gegen die Laufrichtung).
    d = (head - x) * direction
    d = np.where(d < 0, 1.0, d)  # vor dem Kopf: dunkel
    prof = np.exp(-d / max(1e-4, tail))
    return prof.astype(np.float32)
