"""Overlay-Layer (§6): BeatPulse & Sparkle.

Beide skalieren mit der **effektiven Intensität** (§1) und sind mood-gated —
sie kommen nur bei höherem/hohem mood dazu.
"""
from __future__ import annotations

import numpy as np

from .base import Layer, RenderContext, add, hsv_to_rgb


class BeatPulse(Layer):
    """Kurzer Blitz auf Beats. gain 0.6, decay 0.16. Nur bei höherem mood."""

    gain = 0.6
    decay = 0.16
    mood_gate = 0.45

    def __init__(self) -> None:
        self._level = 0.0

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        if ctx.a.mood < self.mood_gate:
            self._level = 0.0
            return
        if ctx.a.beat_now:
            self._level = 1.0
        else:
            self._level *= float(np.exp(-ctx.dt / self.decay))
        amt = self.gain * self._level * ctx.eff_intensity
        if amt <= 0.001:
            return
        rgb = hsv_to_rgb(np.full(ctx.pixels, ctx.base_hue), 0.2, np.full(ctx.pixels, amt))
        add(canvas, rgb)


class Sparkle(Layer):
    """Zufällige Funken auf Höhen-Onsets. gain 0.9, decay 0.18. Nur bei hohem mood."""

    gain = 0.9
    decay = 0.18
    mood_gate = 0.55
    onset_gate = 0.4

    def __init__(self, pixels: int) -> None:
        self._buf = np.zeros(pixels, dtype=np.float32)

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        if self._buf.size != ctx.pixels:
            self._buf = np.zeros(ctx.pixels, dtype=np.float32)
        self._buf *= float(np.exp(-ctx.dt / self.decay))
        if ctx.a.mood >= self.mood_gate and ctx.a.highs_onset >= self.onset_gate:
            n = max(1, int(ctx.pixels * 0.04 * ctx.eff_intensity))
            # Gleichmäßige Abstände statt Zufallspositionen: ein Raster mit
            # gemeinsamem Offset (funkelt lebendig, sitzt aber immer regelmäßig).
            step = ctx.pixels / n
            phase = float(ctx.rng.random()) * step
            idx = ((np.arange(n) * step + phase).astype(int)) % ctx.pixels
            self._buf[idx] = 1.0
        amt = self.gain * self._buf * ctx.eff_intensity
        rgb = hsv_to_rgb(np.full(ctx.pixels, (ctx.base_hue + 0.1) % 1.0), 0.15, amt)
        add(canvas, rgb)
