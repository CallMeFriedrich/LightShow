"""Realtime-Audio-Analyse (reine NumPy-Berechnung).

Liefert alle Features, die das Effekt-Regelwerk benötigt:

* **Spektrum** (log-Bänder) für den Spectrum-Layer
* **Bass / Mitten / Höhen** adaptiv normiert [0, 1] (Bass-Passagen, Wash)
* **energy** (geglättete Gesamtenergie) und **mood** (Spectral-Centroid-Proxy,
  langsam — Song-Charakter)
* **Beat/BPM/Onset** und **highs_onset** (Sparkles)
* **Realtime-Drop** (Energiesprung nach Build-up)
* **song_time / silence** (heuristischer Song-Start via Stille-Lücken)

Bewusst leichtgewichtig (kein librosa/aubio) für < 10 ms je Frame.
"""
from __future__ import annotations

import numpy as np

from .models import AnalysisFrame, PCMFrame

_IDLE_RMS = 0.002  # Idle-Schwelle (§8)
_SILENCE_GAP = 1.2  # s Stille → neuer Song (song_time reset)


class _Adaptive:
    """Adaptive Normierung auf [0,1] über einen langsam fallenden Referenzwert."""

    def __init__(self, decay: float = 0.9995, floor: float = 1e-6) -> None:
        self.ref = floor
        self.decay = decay
        self.floor = floor

    def norm(self, value: float) -> float:
        self.ref = max(self.ref * self.decay, value, self.floor)
        return min(1.0, value / self.ref)


class Analyzer:
    def __init__(
        self,
        sample_rate: int,
        fft_size: int = 2048,
        n_bands: int = 16,
        frame_rate: float = 40.0,
    ) -> None:
        self.sr = sample_rate
        self.fft_size = fft_size
        self.n_bands = n_bands
        self.window = np.hanning(fft_size).astype(np.float32)
        self._buf = np.zeros(fft_size, dtype=np.float32)

        self._freqs = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)

        # Log-verteilte Band-Kanten für das Spektrum.
        edges = np.logspace(np.log10(20.0), np.log10(sample_rate / 2), n_bands + 1)
        self._band_idx = [
            (int(np.searchsorted(self._freqs, edges[i])), int(np.searchsorted(self._freqs, edges[i + 1])))
            for i in range(n_bands)
        ]

        # Frequenzgruppen (Bass/Mitten/Höhen).
        self._bass_mask = (self._freqs >= 20) & (self._freqs < 160)
        self._mid_mask = (self._freqs >= 160) & (self._freqs < 2000)
        self._high_mask = self._freqs >= 2000

        # Adaptive Normierer.
        self._n_bass = _Adaptive()
        self._n_mid = _Adaptive()
        self._n_high = _Adaptive()
        self._n_energy = _Adaptive(decay=0.9998)

        # Onset / Beat.
        self._prev_mag = np.zeros(self._freqs.size, dtype=np.float32)
        self._flux_norm = 1e-6
        self._high_flux_norm = 1e-6
        self._band_smooth = np.zeros(n_bands, dtype=np.float32)

        # Beat-Timing.
        self._env_len = max(64, int(frame_rate * 6))
        self._env = np.zeros(self._env_len, dtype=np.float32)
        self._frame_rate = frame_rate
        self._bpm = 0.0
        self._flux_avg = 0.0
        self._last_beat_i = -999
        self._i = 0

        # Song-Charakter (langsam geglättet).
        self._energy = 0.0
        self._mood = 0.3
        self._block_dt = fft_size / sample_rate  # ~ Zeitschritt je Analyse-Frame

        # Zeit / Stille.
        self._t = 0.0
        self._song_start = 0.0
        self._in_silence = True
        self._silence_since = 0.0

        # Drop-Erkennung.
        self._energy_baseline = 0.0
        self._last_drop_t = -999.0

    def process(self, frame: PCMFrame) -> AnalysisFrame:
        mono = frame.mono.astype(np.float32)
        n = mono.shape[0]
        self._block_dt = n / self.sr
        self._t += self._block_dt

        if n >= self.fft_size:
            self._buf[:] = mono[-self.fft_size :]
        else:
            self._buf = np.roll(self._buf, -n)
            self._buf[-n:] = mono

        rms = float(np.sqrt(np.mean(self._buf**2)))
        peak = float(np.max(np.abs(self._buf)))

        mag = np.abs(np.fft.rfft(self._buf * self.window)).astype(np.float32)

        bands = self._compute_bands(mag)
        bass = self._n_bass.norm(float(np.mean(mag[self._bass_mask])))
        mids = self._n_mid.norm(float(np.mean(mag[self._mid_mask])))
        highs = self._n_high.norm(float(np.mean(mag[self._high_mask])))

        onset, highs_onset = self._compute_onset(mag)
        beat_now = self._detect_beat(onset)
        if self._i % max(1, int(self._frame_rate // 2)) == 0:
            self._bpm = self._estimate_bpm()

        energy = self._update_energy(rms)
        mood = self._update_mood(mag)
        drop_now = self._detect_drop(energy, beat_now)
        silence, song_time = self._update_time(rms)

        self._i += 1
        return AnalysisFrame(
            bands=bands,
            rms=rms,
            peak=peak,
            bass=bass,
            mids=mids,
            highs=highs,
            energy=energy,
            mood=mood,
            bpm=self._bpm,
            beat_now=beat_now,
            onset=onset,
            highs_onset=highs_onset,
            drop_now=drop_now,
            song_time=song_time,
            silence=silence,
        )

    # ── Teilberechnungen ──
    def _compute_bands(self, mag: np.ndarray) -> list[float]:
        raw = np.empty(self.n_bands, dtype=np.float32)
        for b, (lo, hi) in enumerate(self._band_idx):
            hi = max(hi, lo + 1)
            raw[b] = float(np.mean(mag[lo:hi]))
        raw = np.log1p(raw)
        raw /= float(np.max(raw)) or 1.0
        rise = raw > self._band_smooth
        self._band_smooth = np.where(
            rise,
            0.6 * self._band_smooth + 0.4 * raw,
            0.85 * self._band_smooth + 0.15 * raw,
        )
        return self._band_smooth.tolist()

    def _compute_onset(self, mag: np.ndarray) -> tuple[float, float]:
        diff = mag - self._prev_mag
        pos = np.where(diff > 0, diff, 0.0)
        flux = float(np.sum(pos))
        high_flux = float(np.sum(pos[self._high_mask]))
        self._prev_mag = mag
        self._flux_norm = max(self._flux_norm * 0.999, flux, 1e-6)
        self._high_flux_norm = max(self._high_flux_norm * 0.999, high_flux, 1e-6)
        return min(1.0, flux / self._flux_norm), min(1.0, high_flux / self._high_flux_norm)

    def _detect_beat(self, onset: float) -> bool:
        self._env[self._i % self._env_len] = onset
        self._flux_avg = 0.99 * self._flux_avg + 0.01 * onset
        if onset > self._flux_avg * 1.6 and onset > 0.25:
            if self._i - self._last_beat_i > self._frame_rate * 0.25:  # max ~240 BPM
                self._last_beat_i = self._i
                return True
        return False

    def _estimate_bpm(self) -> float:
        env = self._env - self._env.mean()
        if np.allclose(env, 0):
            return self._bpm
        corr = np.correlate(env, env, mode="full")[env.size - 1 :]
        min_lag = int(self._frame_rate * 60.0 / 200.0)
        max_lag = min(int(self._frame_rate * 60.0 / 60.0), corr.size - 1)
        if max_lag <= min_lag:
            return self._bpm
        lag = min_lag + int(np.argmax(corr[min_lag : max_lag + 1]))
        if lag <= 0:
            return self._bpm
        bpm = 60.0 * self._frame_rate / lag
        return round(0.7 * self._bpm + 0.3 * bpm, 1) if self._bpm else round(bpm, 1)

    def _update_energy(self, rms: float) -> float:
        raw = self._n_energy.norm(rms)
        # schnelle Glättung, damit energy responsiv bleibt
        self._energy = 0.7 * self._energy + 0.3 * raw
        return self._energy

    def _update_mood(self, mag: np.ndarray) -> float:
        total = float(np.sum(mag)) or 1e-6
        centroid = float(np.sum(self._freqs * mag)) / total
        # Centroid relativ zu ~5 kHz als „hell/valenz"-Proxy.
        bright = min(1.0, centroid / 5000.0)
        raw = 0.6 * bright + 0.4 * self._energy
        # sehr langsam glätten (~8 s) → stabiler Song-Charakter
        alpha = 1.0 - float(np.exp(-self._block_dt / 8.0))
        self._mood += alpha * (raw - self._mood)
        return self._mood

    def _detect_drop(self, energy: float, beat_now: bool) -> bool:
        # langsame Baseline (~4 s)
        alpha = 1.0 - float(np.exp(-self._block_dt / 4.0))
        self._energy_baseline += alpha * (energy - self._energy_baseline)
        surge = energy - self._energy_baseline
        if (
            beat_now
            and energy > 0.5
            and surge > 0.22
            and (self._t - self._last_drop_t) > 4.0
        ):
            self._last_drop_t = self._t
            return True
        return False

    def _update_time(self, rms: float) -> tuple[bool, float]:
        silent = rms < _IDLE_RMS
        if silent:
            if not self._in_silence:
                self._silence_since = self._t
            self._in_silence = True
        else:
            if self._in_silence and (self._t - self._silence_since) > _SILENCE_GAP:
                self._song_start = self._t  # neuer Song erkannt
            self._in_silence = False
        return silent, self._t - self._song_start
