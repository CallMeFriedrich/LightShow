"""Look-ahead (§9) — Build-ups vor bekannten Drops.

Hält die Drop-Positionen des aktuell laufenden Tracks **im Speicher** (schnell,
kein DB-Zugriff pro Frame). Neue, realtime erkannte Drops werden dedupliziert
und (vom Aufrufer) persistiert. `compute()` liefert je Frame einen
beschleunigenden Build-up-Wert und ein prädiktives Drop-Flag.
"""
from __future__ import annotations

_LEAD = 6.0        # s: Build-up beginnt ~6 s vor dem Drop
_TOL = 1.5         # s: Dedupe-Fenster (wie im Store)
_PREDICT = 0.15    # s: Fenster, in dem der Drop prädiktiv ausgelöst wird


def derive_drops(profile: list[float]) -> list[float]:
    """Drop-Positionen (Sekunden) aus dem gelernten Energie-Profil ableiten.

    Ein Drop = anhaltender Energie-Sprung auf hohes Niveau (Chorus/Hook). Robuster
    als reine Realtime-Erkennung, weil die ganze Hüllkurve bekannt ist. (Idee aus
    der alten StructureRecorder-Logik, hier aus unserem Live-Profil abgeleitet.)
    """
    n = len(profile)
    if n < 12:
        return []
    peak = max(profile) or 1.0
    srt = sorted(profile)
    base = srt[len(srt) // 2]  # Median
    drops: list[float] = []
    last = -999
    for s in range(4, n):
        rise = profile[s] - profile[s - 4]
        if (profile[s] > max(0.5, base * 1.1) and profile[s] > peak * 0.75
                and rise > 0.12 and (s - last) > 8):
            drops.append(float(s))
            last = s
    return drops


class LookAhead:
    def __init__(self) -> None:
        self.track_id = ""
        self.drops: list[float] = []

    def set_track(self, track_id: str, drops: list[float]) -> None:
        self.track_id = track_id
        self.drops = sorted(drops)

    def record_drop(self, elapsed: float) -> bool:
        """Realtime-Drop merken. True, wenn neu (→ Aufrufer persistiert)."""
        if not self.track_id or elapsed < 0:
            return False
        for i, p in enumerate(self.drops):
            if abs(p - elapsed) < _TOL:
                self.drops[i] = (p + elapsed) / 2  # leicht nachführen
                return False
        self.drops.append(elapsed)
        self.drops.sort()
        return True

    def seconds_to_next_drop(self, elapsed: float) -> float | None:
        """Sekunden bis zum nächsten bekannten Drop (oder None)."""
        for p in self.drops:
            if p > elapsed + _PREDICT:
                return p - elapsed
        return None

    def compute(self, elapsed: float) -> tuple[float, bool]:
        """(buildup [0,1], predicted_drop) für die aktuelle Position."""
        if not self.drops:
            return 0.0, False
        nxt = None
        for p in self.drops:
            if p >= elapsed - _PREDICT:
                nxt = p
                break
        if nxt is None:
            return 0.0, False
        delta = nxt - elapsed
        if abs(delta) <= _PREDICT:
            return 1.0, True
        if 0 < delta <= _LEAD:
            # beschleunigend: quadratisch gegen 1 kurz vor dem Drop
            return float(((_LEAD - delta) / _LEAD) ** 2), False
        return 0.0, False
