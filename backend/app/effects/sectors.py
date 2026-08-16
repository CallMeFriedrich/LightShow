"""Sektor-Masken (§2).

Muster sind **spiegelsymmetrisch** um die Mitte, haben **weiche Kanten**
(feather = 3.5 % des Streifens) und schalten inaktive Bereiche auf
``section_floor`` (Default 0 = ganz aus). Die Muster-Gewichtung bevorzugt
stark „full".
"""
from __future__ import annotations

import numpy as np

FEATHER = 0.035  # 3.5 % des Streifens

# Aktive Bereiche je Muster (Fraktionen [0,1]) — alle mirror-symmetrisch.
PATTERNS: dict[str, list[tuple[float, float]]] = {
    "full": [(0.0, 1.0)],
    "center": [(0.35, 0.65)],
    "edges": [(0.0, 0.18), (0.82, 1.0)],
    "thirds_out": [(0.0, 0.33), (0.67, 1.0)],
    "quarters": [(0.125, 0.375), (0.625, 0.875)],
    "mid_third": [(0.33, 0.67)],
}

# Muster-Gewichtung: full ×9, Rest je 1×.
WEIGHTS: dict[str, int] = {
    "full": 9,
    "center": 1,
    "edges": 1,
    "thirds_out": 1,
    "quarters": 1,
    "mid_third": 1,
}


def _gaussian_kernel(sigma_px: float) -> np.ndarray:
    radius = max(1, int(sigma_px * 3))
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    k = np.exp(-(x**2) / (2 * sigma_px**2))
    return k / k.sum()


def make_mask(pixels: int, pattern: str, floor: float = 0.0) -> np.ndarray:
    """Erzeugt die Sektor-Maske (pixels,) in [floor, 1] mit weichen Kanten."""
    regions = PATTERNS.get(pattern, PATTERNS["full"])
    hard = np.zeros(pixels, dtype=np.float32)
    for lo, hi in regions:
        a, b = int(lo * pixels), int(hi * pixels)
        hard[a:b] = 1.0
    if pattern != "full":
        sigma = max(0.5, FEATHER * pixels)
        k = _gaussian_kernel(sigma)
        hard = np.convolve(hard, k, mode="same")
        hard = np.clip(hard, 0.0, 1.0)
    return floor + (1.0 - floor) * hard


def pick_pattern(rng: np.random.Generator) -> str:
    names = list(WEIGHTS.keys())
    weights = np.array([WEIGHTS[n] for n in names], dtype=np.float64)
    weights /= weights.sum()
    return str(rng.choice(names, p=weights))
