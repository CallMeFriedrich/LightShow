// Tap-Tempo: misst im Browser (genauer als übers Netz) den Abstand der letzten Taps.
// onTap(hz | null) wird bei jedem Tap aufgerufen; hz ist null, solange erst ein Tap da ist.
export function createTapper(onTap, { maxTaps = 6, resetMs = 2500 } = {}) {
  let taps = [];
  return function tap() {
    const now = performance.now();
    if (taps.length && now - taps[taps.length - 1] > resetMs) taps = [];  // Pause → neu messen
    taps.push(now);
    taps = taps.slice(-maxTaps);
    if (taps.length < 2) return onTap(null);
    const avg = (taps[taps.length - 1] - taps[0]) / (taps.length - 1);
    onTap(1000 / avg);
  };
}

export const MULT_LABELS = { 0.125: "1/8", 0.25: "1/4", 0.5: "1/2", 1: "1", 2: "2", 4: "4" };
export const fmtHz = (hz) => (hz >= 10 ? hz.toFixed(0) : hz >= 1 ? hz.toFixed(1) : hz.toFixed(2));
