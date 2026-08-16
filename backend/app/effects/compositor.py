"""ShowEngine — komponiert die Licht-Show Frame für Frame (§1–§8).

Reihenfolge pro Frame:
1. Show-Inhalt rendern (Idle · Bass-Passage · Normal: Base→Spectrum→Feature→Overlays)
2. Sektor-Maske anwenden (nach Drop kurzzeitig „full" übersteuert, §2)
3. Anti-Flicker-Glättung (``smoothing``) auf den Inhalt
4. Strobe (crisp, überschreibt)
5. Blackout **ganz zuletzt** (gewinnt immer, harter Schnitt)
Danach Quantisierung → uint8 und Master-Helligkeit.
"""
from __future__ import annotations

import threading

import numpy as np

from ..audio.models import AnalysisFrame
from ..output.base import FrameBuffer
from .bass import BassBounce, BlockToggle
from .baselayers import Ambient, BassWash, Idle, Spectrum
from .base import RenderContext
from .config import ShowConfig
from .output_fx import Blackout, Strobe
from .overlays import BeatPulse, Sparkle
from .scene import SceneManager

_DEFAULT_BASE_HUE = 0.58  # bis Album-Cover-Farbe verfügbar ist (Slice 2)
_DROP_FULL_HOLD = 2.0     # s: nach Drop ganzer Streifen an (§2)

# Verhalten je Songabschnitt: Intensitäts-/Helligkeits-Faktor, Feature-Pool,
# ganzer Streifen (full), Sektor-Kontrast.
_SECTION_PARAMS = {
    "intro": {"intensity": 0.40, "bright": 0.65, "pool": "calm", "full": False},
    "build": {"intensity": 1.00, "bright": 1.00, "pool": "energetic", "full": False},
    "drop":  {"intensity": 1.30, "bright": 1.00, "pool": "energetic", "full": True},
    "verse": {"intensity": 0.85, "bright": 1.00, "pool": None, "full": False},
    "break": {"intensity": 0.50, "bright": 0.80, "pool": "calm", "full": False},
    "outro": {"intensity": 0.40, "bright": 0.60, "pool": "calm", "full": False},
}


class ShowEngine:
    def __init__(self, cfg: ShowConfig, pixels: int, fixtures: int = 2, seed: int | None = None) -> None:
        self.cfg = cfg
        self.pixels = pixels
        self.fixtures = max(1, fixtures)
        self.rng = np.random.default_rng(seed)
        self._lock = threading.Lock()

        # Layer / Controller (persistenter Zustand).
        self.ambient = Ambient()
        self.basswash = BassWash()
        self.spectrum = Spectrum()
        self.idle = Idle()
        self.beatpulse = BeatPulse()
        self.sparkle = Sparkle(pixels)
        self.scene = SceneManager(self.rng)
        self.strobe = Strobe()
        self.blackout = Blackout()

        # Bass-Passage.
        self._in_bass = False
        self._bass_effect = BlockToggle()

        # Puffer.
        self._canvas = np.zeros((pixels, 3), dtype=np.float32)
        self._prev = np.zeros((pixels, 3), dtype=np.float32)
        self._out = FrameBuffer(pixels)
        self._drop_full_until = -1.0
        self.base_hue = _DEFAULT_BASE_HUE
        self._section = "verse"
        self.status: dict = {}

    # ── Steuer-API ──
    def set_base_hue(self, hue: float) -> None:
        self.base_hue = hue % 1.0

    # ── Render ──
    def render(
        self, a: AnalysisFrame, t: float, dt: float,
        buildup: float = 0.0, predicted_drop: bool = False,
        section: str = "verse", tension: float = 0.0,
    ) -> tuple[FrameBuffer, list[float]]:
        cfg = self.cfg
        drop_eff = a.drop_now or predicted_drop
        sp = _SECTION_PARAMS.get(section, _SECTION_PARAMS["verse"])
        self._section = section

        # Intensität: Grund × mood × Abschnitt × (Build-up/Spannung).
        eff_intensity = min(1.0, cfg.intensity * (0.35 + 0.65 * a.mood)
                            * sp["intensity"] * (1.0 + buildup + 0.5 * tension))
        ctx = RenderContext(
            pixels=self.pixels, t=t, dt=dt, a=a, cfg=cfg,
            eff_intensity=eff_intensity, base_hue=self.base_hue,
            direction=self.scene.direction, drop=drop_eff, buildup=max(buildup, tension),
            rng=self.rng,
        )
        canvas = self._canvas
        canvas[:] = 0.0

        bass_passage = False
        if a.silence:
            self.idle.render(canvas, ctx)
        else:
            bass_passage = a.bass > 0.4 and a.highs < 0.22 and a.mids < 0.45
            # Fester Effekt je Abschnitt; wechselt NUR beim Abschnittswechsel.
            self.scene.ensure(section, self.pixels, cfg.section_floor)
            ctx.direction = self.scene.direction
            if bass_passage:
                self._render_bass(canvas, ctx)
            else:
                self._in_bass = False
                self._render_normal(canvas, ctx)

        # Sektor-Maske (nach Drop bzw. im Drop-Abschnitt: full-Override, §2).
        if drop_eff or sp["full"]:
            self._drop_full_until = t + _DROP_FULL_HOLD
        if not a.silence and t >= self._drop_full_until and self.scene.mask is not None:
            canvas *= self.scene.mask[:, None]

        # Anti-Flicker-Glättung des Inhalts (Strobe/Blackout bleiben crisp).
        s = float(np.clip(cfg.smoothing, 0.0, 0.95))
        np.multiply(self._prev, s, out=self._prev)
        self._prev += (1.0 - s) * canvas
        canvas[:] = self._prev

        # Output-Layer: Strobe, dann Blackout (gewinnt zuletzt).
        self.strobe.update(ctx, self.fixtures)
        fixture_gains = self.strobe.apply(canvas, ctx, self.fixtures) or [1.0] * self.fixtures
        black = self.blackout.update(ctx)
        self.blackout.apply(canvas, black)

        # Quantisieren.
        np.clip(canvas, 0.0, 1.0, out=canvas)
        self._out.data = (canvas * 255.0).astype(np.uint8)
        self._out.brightness = cfg.brightness * sp["bright"]

        self.status = {
            "scene": self.scene.feature_name,
            "pattern": self.scene.pattern,
            "section": section,
            "bass_passage": bass_passage,
            "blackout": black,
            "strobe": fixture_gains != [1.0] * self.fixtures or self.strobe._until > t,
            "eff_intensity": round(eff_intensity, 3),
            "base_hue": round(self.base_hue, 3),
            "buildup": round(max(buildup, tension), 3),
            "drop": drop_eff,
        }
        return self._out, fixture_gains

    def _render_normal(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        self.ambient.render(canvas, ctx)
        self.basswash.render(canvas, ctx)
        self.spectrum.render(canvas, ctx)          # prominent, nicht intensity-gedämpft
        self.scene.feature.render(canvas, ctx)     # Feature-Effekt der Szene
        self.beatpulse.render(canvas, ctx)
        self.sparkle.render(canvas, ctx)

    def _render_bass(self, canvas: np.ndarray, ctx: RenderContext) -> None:
        # Basis/Spektrum zurücknehmen, damit der Block/Bounce dominiert (§5).
        self.ambient.render(canvas, ctx)
        self.basswash.render(canvas, ctx)
        self.spectrum.render(canvas, ctx)
        canvas *= 0.25
        if not self._in_bass:
            self._in_bass = True
            use_block = ctx.rng.random() < ctx.cfg.bass_block_chance
            self._bass_effect = BlockToggle() if use_block else BassBounce()
        self._bass_effect.render(canvas, ctx)
