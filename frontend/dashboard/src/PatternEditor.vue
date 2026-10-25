<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue";
import ColorPicker from "./ColorPicker.vue";
import { hsvToRgb, rgbCss, accentOf } from "./color.js";
import { Grid3x3, Play, Copy, Trash2, ArrowLeft, ArrowRight, ArrowUp, X, Plus, FlipHorizontal2, Repeat, Minus } from "lucide-vue-next";

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
  { v: null, label: "", title: "Radierer (aus)", css: "#000" },
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
  <div class="fixed inset-0 z-50 bg-black/70 backdrop-blur-[2px] overflow-auto p-2 sm:p-6" @click.self="emit('close')">
    <div class="panel max-w-5xl mx-auto shadow-2xl shadow-black/60">
      <!-- Kopf -->
      <div class="panel-h flex-wrap py-2.5">
        <Grid3x3 class="w-4 h-4 text-muted" />
        <input :value="pattern.name" @change="emit('change', { name: $event.target.value })" class="field !h-8 w-52 font-medium" />
        <span class="eyebrow hidden sm:inline">Muster-Editor</span>
        <div class="ml-auto flex items-center gap-1.5">
          <button @click="emit('test', !liveLayer.on)" class="btn btn-sm" :class="liveLayer.on ? '!border-live/60 !text-live' : ''">
            <span v-if="liveLayer.on" class="led live"></span><Play v-else />{{ liveLayer.on ? "Läuft auf LEDs" : "Auf LEDs testen" }}</button>
          <button @click="emit('duplicate')" class="btn btn-sm btn-ghost" title="Kopie anlegen"><Copy />Kopie</button>
          <button @click="emit('delete')" class="btn btn-sm btn-danger" title="Löschen"><Trash2 /></button>
          <button @click="emit('close')" class="btn btn-sm btn-primary">Fertig</button>
        </div>
      </div>

      <div class="p-4 space-y-5">
        <!-- Einstellungen -->
        <div class="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div class="flex items-center gap-2">
            <span class="text-[12px] text-muted">Segmente</span>
            <div class="flex items-center">
              <button @click="setSegments(pattern.segments - 1)" class="btn btn-sm btn-icon !rounded-r-none"><Minus /></button>
              <span class="num text-[13px] w-9 h-[26px] grid place-items-center border-y border-line-strong bg-canvas">{{ pattern.segments }}</span>
              <button @click="setSegments(pattern.segments + 1)" class="btn btn-sm btn-icon !rounded-l-none"><Plus /></button>
            </div>
            <div class="seg">
              <button v-for="n in [4, 8, 16]" :key="n" :class="{ on: pattern.segments === n }" @click="setSegments(n)"><span class="num">{{ n }}</span></button>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <span class="text-[12px] text-muted">Übergang</span>
            <div class="seg">
              <button :class="{ on: pattern.transition !== 'soft' }" @click="emit('change', { transition: 'hard' })">Hart</button>
              <button :class="{ on: pattern.transition === 'soft' }" @click="emit('change', { transition: 'soft' })">Weich</button>
            </div>
          </div>
          <span class="text-[11px] text-muted num ml-auto">{{ steps.length }} Schritte · ×1 = 1 Schritt pro Beat</span>
        </div>

        <!-- Vorschau -->
        <div class="flex h-7 rounded-[5px] overflow-hidden bg-black border border-line">
          <div v-for="(c, i) in preview" :key="i" class="flex-1 border-r border-black/70 last:border-0" :style="{ background: c }"></div>
        </div>

        <!-- Pinsel -->
        <div>
          <div class="text-[11px] text-muted mb-2">Pinsel · tippen oder ziehen malt, gleiche Farbe nochmal tippen löscht</div>
          <div class="flex flex-wrap items-center gap-1.5">
            <button v-for="(b, i) in BRUSHES" :key="i" @click="brush = b.v; showCustom = false" :title="b.title || b.label"
                    class="w-8 h-8 rounded-[6px] text-[11px] font-semibold grid place-items-center transition"
                    :class="[same(brush, b.v) ? 'ring-2 ring-ink ring-offset-2 ring-offset-panel' : 'ring-1 ring-inset ring-white/10 hover:scale-105',
                             b.v == null ? 'eraser' : '']"
                    :style="{ background: b.css, color: '#000c' }">{{ b.label }}</button>
            <span class="w-px h-6 bg-line mx-1"></span>
            <button @click="showCustom = !showCustom; brush = [...customColor]" class="btn btn-sm" :class="{ 'is-on': showCustom }">
              <span class="w-3.5 h-3.5 rounded-[3px] ring-1 ring-inset ring-black/40" :style="{ background: rgbCss(...customColor) }"></span>Eigene Farbe</button>
          </div>
          <div v-if="showCustom" class="max-w-md mt-3 p-3 rounded-lg border border-line bg-canvas/50">
            <ColorPicker :hue="customColor[0]" :saturation="customColor[1]" :palette="[]"
                         @change="(c) => { customColor = [c.hue, c.saturation]; brush = [c.hue, c.saturation]; }" />
          </div>
        </div>

        <!-- Raster -->
        <div class="overflow-x-auto -mx-1 px-1">
          <div class="min-w-max select-none touch-none" @pointerdown="gridDown" @pointermove="gridMove"
               @pointerup="gridUp" @pointercancel="gridUp">
            <div v-for="(row, r) in steps" :key="r" class="flex items-center gap-2 mb-1">
              <span class="w-6 text-right text-[11px] num" :class="current === r ? 'text-accent' : 'text-faint'">{{ r + 1 }}</span>
              <div class="flex gap-[3px] p-[3px] rounded-[5px] transition-colors"
                   :class="current === r ? 'bg-accent/15 ring-1 ring-accent/40' : 'ring-1 ring-transparent'">
                <div v-for="(cell, c) in row" :key="c" :data-cell="1" :data-r="r" :data-c="c"
                     class="cell w-7 h-7 sm:w-8 sm:h-8 rounded-[3px] cursor-pointer grid place-items-center text-[10px] font-semibold"
                     :class="cell == null ? 'empty' : ''" :style="cell == null ? {} : { background: cellCss(cell) }">
                  <span v-if="cell === 'base' || cell === 'accent'" class="text-black/55">{{ cell === "base" ? "G" : "A" }}</span></div>
              </div>
              <div class="flex gap-0.5 ml-1" @pointerdown.stop>
                <button @click="rowOp(r, 'dup')" title="Schritt duplizieren" class="btn btn-ghost btn-sm btn-icon"><Copy /></button>
                <button @click="rowOp(r, 'left')" title="Nach links schieben" class="btn btn-ghost btn-sm btn-icon"><ArrowLeft /></button>
                <button @click="rowOp(r, 'right')" title="Nach rechts schieben" class="btn btn-ghost btn-sm btn-icon"><ArrowRight /></button>
                <button @click="rowOp(r, 'up')" title="Schritt nach oben" class="btn btn-ghost btn-sm btn-icon" :disabled="r === 0"><ArrowUp /></button>
                <button @click="rowOp(r, 'del')" title="Schritt löschen" class="btn btn-ghost btn-sm btn-icon hover:!text-danger" :disabled="steps.length < 2"><X /></button>
              </div>
            </div>
          </div>
        </div>

        <div class="flex flex-wrap gap-1.5">
          <button @click="addStep(false)" class="btn btn-sm"><Plus />Schritt</button>
          <button @click="addStep(true)" class="btn btn-sm btn-ghost"><Copy />Letzten kopieren</button>
          <button @click="mirrorAll" class="btn btn-sm btn-ghost"><FlipHorizontal2 />Spiegeln</button>
          <button @click="reverseSteps" class="btn btn-sm btn-ghost"><Repeat />Rückwärts</button>
        </div>
        <p class="text-[11px] text-muted border-t border-line pt-3">
          <span class="text-sub">G</span> / <span class="text-sub">A</span> = Grundfarbe / Akzent — passen sich den Farben der Szene an, in der das Muster läuft.
          Tempo und Stärke stellst du wie bei allen Effekten an der Kachel ein.
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cell { box-shadow: inset 0 0 0 1px rgba(0, 0, 0, .35); }
.cell.empty { background: var(--color-canvas); box-shadow: inset 0 0 0 1px var(--color-line); }
.cell.empty:hover { box-shadow: inset 0 0 0 1px var(--color-line-strong); }
.eraser { background: repeating-linear-gradient(135deg, #1a1a1e 0 4px, #0b0b0d 4px 8px) !important; }
</style>
