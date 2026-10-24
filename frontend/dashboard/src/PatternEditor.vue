<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue";
import ColorPicker from "./ColorPicker.vue";
import { hsvToRgb, rgbCss, accentOf } from "./color.js";

// Muster-Sequenzer: Raster aus Schritten (Zeilen) × Segmenten (Spalten) bemalen.
const props = defineProps({
  pattern: { type: Object, required: true },
  palette: { type: Array, default: () => [] },
  look: { type: Object, required: true },       // Look, dessen Grundfarbe/Akzent gilt
  liveLayer: { type: Object, default: () => ({}) },  // Live-Layer dieses Musters (Tempo, Test)
  bpm: { type: Number, default: 120 },
});
const emit = defineEmits(["change", "close", "delete", "duplicate", "test"]);

const base = computed(() => [props.look.hue ?? 0, props.look.saturation ?? 1]);
const accent = computed(() => accentOf(base.value[0], base.value[1], props.palette));
const resolve = (cell) => (cell === "base" ? base.value : cell === "accent" ? accent.value : cell);
const cellCss = (cell) => (cell == null ? "transparent" : rgbCss(...resolve(cell)));
const same = (a, b) => (a == null && b == null) || a === b ||
  (Array.isArray(a) && Array.isArray(b) && Math.abs(a[0] - b[0]) < 1e-3 && Math.abs(a[1] - b[1]) < 1e-3);

// ── Pinsel ──
const brush = ref("base");                       // null = Radierer
const customColor = ref([0.83, 1]);
const showCustom = ref(false);
const BRUSHES = computed(() => [
  { v: null, label: "Aus", css: "#000" },
  { v: "base", label: "G", title: "Grundfarbe (passt sich der Szene an)", css: rgbCss(...base.value) },
  { v: "accent", label: "A", title: "Akzent (passt sich der Szene an)", css: rgbCss(...accent.value) },
  ...props.palette.map((p) => ({ v: [p.hue, p.saturation], title: p.name, css: rgbCss(p.hue, p.saturation) })),
]);

// ── Raster bearbeiten ──
const steps = computed(() => props.pattern.steps || []);
const setSteps = (rows) => emit("change", { steps: rows });
const copyRows = () => steps.value.map((r) => r.map((c) => (Array.isArray(c) ? [...c] : c)));

let painting = false, paintValue = null;
function cellAt(e) {
  const el = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-cell]");
  return el ? [+el.dataset.r, +el.dataset.c] : null;
}
function paint([r, c]) {
  if (same(steps.value[r]?.[c], paintValue)) return;
  const rows = copyRows();
  rows[r][c] = Array.isArray(paintValue) ? [...paintValue] : paintValue;
  setSteps(rows);
}
function gridDown(e) {
  const rc = cellAt(e);
  if (!rc) return;
  e.currentTarget.setPointerCapture?.(e.pointerId);
  painting = true;
  // Tippen auf eine Zelle in Pinselfarbe → löschen (auch beim Weiterziehen).
  paintValue = same(steps.value[rc[0]][rc[1]], brush.value) ? null : brush.value;
  paint(rc);
}
function gridMove(e) { if (painting) { const rc = cellAt(e); if (rc) paint(rc); } }
function gridUp() { painting = false; }

function rowOp(r, op) {
  const rows = copyRows();
  if (op === "dup") rows.splice(r + 1, 0, rows[r].map((c) => (Array.isArray(c) ? [...c] : c)));
  else if (op === "del" && rows.length > 1) rows.splice(r, 1);
  else if (op === "left") rows[r].push(rows[r].shift());
  else if (op === "right") rows[r].unshift(rows[r].pop());
  else if (op === "up" && r > 0) rows.splice(r - 1, 0, rows.splice(r, 1)[0]);
  setSteps(rows);
}
function addStep(copyLast) {
  const rows = copyRows();
  if (rows.length >= 32) return;
  rows.push(copyLast ? rows[rows.length - 1].map((c) => (Array.isArray(c) ? [...c] : c))
    : Array(props.pattern.segments).fill(null));
  setSteps(rows);
}
const mirrorAll = () => setSteps(copyRows().map((r) => r.reverse()));
const reverseSteps = () => setSteps(copyRows().reverse());
const setSegments = (n) => emit("change", { segments: Math.max(1, Math.min(32, n)) });

// ── Vorschau (läuft im Tempo des Live-Layers) ──
const preview = ref([]);
const current = ref(0);
let raf = 0;
function frame() {
  const l = props.liveLayer || {};
  const rate = l.sync === false ? l.hz ?? 2 : (props.bpm / 60) * (l.mult ?? 1);
  const n = steps.value.length || 1;
  const pos = ((performance.now() / 1000) * rate) % n;
  const i = Math.floor(pos);
  current.value = i;
  const a = steps.value[i] || [], b = steps.value[(i + 1) % n] || [];
  let f = props.pattern.transition === "soft" ? pos - i : 0;
  f = f * f * (3 - 2 * f);
  preview.value = a.map((c, k) => {
    const ca = c == null ? null : hsvToRgb(...resolve(c)), cb = b[k] == null ? null : hsvToRgb(...resolve(b[k]));
    // Deckkraft-gewichtet wie im Backend: Aus-Zellen blenden nach Schwarz.
    const wa = ca ? 1 - f : 0, wb = cb ? f : 0;
    if (wa + wb < 0.01) return "#000";
    const mix = [0, 1, 2].map((j) => Math.round((ca?.[j] ?? 0) * wa + (cb?.[j] ?? 0) * wb));
    return `rgb(${mix.join(",")})`;
  });
  raf = requestAnimationFrame(frame);
}
const onKey = (e) => { if (e.key === "Escape") emit("close"); };
onMounted(() => { frame(); window.addEventListener("keydown", onKey); });
onUnmounted(() => { cancelAnimationFrame(raf); window.removeEventListener("keydown", onKey); });
</script>

<template>
  <div class="fixed inset-0 bg-black/75 z-50 overflow-auto p-2 sm:p-6" @click.self="emit('close')">
    <div class="max-w-5xl mx-auto bg-neutral-900 rounded-xl ring-1 ring-white/10 p-4 space-y-4">
      <!-- Kopf -->
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xl">🧩</span>
        <input :value="pattern.name" @change="emit('change', { name: $event.target.value })"
               class="px-2 py-1 rounded bg-black/40 font-semibold w-48" />
        <span class="text-xs text-gray-500">Muster-Editor</span>
        <div class="ml-auto flex gap-2">
          <button @click="emit('test', !liveLayer.on)" class="px-3 py-1.5 rounded-lg text-sm font-semibold ring-1"
                  :class="liveLayer.on ? 'bg-emerald-500 text-black ring-emerald-200' : 'bg-white/5 ring-white/20'">
            {{ liveLayer.on ? "● läuft auf LEDs" : "▶ Auf LEDs testen" }}</button>
          <button @click="emit('duplicate')" class="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-sm">Kopie</button>
          <button @click="emit('delete')" class="px-3 py-1.5 rounded-lg bg-red-500/30 hover:bg-red-500/50 text-sm">Löschen</button>
          <button @click="emit('close')" class="px-4 py-1.5 rounded-lg bg-cyan-500 text-black text-sm font-semibold">Fertig</button>
        </div>
      </div>

      <!-- Einstellungen -->
      <div class="flex flex-wrap items-center gap-4 text-sm">
        <div class="flex items-center gap-1">
          <span class="text-gray-400 mr-1">Segmente</span>
          <button @click="setSegments(pattern.segments - 1)" class="w-7 h-7 rounded bg-white/10">−</button>
          <span class="w-8 text-center font-mono">{{ pattern.segments }}</span>
          <button @click="setSegments(pattern.segments + 1)" class="w-7 h-7 rounded bg-white/10">+</button>
          <button v-for="n in [4, 8, 16]" :key="n" @click="setSegments(n)"
                  class="px-2 h-7 rounded text-xs ring-1" :class="pattern.segments === n ? 'bg-fuchsia-600/60 ring-fuchsia-300' : 'bg-white/5 ring-white/10'">{{ n }}</button>
        </div>
        <div class="flex rounded-lg bg-black/30 p-0.5 text-xs font-semibold">
          <span class="px-2 py-1 text-gray-400 font-normal">Übergang</span>
          <button @click="emit('change', { transition: 'hard' })" class="px-2.5 py-1 rounded-md"
                  :class="pattern.transition !== 'soft' ? 'bg-fuchsia-500 text-black' : 'text-gray-400'">Hart</button>
          <button @click="emit('change', { transition: 'soft' })" class="px-2.5 py-1 rounded-md"
                  :class="pattern.transition === 'soft' ? 'bg-fuchsia-500 text-black' : 'text-gray-400'">Weich</button>
        </div>
        <span class="text-xs text-gray-500">{{ steps.length }} Schritte · Tempo ×1 = ein Schritt pro Beat</span>
      </div>

      <!-- Vorschau -->
      <div class="flex h-8 rounded-lg overflow-hidden ring-1 ring-white/10 bg-black">
        <div v-for="(c, i) in preview" :key="i" class="flex-1 border-r border-black/60 last:border-0" :style="{ background: c }"></div>
      </div>

      <!-- Pinsel -->
      <div>
        <div class="text-xs text-gray-400 mb-2">Pinsel — antippen/ziehen malt, Tippen auf gleiche Farbe löscht</div>
        <div class="flex flex-wrap gap-1.5 items-center">
          <button v-for="(b, i) in BRUSHES" :key="i" @click="brush = b.v; showCustom = false" :title="b.title || b.label"
                  class="w-9 h-9 rounded-md ring-2 text-xs font-bold flex items-center justify-center transition"
                  :class="same(brush, b.v) ? 'ring-white scale-110' : 'ring-white/15'"
                  :style="{ background: b.css, color: b.v == null ? '#888' : '#000' }">{{ b.label }}</button>
          <button @click="showCustom = !showCustom; brush = [...customColor]"
                  class="h-9 px-3 rounded-md ring-2 text-xs font-semibold"
                  :class="showCustom ? 'ring-white' : 'ring-white/15'" :style="{ background: rgbCss(...customColor) }">
            <span class="bg-black/50 px-1 rounded text-white">🎨 Eigene</span></button>
        </div>
        <div v-if="showCustom" class="max-w-md mt-3">
          <ColorPicker :hue="customColor[0]" :saturation="customColor[1]" :palette="[]"
                       @change="(c) => { customColor = [c.hue, c.saturation]; brush = [c.hue, c.saturation]; }" />
        </div>
      </div>

      <!-- Raster -->
      <div class="overflow-x-auto">
        <div class="min-w-max select-none touch-none" @pointerdown="gridDown" @pointermove="gridMove"
             @pointerup="gridUp" @pointercancel="gridUp">
          <div v-for="(row, r) in steps" :key="r" class="flex items-center gap-1 mb-1">
            <span class="w-6 text-right text-xs font-mono mr-1"
                  :class="current === r ? 'text-emerald-300 font-bold' : 'text-gray-500'">{{ r + 1 }}</span>
            <div class="flex gap-0.5 rounded p-0.5" :class="current === r ? 'bg-emerald-400/30' : ''">
              <div v-for="(cell, c) in row" :key="c" :data-cell="1" :data-r="r" :data-c="c"
                   class="w-7 h-7 sm:w-8 sm:h-8 rounded-sm ring-1 ring-white/10 cursor-pointer flex items-center justify-center text-[10px] font-bold text-black/60"
                   :style="{ background: cellCss(cell) }">
                {{ cell === "base" ? "G" : cell === "accent" ? "A" : "" }}</div>
            </div>
            <div class="flex gap-0.5 ml-2" @pointerdown.stop>
              <button @click="rowOp(r, 'dup')" title="Schritt duplizieren" class="w-7 h-7 rounded bg-white/5 hover:bg-white/15 text-xs">⧉</button>
              <button @click="rowOp(r, 'left')" title="nach links schieben" class="w-7 h-7 rounded bg-white/5 hover:bg-white/15 text-xs">←</button>
              <button @click="rowOp(r, 'right')" title="nach rechts schieben" class="w-7 h-7 rounded bg-white/5 hover:bg-white/15 text-xs">→</button>
              <button @click="rowOp(r, 'up')" title="Schritt nach oben" class="w-7 h-7 rounded bg-white/5 hover:bg-white/15 text-xs" :disabled="r === 0">↑</button>
              <button @click="rowOp(r, 'del')" title="Schritt löschen" class="w-7 h-7 rounded bg-red-500/20 hover:bg-red-500/40 text-xs" :disabled="steps.length < 2">✕</button>
            </div>
          </div>
        </div>
      </div>

      <div class="flex flex-wrap gap-2">
        <button @click="addStep(false)" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-sm">+ Schritt</button>
        <button @click="addStep(true)" class="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-sm">+ Kopie vom letzten</button>
        <button @click="mirrorAll" class="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-sm">⇆ Alles spiegeln</button>
        <button @click="reverseSteps" class="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-sm">↕ Rückwärts</button>
      </div>
      <p class="text-xs text-gray-500">
        G / A = Grundfarbe / Akzent: passen sich automatisch an die Farben des Live-Pults bzw. der Szene an, in der das
        Muster läuft. Tempo und Stärke stellst du wie bei allen Effekten an der Kachel ein.
      </p>
    </div>
  </div>
</template>
