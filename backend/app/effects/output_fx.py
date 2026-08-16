"""Output-Layer (§3 Blackouts, §4 Strobes).

Werden **nach** Sektor-Masking angewandt. Reihenfolge im Compositor:
zuerst Strobe, dann **Blackout ganz zuletzt → gewinnt immer** (behebt den
Bug, dass ein Strobe den Blackout übermalt hat).
"""
from __future__ import annotations

import numpy as np

from .base import RenderContext, hsv_to_rgb

_STROBE_COOLDOWN = 8.0  # s (§4, [code])


class Blackout:
    """Harter Schnitt auf Schwarz, gehalten, dann knackig wieder an (kein Fade)."""

    def __init__(self) -> None:
        self._until = -1.0
        self._last_t = -999.0

    def update(self, ctx: RenderContext) -> bool:
        cfg = ctx.cfg
        if ctx.t < self._until:
            return True  # noch im Blackout
        if not cfg.blackouts:
            return False
        # Auslöser: nur auf Beat, mood > 0.5 und energy > 0.45 (§3, [code]).
        if (
            ctx.a.beat_now
            and ctx.a.mood > 0.5
            and ctx.a.energy > 0.45
            and (ctx.t - self._last_t) >= cfg.blackout_cooldown
            and ctx.rng.random() < cfg.blackout_chance
        ):
            self._until = ctx.t + cfg.blackout_hold
            self._last_t = ctx.t
            return True
        return False

    def apply(self, canvas: np.ndarray, active: bool) -> None:
        if active:
            canvas[:] = 0.0  # harter Aus-Schnitt


class Strobe:
    """Strobe-Bursts, nur auf echten Drops. Typen white/unicolor/randomcolor."""

    def __init__(self) -> None:
        self._until = -1.0
        self._start = 0.0
        self._last_t = -999.0
        self._type = "white"
        self._alt = False
        self._flash_idx = -1
        self._color: np.ndarray | None = None

    def update(self, ctx: RenderContext, fixtures: int) -> None:
        cfg = ctx.cfg
        if ctx.t >= self._until and cfg.strobes and ctx.drop:
            if (
                ctx.a.song_time >= cfg.strobe_min_song_s
                and (ctx.t - self._last_t) >= _STROBE_COOLDOWN
                and ctx.rng.random() < cfg.strobe_chance * ctx.eff_intensity
            ):
                self._start = ctx.t
                self._until = ctx.t + float(ctx.rng.uniform(0.5, 1.0))
                self._last_t = ctx.t
                self._type = str(ctx.rng.choice(["white", "unicolor", "randomcolor"]))
                self._alt = fixtures >= 2 and ctx.rng.random() < cfg.strobe_alt_chance
                self._flash_idx = -1

    @property
    def active(self) -> bool:
        return False  # via apply gesteuert; Zeitfenster in apply geprüft

    def apply(self, canvas: np.ndarray, ctx: RenderContext, fixtures: int) -> list[float] | None:
        """Überschreibt die Canvas während eines Bursts. Gibt fixture-Gains zurück."""
        if ctx.t >= self._until:
            return None
        # 16tel-Blitzrate → Intervall = beat_len / 4.
        interval = max(1e-3, ctx.beat_len / 4.0)
        idx = int((ctx.t - self._start) / interval)
        on = (idx % 2) == 0
        if not on:
            canvas[:] = 0.0
            return [0.0] * max(1, fixtures)
        if idx != self._flash_idx:
            self._flash_idx = idx
            self._color = self._make_color(ctx)
        canvas[:] = self._color
        if self._alt and fixtures >= 2:
            lit = idx % fixtures
            return [1.0 if i == lit else 0.0 for i in range(fixtures)]
        return [1.0] * max(1, fixtures)

    def _make_color(self, ctx: RenderContext) -> np.ndarray:
        p = ctx.pixels
        if self._type == "white":
            return np.ones((p, 3), dtype=np.float32)
        if self._type == "unicolor":
            hue = float(ctx.rng.random())
            return hsv_to_rgb(np.full(p, hue), 1.0, np.ones(p)).astype(np.float32)
        # randomcolor: zufällige Farben pro Block (12 LEDs)
        block = 12
        hues = ctx.rng.random(size=(p // block + 1))
        hue = np.repeat(hues, block)[:p]
        return hsv_to_rgb(hue, 1.0, np.ones(p)).astype(np.float32)
