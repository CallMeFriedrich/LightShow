"""ShowConfig — alle ``[config]``-Parameter aus dem Effekt-Regelwerk.

Wird aus ``<data_dir>/config.yaml`` geladen und dorthin (atomar) zurück-
geschrieben. Dadurch **überlebt die Konfiguration Programm-/PC-Neustart**
(§ Notizen). Fehlt die Datei, wird sie aus den Defaults erzeugt.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import yaml


@dataclass
class ShowConfig:
    # § 1 Grundverhalten
    intensity: float = 0.6          # 0 ruhig … 1 aggressiv (Obergrenze)
    brightness: float = 1.0         # globaler Master-Dimmer
    smoothing: float = 0.5          # Anti-Flicker 0…0.95
    album_art_color: bool = True    # Cover-Farbe als Basis (Slice 2: MASS)

    # § 2 Szenen & Sektoren
    scene_seconds: float = 60.0     # Szenenwechsel-Intervall
    section_floor: float = 0.0      # inaktive Sektoren: 0 = ganz aus

    # § 3 Blackouts
    blackouts: bool = True
    blackout_chance: float = 0.6    # pro passendem Beat
    blackout_cooldown: float = 9.0  # s Mindestpause
    blackout_hold: float = 0.45     # s hart schwarz

    # § 4 Strobes
    strobes: bool = True
    strobe_chance: float = 0.3      # × effektive Intensität
    strobe_alt_chance: float = 0.5  # 2-Strip-Abwechslung (nur bei ≥2 Fixtures)
    strobe_min_song_s: float = 30.0 # kein Strobe in den ersten N s

    # § 5 Bass-Passagen
    bass_block_chance: float = 0.9  # Anteil Block- vs. Bounce-Effekt

    # (LED-Anzahl & Fixtures sind Hardware-Settings → app.config.Settings/ENV)

    # ── Laden / Speichern ──
    @classmethod
    def load(cls, data_dir: str | os.PathLike) -> "ShowConfig":
        path = Path(data_dir) / "config.yaml"
        cfg = cls()
        if path.is_file():
            data = yaml.safe_load(path.read_text()) or {}
            known = {f.name for f in fields(cls)}
            for k, v in data.items():
                if k in known:
                    setattr(cfg, k, v)
        else:
            cfg.save(data_dir)
        cfg._data_dir = str(data_dir)  # type: ignore[attr-defined]
        return cfg

    def save(self, data_dir: str | os.PathLike | None = None) -> None:
        target = Path(data_dir or getattr(self, "_data_dir", "."))
        target.mkdir(parents=True, exist_ok=True)
        path = target / "config.yaml"
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True))
        os.replace(tmp, path)  # atomarer Write

    def update(self, changes: dict) -> list[str]:
        """Übernimmt bekannte Keys, gibt die tatsächlich geänderten zurück."""
        known = {f.name for f in fields(self)}
        applied: list[str] = []
        for k, v in changes.items():
            if k in known:
                setattr(self, k, v)
                applied.append(k)
        if applied:
            self.save()
        return applied

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}
