"""SceneManager — pro Songabschnitt GENAU EIN fester Feature-Effekt.

Kein Zufalls-Rotieren mehr (das wirkte „freestyled"): der Feature-Effekt ist je
Abschnitt fest zugeordnet und bleibt stabil, solange der Abschnitt läuft. Er
wechselt NUR beim Abschnittswechsel (dann auch ein neues Sektor-Muster/Richtung,
einmalig gewählt).
"""
from __future__ import annotations

import numpy as np

from . import sectors
from .features import FEATURES, _Feature

# Feste Zuordnung Abschnitt → Feature-Effekt (kann angepasst werden).
SECTION_FEATURE: dict[str, str] = {
    "intro": "colordrift",   # ruhig, driftender Verlauf, kein Blinken
    "build": "theater",      # marschierende Punkte → steigende Spannung
    "drop":  "dual",         # zwei Kometen zur Mitte → energetisch
    "verse": "comet",        # ein Komet, tempo-synchron
    "break": "quad",         # 4-Teiler, sanfter Crossfade → ruhig
    "outro": "colordrift",   # ruhig, fährt runter
}


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

    def ensure(self, section: str, pixels: int, floor: float) -> bool:
        """Setzt bei Abschnittswechsel (oder erstem Aufruf) den festen Effekt. True bei Wechsel."""
        if self.mask is None or self._pixels != pixels or section != self.section:
            self._set_section(section, pixels, floor)
            return True
        return False

    def _set_section(self, section: str, pixels: int, floor: float) -> None:
        name = SECTION_FEATURE.get(section, "comet")
        self.section = section
        self.feature_name = name
        self.feature = FEATURES[name]()
        self.pattern = sectors.pick_pattern(self.rng)
        self.mask = sectors.make_mask(pixels, self.pattern, floor)
        self.direction = int(self.rng.choice([-1, 1]))
        self._pixels = pixels

    def rebuild_mask(self, pixels: int, floor: float) -> None:
        self.mask = sectors.make_mask(pixels, self.pattern, floor)
        self._pixels = pixels
