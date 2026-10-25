<script setup>
import { ref, reactive, inject, onMounted, onUnmounted, computed } from "vue";
import ColorPicker from "./ColorPicker.vue";
import SpeedControl from "./SpeedControl.vue";
import PatternEditor from "./PatternEditor.vue";
import { createTapper, MULT_LABELS, fmtHz } from "./tap.js";
import { rgbCss, accentOf } from "./color.js";
import {
  Square, ChevronsRight, Ellipsis, Waves, Wind, Rainbow, RefreshCw, Sparkles, Siren, Blend, Grid3x3,
  Power, Sun, Zap, Activity, Music2, Plus, Pencil, Settings2, Trash2, ArrowLeft, ArrowRight,
  SlidersHorizontal, ChevronDown, Hand,
} from "lucide-vue-next";

const props = defineProps({
  mode: { type: String, default: "auto" },
  state: { type: Object, required: true },     // manueller Zustand (aus App, per WS synchron)
  palette: { type: Array, default: () => [] },
  mults: { type: Array, default: () => [0.125, 0.25, 0.5, 1, 2, 4] },
  preview: { type: Array, default: () => [] },
  bpmEff: { type: Number, default: 0 },        // effektives Tempo (getappt oder Musik)
  musicBpm: { type: Number, default: 0 },
});
const emit = defineEmits(["set-mode"]);
const wsSend = inject("wsSend");
const touched = inject("manualTouched");     // Pfad → Zeitpunkt lokaler Änderung (Echo-Filter)
const applyManual = inject("applyManual");

const EFFECTS = [
  { id: "solid", label: "Solid", icon: Square, key: "1", kind: "Fläche" },
  { id: "chase", label: "Chase", icon: ChevronsRight, key: "2", kind: "Muster" },
  { id: "theater", label: "Theater", icon: Ellipsis, key: "3", kind: "Muster" },
  { id: "wave", label: "Welle", icon: Waves, key: "4", kind: "Muster" },
  { id: "breathe", label: "Atmen", icon: Wind, key: "5", kind: "Fläche" },
  { id: "rainbow", label: "Regenbogen", icon: Rainbow, key: "6", kind: "Fläche" },
  { id: "cycle", label: "Farbwechsel", icon: RefreshCw, key: "7", kind: "Fläche" },
  { id: "sparkle", label: "Funkeln", icon: Sparkles, key: "8", kind: "Muster" },
  { id: "police", label: "Polizei", icon: Siren, key: "9", kind: "Muster" },
  { id: "gradient", label: "Verlauf", icon: Blend, key: "0", kind: "Fläche" },
];
const TWO_COLOR = ["police", "gradient"];
const HOLDS = [
  { id: "blackout", label: "Alles aus", hint: "halten", key: "Leer", icon: Power },
  { id: "blinder", label: "Blinder", hint: "Fade-out", key: "B", icon: Sun },
  { id: "flash", label: "Flash", hint: "halten", key: "F", icon: Zap },
];
const KEYS = [
  ["Leer", "Alles aus (halten)"], ["B", "Blinder"], ["F", "Flash (halten)"], ["Enter", "Bump"],
  ["1–9 0", "Effekte an/aus"], ["T", "Tap"], ["S", "Strobe an/aus"],
];
const held = reactive({ blackout: false, blinder: false, flash: false });
const bpm = computed(() => props.bpmEff || props.state.bpm || 120);

// ── Senden (optimistisch lokal übernehmen, Echo-Filter per Pfad) ──
const isObj = (v) => v && typeof v === "object" && !Array.isArray(v);
function applyLocal(obj, changes, path) {
  const now = Date.now();
  for (const [k, v] of Object.entries(changes)) {
    const p = path ? `${path}.${k}` : k;
    if (isObj(v) && isObj(obj[k])) applyLocal(obj[k], v, p);
    else if (k in obj || path) { touched[p] = now; obj[k] = v; }
  }
}
function send(changes) {
  applyLocal(props.state, changes, "");
  if (!wsSend({ action: "manual", changes })) post("/api/manual", { changes });
}
function post(url, body) {
  return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => r.json());
}
function sceneOp(op, payload = {}) {
  if (!wsSend({ action: "scene", op, ...payload })) post(`/api/scenes/${op}`, payload).then(applyManual);
}

// ── Bearbeitungsziel: Live-Pult oder eine Szene ──
const editId = ref(null);
const editScene = computed(() => (editId.value ? props.state.scenes?.[editId.value] : null));
const target = computed(() => editScene.value || props.state);
const focus = ref("solid");                 // Effekt im Editor ("base" = Grundfarbe)
const focused = computed(() => {
  if (focus.value.startsWith("p_")) {
    const pat = props.state.patterns?.[focus.value.slice(2)];
    return { id: focus.value, label: pat?.name ?? "Muster", icon: Grid3x3, kind: "Muster", pattern: pat };
  }
  return EFFECTS.find((e) => e.id === focus.value) || EFFECTS[0];
});
const layer = (id, look = target.value) => look?.layers?.[id] || {};

function sendTarget(changes) {
  if (!editScene.value) return send(changes);
  const id = editId.value;
  applyLocal(editScene.value, changes, `scenes.${id}`);
  sceneOp("update", { id, changes });
}
const sendLayer = (id, lp) => sendTarget({ layers: { [id]: lp } });
function toggleEffect(id) { focus.value = id; sendLayer(id, { on: !layer(id).on }); }

// ── Szenen ──
const scenes = computed(() => (props.state.scene_order || []).map((id) => props.state.scenes?.[id]).filter(Boolean));
const isActive = (id) => (props.state.active_scenes || []).includes(id);
function toggleScene(id) {
  const on = !isActive(id);
  const list = props.state.active_scenes || [];
  touched.active_scenes = Date.now();
  props.state.active_scenes = on ? (props.state.scene_exclusive ? [id] : [...list, id]) : list.filter((s) => s !== id);
  sceneOp("toggle", { id, on });
}
async function createScene(fromLive) {
  const name = prompt("Name der neuen Szene:", `Szene ${scenes.value.length + 1}`);
  if (name === null) return;
  const r = await post("/api/scenes/create", { name, from_live: fromLive });
  applyManual(r);
  if (r.scene) { editId.value = r.scene.id; focus.value = "solid"; }
}
function deleteScene(id) {
  if (!confirm(`Szene „${props.state.scenes[id]?.name}" löschen?`)) return;
  if (editId.value === id) editId.value = null;
  sceneOp("delete", { id });
}

// ── Farben für Vorschau-Chips ──
const RAINBOW = "#f00,#ff0,#0f0,#0ff,#00f,#f0f";
const color2Css = (l) => rgbCss(l.eff_hue2 ?? 0.62, l.eff_saturation2 ?? 1);
function layerCss(id, look) {
  const l = layer(id, look);
  if (id === "rainbow") return `linear-gradient(90deg,${RAINBOW})`;
  const c1 = rgbCss(l.eff_hue ?? 0, l.eff_saturation ?? 1);
  if (id === "police") return `linear-gradient(90deg,${c1} 50%,${color2Css(l)} 50%)`;
  return id === "gradient" ? `linear-gradient(90deg,${c1},${color2Css(l)})` : c1;
}
function lookCss(look) {
  const cols = EFFECTS.filter((e) => layer(e.id, look).on)
    .flatMap((e) => (e.id === "rainbow" ? RAINBOW.split(",")
      : [rgbCss(layer(e.id, look).eff_hue ?? 0, layer(e.id, look).eff_saturation ?? 1),
         ...(TWO_COLOR.includes(e.id) ? [color2Css(layer(e.id, look))] : [])]));
  if (!cols.length) return "#222";
  return cols.length === 1 ? cols[0] : `linear-gradient(90deg,${cols.join(",")})`;
}
const tempoBadge = (l) => (l.sync === false ? `${fmtHz(l.hz ?? 2)} Hz` : `×${MULT_LABELS[l.mult ?? 1] ?? l.mult}`);

// ── Eigene Muster (Sequenzer) ──
const patterns = computed(() => (props.state.pattern_order || []).map((id) => props.state.patterns?.[id]).filter(Boolean));
const editPatternId = ref(null);
const editPattern = computed(() => (editPatternId.value ? props.state.patterns?.[editPatternId.value] : null));
// Mini-Vorschau einer Kachel: erster Schritt des Musters in den Farben des Looks.
function patternCss(pat, look) {
  const acc = accentOf(look.hue ?? 0, look.saturation ?? 1, props.palette);
  const cols = (pat.steps?.[0] || []).map((c) => (c == null ? "#000" : c === "base" ? rgbCss(look.hue ?? 0, look.saturation ?? 1)
    : c === "accent" ? rgbCss(...acc) : rgbCss(c[0], c[1])));
  return cols.length > 1 ? `linear-gradient(90deg,${cols.map((c, i) => `${c} ${(i / cols.length) * 100}% ${((i + 1) / cols.length) * 100}%`).join(",")})` : cols[0] || "#000";
}
function patternOp(op, payload = {}) {
  if (op === "update") applyLocal(props.state.patterns[payload.id], payload.changes, `patterns.${payload.id}`);
  if (!wsSend({ action: "pattern", op, ...payload })) return post(`/api/patterns/${op}`, payload).then(applyManual);
}
async function createPattern(copyOf) {
  const r = await post(`/api/patterns/${copyOf ? "duplicate" : "create"}`, { id: copyOf || "" });
  applyManual(r);
  if (r.pattern) { editPatternId.value = r.pattern.id; focus.value = "p_" + r.pattern.id; }
}
function deletePattern(id) {
  if (!confirm(`Muster „${props.state.patterns[id]?.name}" löschen? Es verschwindet auch aus allen Szenen.`)) return;
  editPatternId.value = null;
  if (focus.value === "p_" + id) focus.value = "solid";
  patternOp("delete", { id });
}
// „Auf LEDs testen" schaltet das Muster im Live-Pult an/aus.
const testPattern = (id, on) => send({ layers: { ["p_" + id]: { on } } });

// ── Globales Tempo (TAP) ──
const beatKey = ref(0);
// BPM direkt eingeben: Feld hält den getippten Wert, solange es den Fokus hat
// (die Anzeige aktualisiert sich sonst laufend). Eingabe schaltet „Musik folgen" aus.
const bpmEdit = ref(null);
const setBpm = (v) => send({ bpm: Math.round(Math.min(300, Math.max(20, v)) * 10) / 10, music_sync: false });
function commitBpm() {
  const v = parseFloat(String(bpmEdit.value).replace(",", "."));
  bpmEdit.value = null;
  if (Number.isFinite(v) && Math.abs(v - bpm.value) >= 0.05) setBpm(v);
}

const tapGlobal = createTapper((hz) => {
  beatKey.value++;
  send(hz ? { tap: true, bpm: Math.round(hz * 600) / 10, music_sync: false } : { tap: true });
});

// ── Halte-Buttons ──
function hold(id, on) {
  if (held[id] === on) return;
  held[id] = on;
  send({ [id]: on });
}
function releaseAll() { for (const id of Object.keys(held)) hold(id, false); }

// Bump: einzelner Puls pro Druck (kein Zustand, nur Auslöser).
const bumpKey = ref(0);
function bump() {
  bumpKey.value++;
  send({ bump: true });
}

// Tastatur: Leertaste/F halten, B Blinder, 1–8 Effekte, T Tap, S Strobe an/aus.
const KEYS_HOLD = { " ": "blackout", b: "blinder", f: "flash" };
function onKey(e, down) {
  if (e.target.closest && e.target.closest("input, select, textarea")) return;
  const k = e.key.toLowerCase();
  if (KEYS_HOLD[k]) { e.preventDefault(); hold(KEYS_HOLD[k], down); return; }
  if (!down || e.repeat) return;
  if (k === "enter") { e.preventDefault(); bump(); return; }
  const eff = EFFECTS.find((x) => x.key === k);
  if (eff) toggleEffect(eff.id);
  else if (k === "t") tapGlobal();
  else if (k === "s") send({ strobe_on: !props.state.strobe_on });
}
const kd = (e) => onKey(e, true), ku = (e) => onKey(e, false);
onMounted(() => { window.addEventListener("keydown", kd); window.addEventListener("keyup", ku); window.addEventListener("blur", releaseAll); });
onUnmounted(() => { releaseAll(); window.removeEventListener("keydown", kd); window.removeEventListener("keyup", ku); window.removeEventListener("blur", releaseAll); });
</script>

<template>
  <div class="select-none space-y-4">
    <!-- Hinweis: Pult greift nur im Manuell-Modus -->
    <div v-if="mode !== 'manual'" class="notice">
      <Hand class="w-4 h-4 text-accent shrink-0" />
      <span class="flex-1">Die Automatik steuert gerade die LEDs. Das Pult greift erst im Modus <span class="text-ink">Manuell</span>.</span>
      <button @click="emit('set-mode', 'manual')" class="btn btn-primary btn-sm">Manuell übernehmen</button>
    </div>

    <!-- Ausgabe -->
    <div class="flex h-5 rounded-[4px] overflow-hidden bg-black border border-line">
      <div v-for="(c, i) in preview" :key="i" class="flex-1" :style="{ background: c }"></div>
    </div>

    <!-- Pads: Halte-Buttons + Bump -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <button v-for="h in HOLDS" :key="h.id"
              @pointerdown.prevent="$event.currentTarget.setPointerCapture?.($event.pointerId); hold(h.id, true)"
              @pointerup="hold(h.id, false)" @pointercancel="hold(h.id, false)" @lostpointercapture="hold(h.id, false)"
              @contextmenu.prevent
              class="pad" :class="(held[h.id] || state[h.id]) && 'held-' + h.id">
        <div class="flex items-start justify-between w-full"><component :is="h.icon" /><span class="kbd">{{ h.key }}</span></div>
        <div><div class="pad-label">{{ h.label }}</div><div class="pad-hint">{{ h.hint }}</div></div>
      </button>
      <button :key="bumpKey" @pointerdown.prevent="bump" @contextmenu.prevent class="pad" :class="{ 'bump-hit': bumpKey }">
        <div class="flex items-start justify-between w-full"><Activity /><span class="kbd">Enter</span></div>
        <div><div class="pad-label">Bump</div><div class="pad-hint">tippen</div></div>
      </button>
    </div>

    <!-- Tempo · Strobe · Dimmer -->
    <div class="grid lg:grid-cols-3 gap-4">
      <section class="panel">
        <div class="panel-h"><span class="eyebrow">Tempo</span>
          <span :key="beatKey" class="led on beat ml-auto" :style="{ animationDuration: 60 / bpm + 's' }"></span></div>
        <div class="p-4 flex gap-4">
          <button @pointerdown.prevent="tapGlobal" class="pad !h-[112px] w-[104px] shrink-0 tap-pad">
            <div class="flex justify-end w-full"><span class="kbd">T</span></div>
            <div class="pad-label !text-[18px]">Tap</div>
          </button>
          <div class="flex-1 min-w-0 flex flex-col justify-between gap-2">
            <div class="flex items-baseline gap-1.5">
              <input type="number" min="20" max="300" step="0.1" title="BPM eingeben (Enter)"
                     :value="bpmEdit ?? bpm.toFixed(1)"
                     @focus="bpmEdit = bpm.toFixed(1); $event.target.select()"
                     @input="bpmEdit = $event.target.value"
                     @keydown.enter="$event.target.blur()" @blur="commitBpm"
                     class="no-spin display w-full min-w-0 text-[40px] leading-none bg-transparent rounded-md px-1.5 -mx-1.5 py-0.5 outline-none hover:bg-raised focus:bg-canvas focus:ring-1 focus:ring-accent" />
              <span class="text-xs text-muted">BPM</span>
            </div>
            <div class="grid grid-cols-4 gap-1">
              <button @click="setBpm(bpm - 1)" class="btn btn-sm num">−1</button>
              <button @click="setBpm(bpm + 1)" class="btn btn-sm num">+1</button>
              <button @click="setBpm(bpm / 2)" class="btn btn-sm num">÷2</button>
              <button @click="setBpm(bpm * 2)" class="btn btn-sm num">×2</button>
            </div>
            <button @click="send({ music_sync: !state.music_sync })" class="btn btn-sm w-full" :class="{ 'is-on': state.music_sync }">
              <Music2 />Musik folgen
              <span class="num ml-auto" :class="state.music_sync ? '' : 'text-muted'">{{ musicBpm >= 40 ? musicBpm.toFixed(0) : "—" }}</span></button>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-h"><span class="eyebrow">Strobe</span>
          <button @click="send({ strobe_on: !state.strobe_on })" class="btn btn-sm ml-auto" :class="{ 'is-on': state.strobe_on }">
            <span class="led" :class="{ on: state.strobe_on }"></span>{{ state.strobe_on ? "An" : "Aus" }}<span class="kbd">S</span></button>
        </div>
        <div class="p-4 space-y-3">
          <SpeedControl :sync="state.strobe_sync" :mult="state.strobe_mult" :hz="state.strobe_hz" :bpm="bpm"
                        :min="0.5" :max="20" :mults="[0.25, 0.5, 1, 2, 4]"
                        @change="(c) => send({ ...(c.sync !== undefined && { strobe_sync: c.sync }),
                                               ...(c.mult !== undefined && { strobe_mult: c.mult }),
                                               ...(c.hz !== undefined && { strobe_hz: c.hz }) })" />
          <div class="flex items-center gap-3 pt-1">
            <div class="seg">
              <button :class="{ on: state.strobe_white }" @click="send({ strobe_white: true })">Weiß</button>
              <button :class="{ on: !state.strobe_white }" @click="send({ strobe_white: false })">Effekte takten</button>
            </div>
            <button @click="send({ strobe_alt: !state.strobe_alt })" class="ml-auto flex items-center gap-2 text-[12px] text-sub hover:text-ink">
              <span class="switch" :class="{ on: state.strobe_alt }"></span>Abwechselnd</button>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-h"><span class="eyebrow">Dimmer</span>
          <span class="ml-auto display text-[17px]">{{ Math.round(state.brightness * 100) }}<span class="text-muted text-xs"> %</span></span></div>
        <div class="p-4 space-y-3">
          <input v-fill type="range" min="0" max="1" step="0.01" :value="state.brightness"
                 @input="send({ brightness: +$event.target.value })" class="fader-lg" />
          <div class="seg seg-fill">
            <button v-for="v in [0.1, 0.25, 0.5, 1]" :key="v" :class="{ on: Math.abs(state.brightness - v) < 0.005 }"
                    @click="send({ brightness: v })"><span class="num">{{ v * 100 }}</span></button>
          </div>
        </div>
      </section>
    </div>

    <!-- Szenen -->
    <section class="panel">
      <div class="panel-h flex-wrap py-2">
        <span class="eyebrow">Szenen</span>
        <span class="text-[11px] text-muted hidden sm:inline">eigene Effekt-Stapel</span>
        <div class="ml-auto flex items-center gap-2">
          <div class="seg">
            <button :class="{ on: !state.scene_exclusive }" @click="send({ scene_exclusive: false })">Stapeln</button>
            <button :class="{ on: state.scene_exclusive }" @click="send({ scene_exclusive: true })">Einzeln</button>
          </div>
          <button @click="createScene(true)" class="btn btn-sm btn-ghost">Aus Live</button>
          <button @click="createScene(false)" class="btn btn-sm"><Plus />Neu</button>
        </div>
      </div>
      <div class="p-3 grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
        <div v-for="sc in scenes" :key="sc.id" class="tile !min-h-[66px]"
             :class="{ on: isActive(sc.id), focus: editId === sc.id }">
          <button @click="toggleScene(sc.id)" class="absolute inset-0 rounded-[8px]" :aria-pressed="isActive(sc.id)" :title="`${sc.name} an/aus`"></button>
          <div class="flex items-center gap-2 pr-7 pointer-events-none">
            <span class="led" :class="{ on: isActive(sc.id) }"></span>
            <span class="text-[13px] font-medium truncate">{{ sc.name }}</span>
          </div>
          <div class="mt-auto h-[3px] rounded-full pointer-events-none" :style="{ background: lookCss(sc) }"></div>
          <button @click.stop="editId = editId === sc.id ? null : sc.id" title="Szene bearbeiten"
                  class="btn btn-ghost btn-sm btn-icon absolute top-1.5 right-1.5 z-[1]"><Pencil /></button>
        </div>
        <div v-if="!scenes.length" class="col-span-full text-[13px] text-muted py-4 text-center">Noch keine Szenen.</div>
      </div>
    </section>

    <!-- Effekte (Live-Ebene oder Szene bearbeiten) -->
    <section class="panel" :class="editScene ? '!border-accent/50' : ''">
      <div v-if="editScene" class="panel-h flex-wrap py-2 bg-accent/[.05]">
        <Pencil class="w-3.5 h-3.5 text-accent" />
        <span class="eyebrow !text-accent">Szene bearbeiten</span>
        <input :value="editScene.name" @change="sendTarget({ name: $event.target.value })" class="field !h-7 w-40" />
        <label class="flex items-center gap-2 text-[12px] text-muted">Stärke
          <input v-fill type="range" min="0" max="1" step="0.01" :value="editScene.level"
                 @input="sendTarget({ level: +$event.target.value })" class="w-24" />
          <span class="num text-sub w-12 whitespace-nowrap">{{ Math.round(editScene.level * 100) }} %</span></label>
        <div class="ml-auto flex items-center gap-1">
          <button @click="sceneOp('move', { id: editId, delta: -1 })" class="btn btn-ghost btn-sm btn-icon" title="Nach vorne"><ArrowLeft /></button>
          <button @click="sceneOp('move', { id: editId, delta: 1 })" class="btn btn-ghost btn-sm btn-icon" title="Nach hinten"><ArrowRight /></button>
          <button @click="deleteScene(editId)" class="btn btn-danger btn-sm"><Trash2 />Löschen</button>
          <button @click="editId = null" class="btn btn-primary btn-sm">Fertig</button>
        </div>
      </div>
      <div v-else class="panel-h">
        <span class="eyebrow">Effekte</span>
        <span class="text-[11px] text-muted">Live-Ebene · aktive Szenen laufen zusätzlich</span>
      </div>

      <div class="p-3 space-y-3">
        <div class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 2xl:grid-cols-11 gap-2">
          <div v-for="e in EFFECTS" :key="e.id" class="tile" :class="{ on: layer(e.id).on, focus: focus === e.id }">
            <button @click="toggleEffect(e.id)" class="absolute inset-0 rounded-[8px]" :aria-pressed="!!layer(e.id).on" :title="`${e.label} an/aus`"></button>
            <div class="flex items-center gap-2 pointer-events-none">
              <component :is="e.icon" class="w-4 h-4" :class="layer(e.id).on ? 'text-accent' : 'text-muted'" />
              <span class="led ml-auto" :class="{ on: layer(e.id).on }"></span>
            </div>
            <div class="text-[13px] font-medium leading-none pointer-events-none">{{ e.label }}</div>
            <div class="flex items-center gap-1.5 pointer-events-none">
              <span class="num text-[10px] text-muted">{{ tempoBadge(layer(e.id)) }}</span>
              <button @click.stop="focus = e.id" title="Farbe, Stärke, Tempo"
                      class="ml-auto pointer-events-auto relative z-[1] w-4 h-4 rounded-[4px] ring-1 ring-inset ring-black/40 hover:scale-125 transition"
                      :style="{ background: layerCss(e.id, target) }"></button>
              <span class="kbd">{{ e.key }}</span>
            </div>
          </div>
          <button @click="focus = 'base'" class="tile" :class="{ focus: focus === 'base' }">
            <span class="w-4 h-4 rounded-full ring-1 ring-inset ring-black/40" :style="{ background: rgbCss(target.hue ?? 0, target.saturation ?? 1) }"></span>
            <span class="text-[13px] font-medium leading-none">Grundfarbe</span>
            <span class="text-[10px] text-muted">für Auto-Farben</span>
          </button>
        </div>

        <!-- Eigene Muster -->
        <div class="flex items-center gap-2 pt-1"><span class="eyebrow">Muster</span>
          <span class="text-[11px] text-muted">selbst programmiert</span></div>
        <div class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 2xl:grid-cols-11 gap-2">
          <div v-for="pat in patterns" :key="pat.id" class="tile" :class="{ on: layer('p_' + pat.id).on, focus: focus === 'p_' + pat.id }">
            <button @click="toggleEffect('p_' + pat.id)" class="absolute inset-0 rounded-[8px]" :aria-pressed="!!layer('p_' + pat.id).on" :title="`${pat.name} an/aus`"></button>
            <div class="flex items-center gap-2 pointer-events-none">
              <Grid3x3 class="w-4 h-4" :class="layer('p_' + pat.id).on ? 'text-accent' : 'text-muted'" />
              <span class="led ml-auto" :class="{ on: layer('p_' + pat.id).on }"></span>
            </div>
            <div class="text-[13px] font-medium leading-none truncate pointer-events-none">{{ pat.name }}</div>
            <div class="flex items-center gap-1 pointer-events-none">
              <span class="num text-[10px] text-muted">{{ tempoBadge(layer('p_' + pat.id)) }}</span>
              <button @click.stop="focus = 'p_' + pat.id" title="Stärke, Tempo"
                      class="ml-auto pointer-events-auto relative z-[1] text-muted hover:text-ink"><Settings2 class="w-3.5 h-3.5" /></button>
              <button @click.stop="editPatternId = pat.id; focus = 'p_' + pat.id" title="Muster bearbeiten"
                      class="pointer-events-auto relative z-[1] text-muted hover:text-ink"><Pencil class="w-3.5 h-3.5" /></button>
            </div>
            <div class="absolute inset-x-[11px] bottom-[5px] h-[2px] rounded-full opacity-80 pointer-events-none" :style="{ background: patternCss(pat, target) }"></div>
          </div>
          <button @click="createPattern()" class="tile items-center justify-center !border-dashed text-muted hover:text-ink">
            <Plus class="w-4 h-4" /><span class="text-[12px]">Neues Muster</span>
          </button>
        </div>
      </div>

      <!-- Einstellungen des gewählten Effekts -->
      <div class="border-t border-line p-4">
        <div v-if="focus === 'base'" class="max-w-xl">
          <div class="text-[13px] font-medium mb-1">Grundfarbe</div>
          <p class="text-[12px] text-muted mb-3">Flächen mit Auto-Farbe übernehmen sie, Muster bekommen eine passende Akzentfarbe.
            {{ editScene ? "" : "Flash blitzt in dieser Farbe." }}</p>
          <ColorPicker :hue="target.hue" :saturation="target.saturation" :palette="palette" @change="(c) => sendTarget(c)" />
        </div>
        <div v-else class="grid lg:grid-cols-2 gap-x-8 gap-y-6">
          <div v-if="focused.pattern">
            <div class="flex items-center gap-2 mb-1"><Grid3x3 class="w-4 h-4 text-muted" />
              <span class="text-[13px] font-medium">{{ focused.label }}</span></div>
            <p class="text-[12px] text-muted mb-3 num">{{ focused.pattern.segments }} Segmente · {{ focused.pattern.steps.length }} Schritte ·
              {{ focused.pattern.transition === "soft" ? "weich" : "hart" }}</p>
            <div class="h-5 rounded-[4px] mb-4 border border-line" :style="{ background: patternCss(focused.pattern, target) }"></div>
            <button @click="editPatternId = focused.pattern.id" class="btn btn-primary"><Pencil />Muster bearbeiten</button>
          </div>
          <div v-else>
            <div class="flex items-center gap-2 mb-3">
              <component :is="focused.icon" class="w-4 h-4 text-muted" />
              <span class="text-[13px] font-medium">{{ focused.label }}</span>
              <span class="text-[12px] text-muted">Farbe</span>
              <button v-if="focus !== 'rainbow'" @click="sendLayer(focus, { color_auto: !layer(focus).color_auto })"
                      class="btn btn-sm ml-auto" :class="{ 'is-on': layer(focus).color_auto }">Auto-Farbe</button>
            </div>
            <p v-if="focus === 'rainbow'" class="text-[12px] text-muted">Regenbogen nutzt das ganze Spektrum.</p>
            <template v-else>
              <p v-if="layer(focus).color_auto" class="text-[12px] text-muted mb-3">
                Folgt {{ focused.kind === "Fläche" ? "der Grundfarbe" : "der Akzentfarbe zur Grundfarbe" }}. Eine Farbe wählen schaltet auf eigene Farbe.</p>
              <div v-if="TWO_COLOR.includes(focus)" class="text-[11px] text-muted mb-1.5">
                Farbe 1 · {{ focus === "police" ? "Segmente 1, 3, …" : "Anfang" }}</div>
              <ColorPicker :hue="layer(focus).color_auto ? layer(focus).eff_hue ?? 0 : layer(focus).hue"
                           :saturation="layer(focus).color_auto ? layer(focus).eff_saturation ?? 1 : layer(focus).saturation"
                           :palette="palette" @change="(c) => sendLayer(focus, { ...c, color_auto: false })" />
              <template v-if="TWO_COLOR.includes(focus)">
                <div class="text-[11px] text-muted mt-4 mb-1.5">Farbe 2 · {{ focus === "police" ? "Segmente 2, 4, …" : "Ende" }}</div>
                <ColorPicker :hue="layer(focus).color_auto ? layer(focus).eff_hue2 ?? 0.62 : layer(focus).hue2"
                             :saturation="layer(focus).color_auto ? layer(focus).eff_saturation2 ?? 1 : layer(focus).saturation2"
                             :palette="palette"
                             @change="(c) => sendLayer(focus, { hue2: c.hue, saturation2: c.saturation, color_auto: false })" />
              </template>
            </template>
          </div>

          <div class="space-y-5">
            <div>
              <div class="flex justify-between text-[13px] mb-1"><span class="text-sub">Stärke</span>
                <span class="num">{{ Math.round((layer(focus).level ?? 1) * 100) }} %</span></div>
              <input v-fill type="range" min="0" max="1" step="0.01" :value="layer(focus).level ?? 1"
                     @input="sendLayer(focus, { level: +$event.target.value })" />
            </div>
            <div v-if="focus === 'police'" class="space-y-3">
              <div>
                <div class="text-[13px] text-sub mb-1.5">Aufteilung</div>
                <div class="seg seg-fill">
                  <button v-for="n in [2, 4, 6, 8]" :key="n" :class="{ on: layer('police').segments === n }"
                          @click="sendLayer('police', { segments: n })">{{ n === 4 ? "Viertel" : n + " Teile" }}</button>
                </div>
              </div>
              <div class="seg seg-fill">
                <button :class="{ on: layer('police').blink }" @click="sendLayer('police', { blink: true })">Doppelblitz</button>
                <button :class="{ on: !layer('police').blink }" @click="sendLayer('police', { blink: false })">Farbwechsel</button>
              </div>
            </div>
            <div v-if="focus === 'gradient'" class="seg seg-fill">
              <button :class="{ on: !layer('gradient').move }" @click="sendLayer('gradient', { move: false })">Statisch</button>
              <button :class="{ on: layer('gradient').move }" @click="sendLayer('gradient', { move: true })">Bewegt</button>
            </div>
            <div v-if="focus !== 'solid' && !(focus === 'gradient' && !layer('gradient').move)">
              <div class="text-[13px] text-sub mb-1.5">Tempo</div>
              <SpeedControl :sync="layer(focus).sync" :mult="layer(focus).mult" :hz="layer(focus).hz" :bpm="bpm"
                            :mults="mults" @change="(c) => sendLayer(focus, c)" />
              <p class="text-[11px] text-muted mt-2">Takt: Faktor pro Beat des globalen Tempos. Frei: eigenes Tempo, per TAP eintippbar.</p>
            </div>
            <button @click="sendLayer(focus, { on: !layer(focus).on })" class="btn w-full !h-9" :class="{ 'is-on': layer(focus).on }">
              <span class="led" :class="{ on: layer(focus).on }"></span>
              {{ focused.label }} {{ layer(focus).on ? "an" : "aus" }}<span v-if="editScene" class="text-muted font-normal">· {{ editScene.name }}</span></button>
          </div>
        </div>
      </div>
    </section>

    <!-- Erweitert -->
    <details class="panel group">
      <summary class="panel-h cursor-pointer !border-b-0 group-open:!border-b">
        <SlidersHorizontal class="w-4 h-4 text-muted" /><span class="eyebrow">Erweitert</span>
        <ChevronDown class="ml-auto w-4 h-4 text-muted transition-transform group-open:rotate-180" />
      </summary>
      <div class="p-4 space-y-5">
        <div class="flex flex-wrap gap-2">
          <button @click="send({ direction: -state.direction })" class="btn btn-sm">
            <ArrowRight v-if="state.direction > 0" /><ArrowLeft v-else />Richtung</button>
          <button v-for="o in [{ k: 'mirror', label: 'Gespiegelt' }, { k: 'beat_sync', label: 'Beat-Pump' }, { k: 'bump_beat', label: 'Bump auf jeden Beat' }]"
                  :key="o.k" @click="send({ [o.k]: !state[o.k] })" class="btn btn-sm" :class="{ 'is-on': state[o.k] }">
            <span class="led" :class="{ on: state[o.k] }"></span>{{ o.label }}</button>
        </div>
        <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-x-8 gap-y-4">
          <label class="block">
            <div class="flex justify-between text-[13px] mb-1"><span class="text-sub">Bump-Stärke</span>
              <span class="num">{{ Math.round(state.bump_gain * 100) }} %</span></div>
            <input v-fill type="range" min="0" max="1" step="0.01" :value="state.bump_gain" @input="send({ bump_gain: +$event.target.value })" />
          </label>
          <label class="block">
            <div class="flex justify-between text-[13px] mb-1"><span class="text-sub">Bump-Länge</span>
              <span class="num">{{ (+state.bump_decay).toFixed(2) }} s</span></div>
            <input v-fill type="range" min="0.05" max="1" step="0.01" :value="state.bump_decay" @input="send({ bump_decay: +$event.target.value })" />
          </label>
          <label class="block">
            <div class="flex justify-between text-[13px] mb-1"><span class="text-sub">Blinder ausblenden</span>
              <span class="num">{{ (+state.blinder_fade).toFixed(1) }} s</span></div>
            <input v-fill type="range" min="0.2" max="5" step="0.1" :value="state.blinder_fade" @input="send({ blinder_fade: +$event.target.value })" />
          </label>
          <label class="block">
            <div class="flex justify-between text-[13px] mb-1"><span class="text-sub">Szenen überblenden</span>
              <span class="num">{{ (+state.scene_fade).toFixed(1) }} s</span></div>
            <input v-fill type="range" min="0" max="5" step="0.1" :value="state.scene_fade" @input="send({ scene_fade: +$event.target.value })" />
          </label>
        </div>
        <div class="pt-4 border-t border-line">
          <div class="text-[11px] text-muted mb-2.5">Tastatur</div>
          <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-2 text-[12px] text-sub">
            <div v-for="k in KEYS" :key="k[0]" class="flex items-center gap-2"><span class="kbd">{{ k[0] }}</span>{{ k[1] }}</div>
          </div>
        </div>
      </div>
    </details>

    <PatternEditor v-if="editPattern" :pattern="editPattern" :palette="palette" :look="target"
                   :live-layer="state.layers?.['p_' + editPattern.id] || {}" :bpm="bpm"
                   @change="(c) => patternOp('update', { id: editPattern.id, changes: c })"
                   @test="(on) => testPattern(editPattern.id, on)"
                   @duplicate="createPattern(editPattern.id)"
                   @delete="deletePattern(editPattern.id)"
                   @close="editPatternId = null" />
  </div>
</template>

<style scoped>
/* Pads im Hardware-Stil: Icon + Taste oben, Beschriftung unten. */
.pad {
  position: relative; height: 96px; padding: 12px; border-radius: 10px;
  display: flex; flex-direction: column; justify-content: space-between; align-items: flex-start; text-align: left;
  background: var(--color-raised); border: 1px solid var(--color-line-strong);
  touch-action: none; user-select: none;
  transition: background-color .08s, border-color .08s, color .08s, box-shadow .08s;
}
.pad:hover { border-color: #45454e; }
.pad :deep(svg) { width: 18px; height: 18px; color: var(--color-muted); }
.pad-label { font-size: 14px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; }
.pad-hint { font-size: 11px; color: var(--color-muted); margin-top: 2px; }
.held-blackout { background: #000; border-color: var(--color-danger); color: var(--color-danger); box-shadow: inset 0 0 0 1px var(--color-danger); }
.held-blackout :deep(svg), .held-blackout .pad-hint { color: var(--color-danger); }
.held-blinder { background: #ffe4bd; border-color: #ffe4bd; color: #2b1b06; box-shadow: 0 0 24px rgba(255, 214, 160, .35); }
.held-flash { background: var(--color-ink); border-color: var(--color-ink); color: var(--color-canvas); }
.held-blinder :deep(svg), .held-blinder .pad-hint, .held-flash :deep(svg), .held-flash .pad-hint { color: inherit; opacity: .7; }
.bump-hit { animation: bump-hit .3s ease-out; }
@keyframes bump-hit { from { background: var(--color-accent); border-color: var(--color-accent); color: var(--color-accent-ink); } }
.tap-pad:active { background: var(--color-accent); border-color: var(--color-accent); color: var(--color-accent-ink); }
.beat { animation: beat linear infinite; }
@keyframes beat { 0% { opacity: 1; } 25% { opacity: .2; } 100% { opacity: .2; } }
</style>
