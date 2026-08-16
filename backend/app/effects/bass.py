"""Bass-Passagen-Effekte (§5): BlockToggle & BassBounce.

Erkennung der Bass-Schläge über einen internen Flankendetektor auf ``a.bass``.
"""
from __future__ import annotations

import numpy as np

from .base import Layer, RenderContext, add, hsv_to_rgb


class _BassHit:
    """Flankendetektor: True beim Überschreiten der Schwelle (mit Refraktärzeit)."""

    def __init__(self, threshold: float = 0.5, refractory: float = 0.12) -> None:
        self.threshold = threshold
        self.refractory = refractory
        self._armed = True
        self._last_t = -999.0

    def hit(self, bass: float, t: float) -> bool:
        if bass < self.threshold * 0.7:
            self._armed = True
        if self._armed and bass >= self.threshold and (t - self._last_t) > self.refractory:
            self._armed = False
            self._last_t = t
            return True
        return False


class BlockToggle(Layer):
    """36-LED-Blöcke, schalten auf jeden Bass-Schlag um. gain 0.95, block 36, schwelle 0.5."""

    gain = 0.95
    block = 36
    threshold = 0.5

    def __init__(self) -> None:
        self._det = _BassHit(self.threshold)
        self._state = 0

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        if self._det.hit(ctx.a.bass, ctx.t):
            self._state ^= 1
        i = np.arange(ctx.pixels)
        block_idx = i // self.block
        lit = (block_idx % 2) == self._state
        hue = np.full(ctx.pixels, ctx.base_hue)
        add(canvas, hsv_to_rgb(hue, 1.0, self.gain * lit.astype(np.float32)))


class BassBounce(Layer):
    """Komet schwingt bei jedem Bass-Schlag zum anderen Ende. gain 0.95, tail 0.10."""

    gain = 0.95
    tail = 0.10

    def __init__(self) -> None:
        self._det = _BassHit()
        self._target = 1.0
        self._start = 0.0
        self._hit_t = 0.0
        self._interval = 0.5

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        if self._det.hit(ctx.a.bass, ctx.t):
            interval = ctx.t - self._hit_t
            self._interval = min(2.0, max(0.15, interval)) if self._hit_t else ctx.beat_len
            self._start = self._pos(ctx.t)
            self._target = 1.0 - self._target
            self._hit_t = ctx.t
        head = self._pos(ctx.t)
        x = np.linspace(0.0, 1.0, ctx.pixels)
        prof = np.exp(-np.abs(x - head) / self.tail).astype(np.float32)
        hue = np.full(ctx.pixels, ctx.base_hue)
        add(canvas, hsv_to_rgb(hue, 1.0, self.gain * prof))

    def _pos(self, t: float) -> float:
        progress = min(1.0, (t - self._hit_t) / max(1e-3, self._interval))
        return self._start + (self._target - self._start) * progress
