// Farb-Helfer fürs Pult: HSV (volle Helligkeit) → RGB/CSS, Akzentfarbe wie im Backend.
export function hsvToRgb(h, s) {
  const i = Math.floor(h * 6), f = h * 6 - i, p = 1 - s, q = 1 - s * f, t = 1 - s * (1 - f);
  const c = [[1, t, p], [q, 1, p], [p, 1, t], [p, q, 1], [t, p, 1], [1, p, q]][((i % 6) + 6) % 6];
  return c.map((v) => Math.round(v * 255));
}
export const rgbCss = (h, s) => `rgb(${hsvToRgb(h, s).join(",")})`;

// Akzent zur Grundfarbe: Komplementärton, auf die gesättigten Palettenfarben gerastert
// (gleiche Regel wie Look.accent() im Backend).
export function accentOf(hue, sat, palette) {
  if (sat < 0.25) return [0.62, 1];
  const target = (hue + 0.5) % 1;
  const hues = palette.filter((p) => p.saturation >= 1).map((p) => p.hue);
  const dist = (h) => Math.min(Math.abs(h - target), 1 - Math.abs(h - target));
  const best = hues.reduce((a, b) => (dist(b) < dist(a) ? b : a), hues[0] ?? target);
  return [best, Math.max(sat, 0.6)];
}
