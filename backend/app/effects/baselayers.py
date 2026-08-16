"""Basis-Layer: Ambient, BassWash, Spectrum, Idle.

Gains/Parameter exakt aus §7 des Effekt-Regelwerks. Diese Layer bilden den
farbigen Grund; das Spektrum ist prominent und wird NICHT von der Intensität
gedämpft (§1).
"""
from __future__ import annotations

import numpy as np

from .base import Layer, RenderContext, add, hsv_to_rgb, hue_gradient


class Ambient(Layer):
    """Atmender Farbverlauf als ruhiger Grund. gain 0.28, hue-span 0.15."""

    gain = 0.28
    breath_speed = 0.4
    hue_span = 0.15
    drift = 0.03

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        hue = hue_gradient(ctx.pixels, ctx.base_hue + ctx.t * self.drift, self.hue_span)
        breath = 0.5 + 0.5 * np.sin(ctx.t * self.breath_speed * 2 * np.pi)
        val = self.gain * (0.6 + 0.4 * breath)
        add(canvas, hsv_to_rgb(hue % 1.0, 1.0, val))


class BassWash(Layer):
    """Bass-getriebener Wash. gain 0.6, hue-span 0.12, energy-shift 0.08."""

    gain = 0.6
    hue_span = 0.12
    energy_shift = 0.08

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        center = ctx.base_hue + ctx.a.energy * self.energy_shift
        hue = hue_gradient(ctx.pixels, center, self.hue_span)
        val = self.gain * ctx.a.bass
        add(canvas, hsv_to_rgb(hue % 1.0, 1.0, val))


class Spectrum(Layer):
    """Frequenzbänder als bunter Verlauf. gain 0.9, hue-span 0.45 (§1)."""

    gain = 0.9
    hue_span = 0.45

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        bands = np.asarray(ctx.a.bands, dtype=np.float32)
        if bands.size == 0:
            return
        idx = np.linspace(0, bands.size - 1, ctx.pixels).astype(int)
        vals = bands[idx]
        # Eine Farbfamilie über hue_span (nicht voller Regenbogen).
        hue = (ctx.base_hue + np.linspace(0.0, self.hue_span, ctx.pixels)) % 1.0
        add(canvas, hsv_to_rgb(hue, 1.0, self.gain * vals))


class Idle(Layer):
    """Idle bei Stille (§8): hell-dunkelblauer Grund + beiger langsamer Chase."""

    blue_hue = 0.60
    beige_hue = 0.10
    chase_seconds = 12.0

    def render(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        x = np.linspace(0.0, 1.0, ctx.pixels)
        # driftender Helligkeitsverlauf auf Blau
        val = 0.12 + 0.10 * (0.5 + 0.5 * np.sin(2 * np.pi * (x + ctx.t * 0.05)))
        base = hsv_to_rgb(np.full(ctx.pixels, self.blue_hue), 0.8, val)
        # beiger, langsam wandernder Chase-Punkt
        head = (ctx.t / self.chase_seconds) % 1.0
        d = np.abs(((x - head + 0.5) % 1.0) - 0.5)
        chase = np.exp(-d / 0.03)
        beige = hsv_to_rgb(np.full(ctx.pixels, self.beige_hue), 0.35, 0.5 * chase)
        add(canvas, base)
        add(canvas, beige)
