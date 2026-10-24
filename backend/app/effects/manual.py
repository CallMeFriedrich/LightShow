"""ManualEngine — Live-Pult für den manuellen Modus.

Im Modus ``manual`` ersetzt dieser Renderer die audio-gesteuerte ShowEngine.
Der Zustand (``ManualState``) wird vom UI in Echtzeit gesetzt (WS/REST) und
pro Frame gelesen — keine Szenen-Automatik, keine Zufallsblackouts.

**Looks:** Ein Look ist ein Stapel von Effekt-Layern (je Farbe, Stärke, Tempo) plus
Grundfarbe für die Auto-Farben. Das Live-Pult ist ein Look, und jede **Szene** ist ein
eigener, frei programmierbarer Look. Szenen sind wie Effekte stapelbar: alle aktiven
Szenen und das Live-Pult werden gemeinsam komponiert; beim An-/Abschalten blenden
Szenen über ``scene_fade`` weich ein bzw. aus.
* Flächen-Layer (solid, breathe, rainbow, cycle) mischen additiv (wie Licht).
* Muster-Layer (wave, chase, theater, sparkle) liegen deckend darüber (Alpha-Blend).

**Tempo:** Es gibt ein globales Tempo (BPM — getappt oder live aus der Musik).
Jeder Layer und der Strobe laufen entweder *synchron* dazu (Faktor ⅛…4, phasengenau
auf dem Beat) oder mit *eigenem* Tempo in Hz.

Reihenfolge pro Frame:
1. Flächen aller Looks → Muster aller Looks → Beat-Pump → Bump → Strobe → Pult-Dimmer
2. Flash (Halten) / Blinder (sofort Warmweiß, nach dem Loslassen Fade-out)
3. Blackout (Halten, gewinnt immer)
"""
from __future__ import annotations

import copy
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from ..audio.models import AnalysisFrame
from ..output.base import FrameBuffer
from .base import hsv_to_rgb

FILL_EFFECTS = ("solid", "gradient", "breathe", "rainbow", "cycle")
OVERLAY_EFFECTS = ("wave", "chase", "theater", "police", "sparkle")
EFFECTS = ("solid", "chase", "theater", "wave", "breathe", "rainbow", "cycle", "sparkle", "police", "gradient")
TWO_COLOR = ("police", "gradient")
SEGMENTS = (2, 4, 6, 8)
PATTERN_PREFIX = "p_"          # Layer-Key eines eigenen Musters: "p_<id>"
MAX_PATTERN_SEGMENTS = 32
MAX_PATTERN_STEPS = 32

# Tempo-Faktoren relativ zum globalen Beat (Zyklen pro Beat).
MULTS = (0.125, 0.25, 0.5, 1.0, 2.0, 4.0)
_DEFAULT_MULT = {"solid": 1.0, "chase": 1.0, "theater": 1.0, "wave": 0.5,
                 "breathe": 0.25, "rainbow": 0.25, "cycle": 0.125, "sparkle": 1.0, "police": 0.5,
                 "gradient": 0.125}

# Voreingestellte Palette (Name, Hue, Sättigung). Auto-Akzente werden daraus gewählt.
PALETTE: list[tuple[str, float, float]] = [
    ("Weiß", 0.0, 0.0), ("Warmweiß", 0.083, 0.58), ("Rot", 0.0, 1.0), ("Orange", 0.07, 1.0),
    ("Gelb", 0.15, 1.0), ("Grün", 0.33, 1.0), ("Türkis", 0.48, 1.0), ("Blau", 0.62, 1.0),
    ("Violett", 0.75, 1.0), ("Magenta", 0.87, 1.0), ("Pink", 0.93, 0.55),
]
_HUES = [h for _, h, sat in PALETTE if sat >= 1.0]  # gesättigte Töne für Auto-Akzente

_WARM_WHITE = np.array([1.0, 0.72, 0.42], dtype=np.float32)  # ~2700 K
_MOMENTARY = ("blackout", "blinder", "flash")

_LAYER_SPEC: dict[str, tuple] = {
    "on": ("bool",), "color_auto": ("bool",), "sync": ("bool",),
    "hue": ("hue",), "saturation": ("range", 0.0, 1.0), "level": ("range", 0.0, 1.0),
    "mult": ("mult",), "hz": ("range", 0.02, 10.0),
    # Zweitfarbe/Segmente/Doppelblitz (Polizei-Effekt)
    "hue2": ("hue",), "saturation2": ("range", 0.0, 1.0), "segments": ("segments",), "blink": ("bool",),
    "move": ("bool",),           # Verlauf bewegt (sonst statisch)
}
_LOOK_SPEC: dict[str, tuple] = {"hue": ("hue",), "saturation": ("range", 0.0, 1.0)}
_SCENE_SPEC: dict[str, tuple] = {**_LOOK_SPEC, "name": ("str",), "level": ("range", 0.0, 1.0)}
_STATE_SPEC: dict[str, tuple] = {
    **_LOOK_SPEC, "brightness": ("range", 0.0, 1.0),
    "direction": ("dir",), "mirror": ("bool",), "beat_sync": ("bool",),
    "bpm": ("range", 20.0, 300.0), "music_sync": ("bool",),
    "strobe_on": ("bool",), "strobe_hz": ("range", 0.5, 20.0), "strobe_sync": ("bool",),
    "strobe_mult": ("mult",), "strobe_white": ("bool",), "strobe_alt": ("bool",),
    "blinder_fade": ("range", 0.1, 5.0), "scene_fade": ("range", 0.0, 10.0),
    "scene_exclusive": ("bool",),
    "bump_gain": ("range", 0.0, 1.0), "bump_decay": ("range", 0.05, 1.0), "bump_beat": ("bool",),
    "blackout": ("bool",), "blinder": ("bool",), "flash": ("bool",),
}


def _coerce(spec: tuple, v):
    kind = spec[0]
    if kind == "bool":
        return bool(v)
    if kind == "str":
        return str(v).strip()[:40] or "Szene"
    if kind == "dir":
        return -1 if int(v) < 0 else 1
    if kind == "hue":
        return float(v) % 1.0
    if kind == "mult":
        return min(MULTS, key=lambda m: abs(m - float(v)))
    if kind == "segments":
        return min(SEGMENTS, key=lambda n: abs(n - int(v)))
    return round(float(np.clip(float(v), spec[1], spec[2])), 4)


def _apply(obj, changes: dict, spec: dict) -> list[str]:
    """Übernimmt bekannte Keys mit Typ-/Bereichsprüfung, gibt geänderte Keys zurück."""
    applied: list[str] = []
    for name, v in changes.items():
        if name == "layers":
            if isinstance(v, dict) and _update_layers(obj.layers, v):
                applied.append(name)
            continue
        if name not in spec:
            continue
        try:
            setattr(obj, name, _coerce(spec[name], v))
        except (TypeError, ValueError):
            continue
        applied.append(name)
    return applied


def _update_layers(layers: dict, patch: dict) -> bool:
    """Merged Teil-Updates je Layer: {"chase": {"on": true, "hue": 0.1}}."""
    changed = False
    for eid, lp in patch.items():
        layer = layers.get(eid)
        if layer is None and _is_pattern_key(eid):
            layer = layers[eid] = _pattern_layer()   # Muster-Layer bei Bedarf anlegen
        if layer is None or not isinstance(lp, dict):
            continue
        for k, v in lp.items():
            if k not in _LAYER_SPEC:
                continue
            try:
                layer[k] = _coerce(_LAYER_SPEC[k], v)
            except (TypeError, ValueError):
                continue
            changed = True
    return changed


def _is_pattern_key(eid: str) -> bool:
    rest = eid[len(PATTERN_PREFIX):] if eid.startswith(PATTERN_PREFIX) else ""
    return 0 < len(rest) <= 16 and rest.isalnum()


def _pattern_layer() -> dict:
    return {"on": False, "level": 1.0, "sync": True, "mult": 1.0, "hz": 2.0}


def accent_hue(hue: float) -> float:
    """Passende Akzentfarbe aus der Palette: Komplementärton, auf die Palette gerastert."""
    target = (hue + 0.5) % 1.0
    dist = [min(abs(h - target), 1.0 - abs(h - target)) for h in _HUES]
    return _HUES[int(np.argmin(dist))]


def _default_layers(on: tuple[str, ...] = ("solid",)) -> dict:
    layers = {e: {"on": e in on, "hue": 0.62, "saturation": 1.0, "color_auto": True, "level": 1.0,
                  "sync": True, "mult": _DEFAULT_MULT[e], "hz": _DEFAULT_MULT[e] * 2.0,
                  "hue2": 0.62, "saturation2": 1.0, "segments": 4, "blink": True, "move": False}
              for e in EFFECTS}
    layers["police"].update({"color_auto": False, "hue": 0.0})  # klassisch Rot/Blau
    return layers


@dataclass
class Look:
    """Effekt-Stapel + Grundfarbe (Live-Pult und Szenen)."""

    layers: dict = field(default_factory=_default_layers)
    hue: float = 0.62            # Grundfarbe (Basis der Auto-Farben)
    saturation: float = 1.0      # 0 = Weiß … 1 = volle Farbe

    def accent(self) -> tuple[float, float]:
        """Akzentfarbe zur Grundfarbe (Muster, Auto-Farben)."""
        if self.saturation < 0.25:  # Grundfarbe (fast) weiß → farbiger Akzent
            return 0.62, 1.0
        return accent_hue(self.hue), max(self.saturation, 0.6)

    def layer_color(self, eid: str) -> tuple[float, float]:
        """Effektive Farbe (hue, sat) eines Layers: eigene oder automatisch passend zur Grundfarbe."""
        layer = self.layers[eid]
        if not layer["color_auto"]:
            return layer["hue"], layer["saturation"]
        if eid in FILL_EFFECTS:
            return self.hue, self.saturation
        return self.accent()

    def layer_color2(self, eid: str) -> tuple[float, float]:
        """Zweitfarbe (Polizei, Verlauf): eigene oder Akzent zur Grundfarbe."""
        layer = self.layers[eid]
        if not layer["color_auto"]:
            return layer["hue2"], layer["saturation2"]
        if self.saturation < 0.25:
            return 0.0, 1.0
        return accent_hue(self.hue), max(self.saturation, 0.6)

    def look_dict(self) -> dict:
        d = {"layers": copy.deepcopy(self.layers), "hue": self.hue, "saturation": self.saturation}
        for eid, layer in d["layers"].items():
            if eid.startswith(PATTERN_PREFIX):
                continue
            layer["eff_hue"], layer["eff_saturation"] = self.layer_color(eid)
            if eid in TWO_COLOR:
                layer["eff_hue2"], layer["eff_saturation2"] = self.layer_color2(eid)
        return d


@dataclass
class Scene(Look):
    id: str = ""
    name: str = "Szene"
    level: float = 1.0           # Szenen-Master

    def update(self, changes: dict) -> list[str]:
        return _apply(self, changes, _SCENE_SPEC)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "level": self.level, **self.look_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "Scene":
        sc = cls(id=str(d.get("id") or uuid.uuid4().hex[:8]), layers=_default_layers(on=()))
        sc.update({k: v for k, v in d.items() if k != "id"})
        return sc


def _scene(name: str, layers: dict, **kw) -> Scene:
    sc = Scene(id=uuid.uuid4().hex[:8], layers=_default_layers(on=()))
    sc.update({"name": name, "layers": layers, **kw})
    return sc


def default_scenes() -> list[Scene]:
    """Start-Szenen beim ersten Start (danach frei änder-/löschbar)."""
    return [
        _scene("Chill", {"solid": {"on": True, "level": 0.35},
                         "wave": {"on": True, "color_auto": False, "hue": 0.75, "mult": 0.25}}, hue=0.62),
        _scene("Warm", {"solid": {"on": True, "level": 0.5},
                        "sparkle": {"on": True, "color_auto": False, "hue": 0.1, "saturation": 0.3, "mult": 0.5}},
               hue=0.083, saturation=0.58),
        _scene("Feuer", {"solid": {"on": True, "level": 0.5},
                         "wave": {"on": True, "color_auto": False, "hue": 0.0, "mult": 0.5},
                         "sparkle": {"on": True, "color_auto": False, "hue": 0.15}}, hue=0.07),
        _scene("Club", {"solid": {"on": True, "level": 0.25}, "chase": {"on": True}}, hue=0.87),
        _scene("Party", {"rainbow": {"on": True, "level": 0.6},
                         "chase": {"on": True, "color_auto": False, "saturation": 0.0}}),
        _scene("Glitzer", {"sparkle": {"on": True, "color_auto": False, "saturation": 0.0, "mult": 2.0}}),
    ]


def _cell(v):
    """Rasterzelle: None (aus) | "base" | "accent" | [hue, sat]."""
    if v in ("base", "accent"):
        return v
    if isinstance(v, (list, tuple)) and len(v) == 2:
        try:
            return [round(float(v[0]) % 1.0, 4), round(float(np.clip(float(v[1]), 0.0, 1.0)), 4)]
        except (TypeError, ValueError):
            return None
    return None


@dataclass
class Pattern:
    """Eigenes Muster (Sequenzer): Streifen in Segmente geteilt, Schritte nacheinander abgespielt."""

    id: str = ""
    name: str = "Muster"
    segments: int = 8
    transition: str = "hard"     # hard | soft (weich überblenden zwischen Schritten)
    steps: list = field(default_factory=list)            # [Schritt][Segment] → Zelle

    def update(self, changes: dict) -> list[str]:
        applied: list[str] = []
        if "name" in changes:
            self.name = str(changes["name"]).strip()[:40] or "Muster"
            applied.append("name")
        if changes.get("transition") in ("hard", "soft"):
            self.transition = changes["transition"]
            applied.append("transition")
        if "segments" in changes:
            try:
                self.segments = int(np.clip(int(changes["segments"]), 1, MAX_PATTERN_SEGMENTS))
                applied.append("segments")
            except (TypeError, ValueError):
                pass
        if isinstance(changes.get("steps"), list):
            self.steps = [list(row) if isinstance(row, list) else [] for row in changes["steps"][:MAX_PATTERN_STEPS]]
            applied.append("steps")
        # Raster immer auf segments × (≥1 Schritt) normalisieren.
        rows = [[_cell(c) for c in row[: self.segments]] for row in self.steps] or [[]]
        self.steps = [row + [None] * (self.segments - len(row)) for row in rows]
        return applied

    @classmethod
    def from_dict(cls, d: dict) -> "Pattern":
        pat = cls(id=str(d.get("id") or uuid.uuid4().hex[:8]))
        pat.update({k: v for k, v in d.items() if k != "id"})
        return pat


def _pattern(name: str, segments: int, steps: list, transition: str = "hard") -> Pattern:
    pat = Pattern(id=uuid.uuid4().hex[:8])
    pat.update({"name": name, "segments": segments, "steps": steps, "transition": transition})
    return pat


def default_patterns() -> list[Pattern]:
    """Beispiel-Muster beim ersten Start (zeigen, was der Sequenzer kann)."""
    B, A, _ = "base", "accent", None
    run = [[B if i == k else _ for i in range(8)] for k in range(8)]
    out = [[_, _, _, B, B, _, _, _], [_, _, B, A, A, B, _, _], [_, B, A, _, _, A, B, _], [B, A, _, _, _, _, A, B]]
    return [
        _pattern("Lauflicht", 8, run),
        _pattern("Zweifarb-Wechsel", 4, [[B, A, B, A], [A, B, A, B]]),
        _pattern("Mitte → außen", 8, out, "soft"),
    ]


@dataclass
class ManualState(Look):
    brightness: float = 1.0      # Pult-Dimmer
    direction: int = 1           # +1 / -1
    mirror: bool = False         # Effekte von der Mitte aus gespiegelt
    beat_sync: bool = False      # Beat-Pump: Helligkeit pumpt auf jeden Beat
    bpm: float = 120.0           # globales Tempo (getappt)
    music_sync: bool = False     # globales Tempo folgt live der erkannten Musik-BPM
    strobe_on: bool = False
    strobe_hz: float = 8.0       # eigenes Strobe-Tempo
    strobe_sync: bool = False    # True = Strobe folgt globalem Tempo × strobe_mult
    strobe_mult: float = 2.0
    strobe_white: bool = True    # weiß blitzen (sonst die Effekte takten)
    strobe_alt: bool = False     # Strips abwechselnd blitzen
    blinder_fade: float = 1.5    # s Fade-out nach dem Loslassen
    bump_gain: float = 0.6       # Bump: Stärke des Pulses (wie BeatPulse im Auto-Modus)
    bump_decay: float = 0.16     # Bump: Abklingzeit in s
    bump_beat: bool = False      # Bump automatisch auf jeden globalen Beat
    scene_fade: float = 1.0      # s Ein-/Ausblenden der Szenen
    scene_exclusive: bool = False  # True = immer nur eine Szene aktiv (Überblendung)
    scenes: dict = field(default_factory=dict)           # id → Scene
    scene_order: list = field(default_factory=list)
    active_scenes: list = field(default_factory=list)
    patterns: dict = field(default_factory=dict)         # id → Pattern (eigene Muster)
    pattern_order: list = field(default_factory=list)
    # Halte-Buttons (nicht persistiert)
    blackout: bool = False
    blinder: bool = False
    flash: bool = False

    def update(self, changes: dict) -> list[str]:
        return _apply(self, changes, _STATE_SPEC)

    # ── Szenen ──
    def scene_create(self, name: str = "", from_live: bool = False) -> Scene:
        sc = Scene(id=uuid.uuid4().hex[:8], layers=_default_layers(on=()))
        if from_live:
            sc.layers, sc.hue, sc.saturation = copy.deepcopy(self.layers), self.hue, self.saturation
        sc.update({"name": name or f"Szene {len(self.scenes) + 1}"})
        self.scenes[sc.id] = sc
        self.scene_order.append(sc.id)
        return sc

    def scene_delete(self, sid: str) -> bool:
        if self.scenes.pop(sid, None) is None:
            return False
        self.scene_order = [s for s in self.scene_order if s != sid]
        self.active_scenes = [s for s in self.active_scenes if s != sid]
        return True

    def scene_toggle(self, sid: str, on: bool | None = None) -> bool:
        if sid not in self.scenes:
            return False
        active = sid in self.active_scenes
        on = (not active) if on is None else bool(on)
        if on and self.scene_exclusive:
            self.active_scenes = [sid]
        elif on and not active:
            self.active_scenes = [*self.active_scenes, sid]
        elif not on:
            self.active_scenes = [s for s in self.active_scenes if s != sid]
        return True

    def scene_move(self, sid: str, delta: int) -> bool:
        if sid not in self.scene_order:
            return False
        i = self.scene_order.index(sid)
        j = max(0, min(len(self.scene_order) - 1, i + int(delta)))
        self.scene_order.insert(j, self.scene_order.pop(i))
        return True

    # ── Eigene Muster ──
    def pattern_create(self, name: str = "", copy_of: str = "") -> Pattern | None:
        src = self.patterns.get(copy_of)
        if copy_of and src is None:
            return None
        if src:
            pat = Pattern.from_dict({**asdict(src), "id": uuid.uuid4().hex[:8], "name": name or f"{src.name} (Kopie)"})
        else:
            B, A, _ = "base", "accent", None
            pat = _pattern(name or f"Muster {len(self.patterns) + 1}", 8,
                           [[B, _] * 4, [_, A] * 4])
        self.patterns[pat.id] = pat
        self.pattern_order.append(pat.id)
        return pat

    def pattern_delete(self, pid: str) -> bool:
        if self.patterns.pop(pid, None) is None:
            return False
        self.pattern_order = [p for p in self.pattern_order if p != pid]
        key = PATTERN_PREFIX + pid
        for look in (self, *self.scenes.values()):   # Muster aus allen Looks entfernen
            look.layers.pop(key, None)
        return True

    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if k not in ("layers", "scenes", "patterns")}
        d.update(self.look_dict())
        d["scenes"] = {sid: sc.to_dict() for sid, sc in self.scenes.items()}
        d["patterns"] = {pid: asdict(pat) for pid, pat in self.patterns.items()}
        return d

    # ── Persistenz (ohne Halte-Buttons) ──
    @classmethod
    def load(cls, path: str | os.PathLike) -> "ManualState":
        st = cls()
        data: dict = {}
        p = Path(path)
        if p.is_file():
            try:
                data = json.loads(p.read_text())
            except (OSError, ValueError):
                data = {}
        st.update({k: v for k, v in data.items() if k not in _MOMENTARY})
        # Altes Format (ein einzelner Effekt) → als aktiven Layer übernehmen.
        if "layers" not in data and data.get("effect") in EFFECTS:
            for eid, layer in st.layers.items():
                layer["on"] = eid == data["effect"]
        if "scenes" in data:
            for raw in data.get("scenes") or []:
                sc = Scene.from_dict(raw)
                st.scenes[sc.id] = sc
                st.scene_order.append(sc.id)
            st.active_scenes = [s for s in data.get("active_scenes", []) if s in st.scenes]
        else:
            for sc in default_scenes():
                st.scenes[sc.id] = sc
                st.scene_order.append(sc.id)
        raw_patterns = data["patterns"] if "patterns" in data else [asdict(p) for p in default_patterns()]
        for raw in raw_patterns or []:
            pat = Pattern.from_dict(raw)
            st.patterns[pat.id] = pat
            st.pattern_order.append(pat.id)
        # Muster-Layer, deren Muster fehlt, verwerfen.
        for look in (st, *st.scenes.values()):
            for key in [k for k in look.layers if k.startswith(PATTERN_PREFIX) and k[2:] not in st.patterns]:
                del look.layers[key]
        return st

    def save(self, path: str | os.PathLike) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in asdict(self).items()
                if k not in (*_MOMENTARY, "scenes", "scene_order", "patterns", "pattern_order")}
        data["scenes"] = [asdict(self.scenes[sid]) for sid in self.scene_order if sid in self.scenes]
        data["patterns"] = [asdict(self.patterns[pid]) for pid in self.pattern_order if pid in self.patterns]
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, p)  # atomarer Write


def _rgb(hue: float, sat: float) -> np.ndarray:
    return hsv_to_rgb(np.array([hue % 1.0]), sat, np.ones(1))[0].astype(np.float32)


class _LookRenderer:
    """Laufzeit-Zustand eines Looks (Phasen mit eigenem Tempo, Funkel-Puffer)."""

    def __init__(self, pixels: int, rng: np.random.Generator) -> None:
        self.pixels = pixels
        self.rng = rng
        self.gain = 0.0                                  # Szenen-Ein-/Ausblendung
        self._phases: dict[str, float] = {}
        self._ph: dict[str, float] = {}
        self._sparkle = np.zeros(pixels, dtype=np.float32)
        self._sparkle_cycle = 0

    def advance(self, look: Look, dt: float, beats: float) -> None:
        for eid, layer in look.layers.items():
            if layer["sync"]:
                self._ph[eid] = beats * layer["mult"]
            else:
                self._phases[eid] = (self._phases.get(eid, 0.0) + dt * layer["hz"]) % 4096.0
                self._ph[eid] = self._phases[eid]

    def fills(self, canvas: np.ndarray, look: Look, x: np.ndarray, gain: float) -> None:
        for eid in FILL_EFFECTS:
            layer = look.layers[eid]
            if layer["on"] and layer["level"] > 0.0:
                canvas += self._fill(eid, x, self._ph[eid], look) * (layer["level"] * gain)

    def overlays(self, canvas: np.ndarray, look: Look, x: np.ndarray, gain: float,
                 dt: float, bpm: float, patterns: dict | None = None) -> None:
        for eid in OVERLAY_EFFECTS:
            layer = look.layers[eid]
            if eid == "police" and layer["on"] and layer["level"] > 0.0:
                a1, a2 = self._police(x, self._ph[eid], layer)
                g = layer["level"] * gain
                a1, a2 = a1 * g, a2 * g
                canvas *= (1.0 - a1 - a2)[:, None]
                canvas += a1[:, None] * _rgb(*look.layer_color(eid)) + a2[:, None] * _rgb(*look.layer_color2(eid))
                continue
            if layer["on"] and layer["level"] > 0.0:
                alpha = self._alpha(eid, x, self._ph[eid], dt, layer, bpm) * (layer["level"] * gain)
                canvas *= (1.0 - alpha)[:, None]
                canvas += alpha[:, None] * _rgb(*look.layer_color(eid))
        if not look.layers["sparkle"]["on"]:
            self._sparkle[:] = 0.0
        # Eigene Muster (Sequenzer) obenauf, in der Reihenfolge des Looks.
        for key, layer in look.layers.items():
            if not key.startswith(PATTERN_PREFIX) or not layer["on"] or layer["level"] <= 0.0:
                continue
            pat = (patterns or {}).get(key[len(PATTERN_PREFIX):])
            if pat is None:
                continue
            rgb, alpha = self._pattern(pat, look, x, self._ph.get(key, 0.0))
            alpha *= layer["level"] * gain
            canvas *= (1.0 - alpha)[:, None]
            canvas += rgb * alpha[:, None]

    @staticmethod
    def _step_colors(row: list, look: Look) -> tuple[np.ndarray, np.ndarray]:
        """Ein Sequenzer-Schritt → Farben (seg, 3) und Deckkraft (seg,)."""
        rgb = np.zeros((len(row), 3), dtype=np.float32)
        alpha = np.zeros(len(row), dtype=np.float32)
        base, acc = (look.hue, look.saturation), look.accent()
        for i, cell in enumerate(row):
            if cell is None:
                continue
            hs = base if cell == "base" else acc if cell == "accent" else cell
            rgb[i] = _rgb(hs[0], hs[1])
            alpha[i] = 1.0
        return rgb, alpha

    def _pattern(self, pat: "Pattern", look: Look, x: np.ndarray, ph: float) -> tuple[np.ndarray, np.ndarray]:
        """Ein Zyklus = ein Schritt. Hart: Schritte springen; weich: überblenden."""
        n = len(pat.steps)
        pos = ph % n
        i = int(pos)
        rgb, alpha = self._step_colors(pat.steps[i], look)
        if pat.transition == "soft":
            f = pos - i
            f = f * f * (3.0 - 2.0 * f)                      # smoothstep
            rgb2, alpha2 = self._step_colors(pat.steps[(i + 1) % n], look)
            a = alpha * (1.0 - f) + alpha2 * f
            # Farben deckkraft-gewichtet mischen (Aus-Zellen färben nicht ab).
            num = rgb * (alpha * (1.0 - f))[:, None] + rgb2 * (alpha2 * f)[:, None]
            rgb = num / np.maximum(a, 1e-6)[:, None]
            alpha = a
        seg = np.minimum((x * pat.segments).astype(int), pat.segments - 1)
        return rgb[seg], alpha[seg].copy()

    def _fill(self, eid: str, x: np.ndarray, ph: float, look: Look) -> np.ndarray:
        """Flächen-Layer → (pixels, 3). Ein Zyklus = ein Tempo-Schritt."""
        hue, sat = look.layer_color(eid)
        if eid == "solid":
            return np.broadcast_to(_rgb(hue, sat), (self.pixels, 3))
        if eid == "gradient":
            layer = look.layers[eid]
            # statisch: Farbe 1 links → Farbe 2 rechts; bewegt: 1→2→1 nahtlos durchlaufend
            m = 0.5 - 0.5 * np.cos(2.0 * np.pi * (x - ph * 0.5)) if layer["move"] else x
            h2, s2 = look.layer_color2(eid)
            # Weiß hat keinen Farbton → den der anderen Seite nehmen (sonst Farbstich im Verlauf).
            if sat < 0.05:
                hue = h2
            elif s2 < 0.05:
                h2 = hue
            dh = ((h2 - hue + 0.5) % 1.0) - 0.5          # kürzester Weg über den Farbkreis
            return hsv_to_rgb((hue + dh * m) % 1.0, sat + (s2 - sat) * m, np.ones_like(x))
        if eid == "breathe":
            b = 0.08 + 0.92 * (0.5 - 0.5 * np.cos(2.0 * np.pi * ph))
            return np.broadcast_to(_rgb(hue, sat) * b, (self.pixels, 3))
        if eid == "rainbow":
            return hsv_to_rgb((x + ph * 0.25) % 1.0, 1.0, np.ones_like(x))
        # cycle: Farbwechsel ab der Layer-Farbe (etwas Sättigung, sonst sieht man nichts)
        return np.broadcast_to(_rgb(hue + ph * 0.25, max(sat, 0.6)), (self.pixels, 3))

    @staticmethod
    def _police(x: np.ndarray, ph: float, layer: dict) -> tuple[np.ndarray, np.ndarray]:
        """Polizei: Streifen in Segmente teilen, jedes zweite gepaart (1+3 / 2+4 …).

        Pro Zyklus ist erst Gruppe A (Farbe 1), dann Gruppe B (Farbe 2) dran —
        mit Doppelblitz wie ein Blaulicht, sonst tauschen beide Farben die Plätze.
        """
        seg = layer["segments"]
        group = np.minimum((x * seg).astype(int), seg - 1) % 2
        c = ph % 1.0
        half = 0 if c < 0.5 else 1
        if layer["blink"]:
            u = (c % 0.5) * 2.0
            on = u < 0.22 or 0.32 <= u < 0.54
            a1 = ((group == 0) & (half == 0) & on).astype(np.float32)
            a2 = ((group == 1) & (half == 1) & on).astype(np.float32)
        else:
            a1 = (group == half).astype(np.float32)
            a2 = 1.0 - a1
        return a1, a2

    def _alpha(self, eid: str, x: np.ndarray, ph: float, dt: float, layer: dict, bpm: float) -> np.ndarray:
        """Muster-Layer → Deckkraft je Pixel [0,1]. Ein Zyklus = ein Tempo-Schritt."""
        if eid == "wave":
            return (0.5 + 0.5 * np.sin(2.0 * np.pi * (x * 2.0 - ph))).astype(np.float32)
        if eid == "chase":
            # 3 Kometen mit Schweif; pro Zyklus rückt jeder um einen Abstand vor.
            u = (x * 3.0 - ph) % 1.0
            return np.exp(-(1.0 - u) / 0.12).astype(np.float32)
        if eid == "theater":
            idx = (x * (self.pixels - 1)).astype(int)
            return (((idx + int(ph * 3.0)) % 3) == 0).astype(np.float32)
        # sparkle: Dichte folgt dem Tempo, zusätzlich ein Schub auf jedem Zyklus
        rate = bpm / 60.0 * layer["mult"] if layer["sync"] else layer["hz"]
        self._sparkle *= max(0.0, 1.0 - dt * 6.0)
        n = self.rng.poisson(max(0.05, self.pixels * dt * (0.2 + 0.6 * rate)))
        if int(ph) != self._sparkle_cycle:
            self._sparkle_cycle = int(ph)
            n += self.pixels // 20
        if n:
            self._sparkle[self.rng.integers(0, self.pixels, size=n)] = 1.0
        return self._sparkle


class ManualEngine:
    def __init__(self, state: ManualState, pixels: int, fixtures: int = 2, seed: int | None = None) -> None:
        self.state = state
        self.pixels = pixels
        self.fixtures = max(1, fixtures)
        self.rng = np.random.default_rng(seed)
        self._canvas = np.zeros((pixels, 3), dtype=np.float32)
        self._out = FrameBuffer(pixels)
        self._live = _LookRenderer(pixels, self.rng)
        self._scene_r: dict[str, _LookRenderer] = {}
        self._beats = 0.0          # globale Beat-Position; Tap setzt sie auf 0
        self._last_beat = 0
        self._beat_env = 0.0
        self._strobe_phase = 0.0
        self._strobe_count = 0
        self._strobe_until = -1.0
        self._strobe_was_on = False
        self._blinder_level = 0.0  # 1 = volles Warmweiß, fadet nach dem Loslassen aus
        self._bump = 0.0           # Bump-Puls 1 → 0
        self.bpm_eff = state.bpm

    def tap(self) -> None:
        """Tap = Beat-Anfang: alles Synchrone phasengenau auf den Tap ausrichten."""
        self._beats = 0.0
        self._last_beat = 0

    def bump(self) -> None:
        """Bump-Button: heller Puls über dem Inhalt, klingt über bump_decay ab."""
        self._bump = 1.0

    def render(self, a: AnalysisFrame, t: float, dt: float, master: float = 1.0) -> tuple[FrameBuffer, list[float]]:
        s = self.state
        canvas = self._canvas
        canvas[:] = 0.0
        gains = [1.0] * self.fixtures

        # Globales Tempo (getappt oder live aus der Musik).
        self.bpm_eff = a.bpm if (s.music_sync and a.bpm >= 40) else s.bpm
        self._beats += dt * self.bpm_eff / 60.0
        if s.music_sync and a.beat_now:  # Phase sanft auf erkannte Beats ziehen
            frac = self._beats % 1.0
            self._beats += (1.0 - frac) * 0.5 if frac > 0.5 else -frac * 0.5

        x = np.linspace(0.0, 1.0, self.pixels, dtype=np.float32)
        if s.mirror:
            x = 1.0 - np.abs(2.0 * x - 1.0)
        if s.direction < 0:
            x = 1.0 - x

        # Live-Pult + aktive (bzw. gerade ausblendende) Szenen komponieren.
        stack: list[tuple[_LookRenderer, Look, float]] = [(self._live, s, 1.0)]
        step = dt / s.scene_fade if s.scene_fade > 0 else 1.0
        for sid in s.scene_order:
            sc = s.scenes.get(sid)
            if sc is None:
                continue
            r = self._scene_r.get(sid)
            target = 1.0 if sid in s.active_scenes else 0.0
            if r is None:
                if not target:
                    continue
                r = self._scene_r[sid] = _LookRenderer(self.pixels, self.rng)
            r.gain = min(target, r.gain + step) if target > r.gain else max(target, r.gain - step)
            if r.gain <= 0.0 and not target:
                del self._scene_r[sid]
                continue
            stack.append((r, sc, r.gain * sc.level))
        for sid in [k for k in self._scene_r if k not in s.scenes]:
            del self._scene_r[sid]

        for r, look, _ in stack:
            r.advance(look, dt, self._beats)
        for r, look, g in stack:
            r.fills(canvas, look, x, g)
        np.clip(canvas, 0.0, 1.0, out=canvas)
        for r, look, g in stack:
            r.overlays(canvas, look, x, g, dt, self.bpm_eff, s.patterns)

        # Beat-Pump auf dem globalen Beat.
        beat = int(self._beats)
        if beat != self._last_beat:
            self._last_beat = beat
            self._beat_env = 1.0
            if s.bump_beat:
                self._bump = 1.0
        else:
            self._beat_env *= 0.85
        if s.beat_sync:
            canvas *= 0.25 + 0.75 * self._beat_env

        # Bump: additiver Puls in hellem Pastell der Grundfarbe (wie BeatPulse, §6).
        if self._bump > 0.001:
            canvas += _rgb(s.hue, 0.2) * (s.bump_gain * self._bump)
            np.clip(canvas, 0.0, 1.0, out=canvas)
            self._bump *= float(np.exp(-dt / s.bump_decay))

        if s.strobe_on:
            gains = self._strobe(canvas, t, dt) or gains
        self._strobe_was_on = s.strobe_on

        canvas *= s.brightness  # Pult-Dimmer (Blinder bleibt davon unberührt)

        if s.flash:
            canvas[:] = _rgb(s.hue, s.saturation)
            gains = [1.0] * self.fixtures

        # Blinder: gedrückt → sofort voll; losgelassen → linear über blinder_fade aus,
        # dabei wird der darunterliegende Inhalt wieder sichtbar.
        if s.blinder:
            self._blinder_level = 1.0
        elif self._blinder_level > 0.0:
            self._blinder_level = max(0.0, self._blinder_level - dt / max(0.1, s.blinder_fade))
        bl = self._blinder_level
        if bl > 0.0:
            canvas *= 1.0 - bl
            canvas += _WARM_WHITE * bl
            gains = [1.0] * self.fixtures

        if s.blackout:
            canvas[:] = 0.0

        np.clip(canvas, 0.0, 1.0, out=canvas)
        self._out.data = (canvas * 255.0).astype(np.uint8)
        self._out.brightness = master
        return self._out, gains

    def _strobe(self, canvas: np.ndarray, t: float, dt: float) -> list[float] | None:
        """Kurze, knackige Blitze: jeder Zyklus startet einen Blitz fester Länge."""
        s = self.state
        if s.strobe_sync:
            hz = self.bpm_eff / 60.0 * s.strobe_mult
            count = int(self._beats * s.strobe_mult)
            fire = count != self._strobe_count
            self._strobe_count = count
        else:
            hz = s.strobe_hz
            if not self._strobe_was_on:
                self._strobe_phase = 1.0  # beim Einschalten sofort blitzen
            self._strobe_phase += dt * hz
            fire = self._strobe_phase >= 1.0
            if fire:
                self._strobe_phase %= 1.0
                self._strobe_count += 1
        if fire or not self._strobe_was_on:
            self._strobe_until = t + max(0.03, min(0.08, 0.5 / max(hz, 1e-3)))
        if t < self._strobe_until:
            if s.strobe_white:
                canvas[:] = 1.0
            if s.strobe_alt and self.fixtures >= 2:
                lit = self._strobe_count % self.fixtures
                return [1.0 if i == lit else 0.0 for i in range(self.fixtures)]
            return None
        canvas[:] = 0.0
        return [0.0] * self.fixtures
