"""Realtime-Songstruktur-Erkennung (intro / build / drop / verse / break / outro).

Klassifiziert den aktuellen Abschnitt aus dem **Energieverlauf** (schnelle vs.
langsame EMA + Trend), der **Position im Song** (elapsed/duration, aus SendSpin)
und **Drop-Events**. Kein Offline-Wissen wie Rekordbox, aber eine gute
Live-Näherung, damit sich der Streifen je Abschnitt anders verhält.

Abschnitte:
* **intro**  — Songanfang, noch ruhig
* **build**  — Energie steigt anhaltend (Up/Build-up) → Spannung
* **drop**   — kurz nach einem Energie-Sprung, hohe Energie (Chorus/Hook)
* **verse**  — mittlere Energie (Standard)
* **break**  — Energie deutlich unter dem Songmittel (Breakdown/Down)
* **outro**  — Songende, Energie fällt
"""
from __future__ import annotations

import math


class SectionDetector:
    def __init__(self) -> None:
        self.section = "intro"
        self.tension = 0.0            # 0..1, steigt im Build-up
        self._e_base = 0.0            # langsames Songmittel (~12 s)
        self._e_fast = 0.0            # schnelle Energie (~1 s)
        self._e_prev = 0.0
        self._trend = 0.0
        self._t = 0.0
        self._last_drop_t = -999.0
        self._rising_since: float | None = None

    def update(self, energy: float, drop_now: bool, pos: float | None, dt: float,
               future_energy: float | None = None) -> tuple[str, float]:
        dt = max(1e-3, min(0.2, dt))
        self._t += dt
        a_base = 1.0 - math.exp(-dt / 12.0)
        a_fast = 1.0 - math.exp(-dt / 1.0)
        self._e_base += a_base * (energy - self._e_base)
        self._e_fast += a_fast * (energy - self._e_fast)

        deriv = (self._e_fast - self._e_prev) / dt
        self._e_prev = self._e_fast
        self._trend = 0.9 * self._trend + 0.1 * deriv

        if drop_now:
            self._last_drop_t = self._t
        since_drop = self._t - self._last_drop_t

        if self._trend > 0.04:
            if self._rising_since is None:
                self._rising_since = self._t
        else:
            self._rising_since = None
        rising_dur = (self._t - self._rising_since) if self._rising_since is not None else 0.0

        # Gelerntes Profil: kommt in ~4 s deutlich mehr Energie? → vorausschauender Build-up.
        learned_build = (
            future_energy is not None
            and future_energy > 0.45
            and (future_energy - self._e_fast) > 0.12
        )

        # ── Klassifikation (Priorität von oben) ──
        if pos is not None and pos > 0.90 and self._e_fast < self._e_base * 0.9:
            sec = "outro"
        elif pos is not None and pos < 0.08 and self._e_fast < 0.5:
            sec = "intro"
        elif since_drop < 6.0 and self._e_fast > max(0.45, self._e_base):
            sec = "drop"
        elif self._e_base > 0.4 and self._e_fast < self._e_base * 0.6:
            sec = "break"
        elif learned_build or (rising_dur > 1.5 and self._e_fast > 0.35):
            sec = "build"
        else:
            sec = "verse"

        if sec == "build":
            self.tension = min(1.0, self.tension + dt * 0.4)
        elif sec == "drop":
            self.tension = 0.0
        else:
            self.tension = max(0.0, self.tension - dt * 0.6)

        self.section = sec
        return sec, self.tension
