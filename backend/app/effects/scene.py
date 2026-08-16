"""SceneManager (§6/§2).

Wählt pro Szene EINEN Feature-Effekt (Pool je nach mood), ein Sektor-Muster
(gewichtet) und eine Chase-Richtung. Szenenwechsel alle ``scene_seconds``.
"""
from __future__ import annotations

import numpy as np

from . import sectors
from .features import FEATURES, _Feature

# Pools nach Song-Charakter (§6).
POOL_CALM = ["colordrift", "comet", "quad", "colordrift"]
POOL_ENERGETIC = ["theater", "dual", "bounce", "comet"]
MOOD_SPLIT = 0.45


class SceneManager:
    def __init__(self, rng: np.random.Generator) -> None:
        self.rng = rng
        self.feature: _Feature = FEATURES["colordrift"]()
        self.feature_name = "colordrift"
        self.pattern = "full"
        self.mask: np.ndarray | None = None
        self.direction = 1
        self._scene_start = 0.0
        self._pixels = 0

    def maybe_advance(self, t: float, mood: float, scene_seconds: float, pixels: int,
                      floor: float, pool: str | None = None, force: bool = False) -> bool:
        """Wechselt die Szene, wenn fällig oder erzwungen. True bei Wechsel.

        ``pool``: "calm" | "energetic" | None (dann nach mood).
        """
        due = self.mask is None or self._pixels != pixels or (t - self._scene_start) >= scene_seconds
        if force or due:
            self._new_scene(t, mood, pixels, floor, pool)
            return True
        return False

    def _new_scene(self, t: float, mood: float, pixels: int, floor: float, pool: str | None = None) -> None:
        if pool == "energetic":
            names = POOL_ENERGETIC
        elif pool == "calm":
            names = POOL_CALM
        else:
            names = POOL_ENERGETIC if mood >= MOOD_SPLIT else POOL_CALM
        self.feature_name = str(self.rng.choice(names))
        self.feature = FEATURES[self.feature_name]()
        self.pattern = sectors.pick_pattern(self.rng)
        self.mask = sectors.make_mask(pixels, self.pattern, floor)
        self.direction = int(self.rng.choice([-1, 1]))
        self._scene_start = t
        self._pixels = pixels

    def rebuild_mask(self, pixels: int, floor: float) -> None:
        self.mask = sectors.make_mask(pixels, self.pattern, floor)
        self._pixels = pixels
