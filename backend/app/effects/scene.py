"""SceneManager — pro Songabschnitt EIN Effekt, aber abwechslungsreich.

Innerhalb eines Abschnitts bleibt der Effekt stabil (kein „freestyled" Rotieren).
Bei jedem NEUEN Abschnitt wird aus dem Pool des Abschnitts ein Effekt gewählt —
**nicht derselbe wie beim letzten Mal** in diesem Abschnitt, damit es abwechslungs-
reich bleibt.
"""
from __future__ import annotations

import numpy as np

from . import sectors
from .features import FEATURES, _Feature

# Pro Abschnitt ein Pool passender Effekte (es rotiert ohne direkte Wiederholung).
SECTION_POOLS: dict[str, list[str]] = {
    "intro": ["colordrift", "comet", "quad"],
    "build": ["theater", "comet", "dual", "bounce"],
    "drop":  ["dual", "bounce", "theater", "comet"],
    "verse": ["comet", "colordrift", "quad", "theater", "dual"],
    "break": ["quad", "colordrift", "bounce"],
    "outro": ["colordrift", "comet", "quad"],
}

# Rückwärtskompatibler Name für die REST-Info.
SECTION_FEATURE = SECTION_POOLS


class SceneManager:
    def __init__(self, rng: np.random.Generator) -> None:
        self.rng = rng
        self.section: str | None = None
        self.feature_name = "colordrift"
        self.feature: _Feature = FEATURES["colordrift"]()
        self.pattern = "full"
        self.mask: np.ndarray | None = None
        self.direction = 1
        self._pixels = 0
        self._last: dict[str, str] = {}  # zuletzt gewählter Effekt je Abschnitt

    def ensure(self, section: str, pixels: int, floor: float) -> bool:
        """Setzt bei Abschnittswechsel (oder erstem Aufruf) einen Effekt. True bei Wechsel."""
        if self.mask is None or self._pixels != pixels or section != self.section:
            self._set_section(section, pixels, floor)
            return True
        return False

    def _pick_feature(self, section: str) -> str:
        pool = SECTION_POOLS.get(section, ["comet"])
        last = self._last.get(section)
        options = [p for p in pool if p != last] or pool
        name = str(self.rng.choice(options))
        self._last[section] = name
        return name

    def _set_section(self, section: str, pixels: int, floor: float) -> None:
        self.section = section
        self.feature_name = self._pick_feature(section)
        self.feature = FEATURES[self.feature_name]()
        self.pattern = sectors.pick_pattern(self.rng)
        self.mask = sectors.make_mask(pixels, self.pattern, floor)
        self.direction = int(self.rng.choice([-1, 1]))
        self._pixels = pixels

    def rebuild_mask(self, pixels: int, floor: float) -> None:
        self.mask = sectors.make_mask(pixels, self.pattern, floor)
        self._pixels = pixels
