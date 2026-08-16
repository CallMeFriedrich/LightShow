"""Feature-Effekte (§6/§7) — je Szene EINER aktiv.

Alle sind tempo-synchron über einen Phasen-Akkumulator (robust gegen
BPM-Schwankungen). Gains/Parameter exakt aus §7.
"""
from __future__ import annotations

import numpy as np

from .base import Layer, RenderContext, add, comet_profile, hsv_to_rgb, hue_gradient


class _Feature(Layer):
    def __init__(self) -> None:
        self.phase = 0.0

    def _advance(self, ctx: RenderContext, beats_per_cycle: float) -> float:
        self.phase += ctx.dt / max(1e-4, beats_per_cycle * ctx.beat_len)
        return self.phase % 1.0


class ColorDrift(_Feature):
    """Langsam driftender Farbverlauf, kein Blinken. gain 0.7, span 0.30, speed 0.03."""

    gain = 0.7
    hue_span = 0.30
    speed = 0.03

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        hue = hue_gradient(ctx.pixels, ctx.base_hue + ctx.t * self.speed, self.hue_span)
        val = self.gain * (0.7 + 0.3 * ctx.a.energy)
        add(canvas, hsv_to_rgb(hue % 1.0, 1.0, val))


class Comet(_Feature):
    """Einzelner Komet, tempo-synchron. gain 0.9, tail 0.12, beats/sweep 4."""

    gain = 0.9
    tail = 0.12
    beats_per_sweep = 4.0

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        p = self._advance(ctx, self.beats_per_sweep)
        head = p if ctx.direction >= 0 else 1.0 - p
        prof = comet_profile(ctx.pixels, head, self.tail, ctx.direction)
        hue = np.full(ctx.pixels, ctx.base_hue)
        add(canvas, hsv_to_rgb(hue, 1.0, self.gain * prof))


class DualComet(_Feature):
    """Zwei Kometen von beiden Enden zur Mitte. gain 0.9, tail 0.12, beats/sweep 4."""

    gain = 0.9
    tail = 0.12
    beats_per_sweep = 4.0

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        p = self._advance(ctx, self.beats_per_sweep)
        head1 = 0.5 * p          # von links zur Mitte
        head2 = 1.0 - 0.5 * p    # von rechts zur Mitte
        prof = comet_profile(ctx.pixels, head1, self.tail, +1)
        prof = np.maximum(prof, comet_profile(ctx.pixels, head2, self.tail, -1))
        hue = np.full(ctx.pixels, ctx.base_hue)
        add(canvas, hsv_to_rgb(hue, 1.0, self.gain * prof))


class BounceComet(_Feature):
    """Komet ping-pong hin und her. gain 0.9, tail 0.10, beats/sweep 2."""

    gain = 0.9
    tail = 0.10
    beats_per_sweep = 2.0

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        p = self._advance(ctx, self.beats_per_sweep)
        head = 1.0 - abs(2.0 * p - 1.0)  # Dreieck 0→1→0
        x = np.linspace(0.0, 1.0, ctx.pixels)
        prof = np.exp(-np.abs(x - head) / self.tail).astype(np.float32)
        hue = np.full(ctx.pixels, ctx.base_hue)
        add(canvas, hsv_to_rgb(hue, 1.0, self.gain * prof))


class TheaterChase(_Feature):
    """Gleichmäßig marschierende Punkte. gain 0.85, spacing 16, beats/step 0.5."""

    gain = 0.85
    spacing = 16
    beats_per_step = 0.5

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        self.phase += ctx.dt / max(1e-4, self.beats_per_step * ctx.beat_len)
        offset = int(self.phase) * ctx.direction
        i = np.arange(ctx.pixels)
        lit = ((i - offset) % self.spacing) == 0
        prof = lit.astype(np.float32)
        hue = np.full(ctx.pixels, ctx.base_hue)
        add(canvas, hsv_to_rgb(hue, 1.0, self.gain * prof))


class QuadAlternate(_Feature):
    """4 Teile, (1+3)/(2+4) im sanften Crossfade, gleiche Farbe. gain 0.9, beats/toggle 2."""

    gain = 0.9
    beats_per_toggle = 2.0

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        p = self._advance(ctx, self.beats_per_toggle)
        w = 0.5 - 0.5 * np.cos(2 * np.pi * p)  # weicher 0→1→0-Crossfade
        seg = (np.linspace(0, 4, ctx.pixels, endpoint=False)).astype(int)
        group_a = (seg % 2) == 0  # Teile 1 & 3
        val = np.where(group_a, 1.0 - w, w).astype(np.float32)
        hue = np.full(ctx.pixels, ctx.base_hue)
        add(canvas, hsv_to_rgb(hue, 1.0, self.gain * val))


# Registry der Feature-Effekte (Kurzname → Klasse) — für SceneManager/UI.
FEATURES: dict[str, type[_Feature]] = {
    "colordrift": ColorDrift,
    "comet": Comet,
    "dual": DualComet,
    "bounce": BounceComet,
    "theater": TheaterChase,
    "quad": QuadAlternate,
}
