<script setup>
import { ref, reactive, inject, onMounted, onUnmounted, computed } from "vue";
import ColorPicker from "./ColorPicker.vue";
import SpeedControl from "./SpeedControl.vue";
import PatternEditor from "./PatternEditor.vue";
import { createTapper, MULT_LABELS, fmtHz } from "./tap.js";
import { rgbCss, accentOf } from "./color.js";

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
  { id: "solid", label: "Solid", icon: "⬛", key: "1", kind: "Fläche" },
  { id: "chase", label: "Chase", icon: "🏃", key: "2", kind: "Muster" },
  { id: "theater", label: "Theater", icon: "🎭", key: "3", kind: "Muster" },
  { id: "wave", label: "Welle", icon: "🌊", key: "4", kind: "Muster" },
  { id: "breathe", label: "Atmen", icon: "💨", key: "5", kind: "Fläche" },
  { id: "rainbow", label: "Regenbogen", icon: "🌈", key: "6", kind: "Fläche" },
  { id: "cycle", label: "Farbwechsel", icon: "🔄", key: "7", kind: "Fläche" },
  { id: "sparkle", label: "Funkeln", icon: "✨", key: "8", kind: "Muster" },
  { id: "police", label: "Polizei", icon: "🚨", key: "9", kind: "Muster" },
  { id: "gradient", label: "Verlauf", icon: "🌅", key: "0", kind: "Fläche" },
];
const TWO_COLOR = ["police", "gradient"];
const HOLDS = [
  { id: "blackout", label: "ALLES AUS", hint: "halten · Leertaste", cls: "bg-black ring-white/30", on: "bg-neutral-800 ring-red-500" },
  { id: "blinder", label: "BLINDER", hint: "drücken · B", cls: "bg-amber-200/20 ring-amber-200/40", on: "bg-amber-100 text-black ring-amber-50" },
  { id: "flash", label: "FLASH", hint: "halten · F", cls: "bg-fuchsia-600/30 ring-fuchsia-400/40", on: "bg-fuchsia-500 ring-fuchsia-200" },
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
    return { id: focus.value, label: pat?.name ?? "Muster", icon: "🧩", kind: "Muster", pattern: pat };
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
const tempoBadge = (l) => (l.sync === false ? `${fmtHz(l.hz ?? 2)} Hz` : `♩×${MULT_LABELS[l.mult ?? 1] ?? l.mult}`);

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
    <div v-if="mode !== 'manual'"
         class="px-4 py-3 rounded-lg bg-amber-500/15 ring-1 ring-amber-500/40 text-amber-200 text-sm flex items-center justify-between gap-3">
      <span>Automatik ist aktiv — das Pult steuert die LEDs erst im Modus <b>Manuell</b>.</span>
      <button @click="emit('set-mode', 'manual')"
              class="px-3 py-1.5 rounded-lg bg-amber-500 text-black font-semibold whitespace-nowrap">Manuell übernehmen</button>
    </div>

    <!-- LED-Preview -->
    <div class="flex h-6 rounded-lg overflow-hidden ring-1 ring-white/10">
      <div v-for="(c, i) in preview" :key="i" class="flex-1" :style="{ background: c }"></div>
    </div>

    <!-- Halte-Buttons + Bump -->
    <div class="grid grid-cols-4 gap-3">
      <button v-for="h in HOLDS" :key="h.id"
              @pointerdown.prevent="$event.currentTarget.setPointerCapture?.($event.pointerId); hold(h.id, true)"
              @pointerup="hold(h.id, false)" @pointercancel="hold(h.id, false)" @lostpointercapture="hold(h.id, false)"
              @contextmenu.prevent
              class="h-20 sm:h-24 rounded-xl ring-2 font-bold text-lg sm:text-xl tracking-wide transition touch-none flex flex-col items-center justify-center"
              :class="held[h.id] || state[h.id] ? h.on + ' scale-95' : h.cls">
        {{ h.label }}
        <span class="text-[10px] font-normal opacity-60 mt-1">{{ h.hint }}</span>
      </button>
      <button :key="bumpKey" @pointerdown.prevent="bump" @contextmenu.prevent
              class="bump h-20 sm:h-24 rounded-xl ring-2 ring-sky-300/50 bg-sky-400/20 font-bold text-lg sm:text-xl tracking-wide touch-none flex flex-col items-center justify-center active:scale-95 transition">
        BUMP
        <span class="text-[10px] font-normal opacity-60 mt-1">tippen · Enter</span>
      </button>
    </div>

    <!-- Tempo · Strobe · Dimmer -->
    <div class="grid lg:grid-cols-3 gap-4">
      <div class="bg-white/5 rounded-xl p-4">
        <div class="text-xs uppercase text-gray-400 mb-3">Globales Tempo</div>
        <div class="flex items-stretch gap-3">
          <button @pointerdown.prevent="tapGlobal"
                  class="w-24 h-24 rounded-xl bg-cyan-500/20 ring-2 ring-cyan-300/50 font-bold text-2xl active:bg-cyan-300 active:text-black touch-none">
            TAP<span class="block text-[10px] font-normal opacity-60">im Takt · T</span></button>
          <div class="flex-1 flex flex-col justify-between">
            <div class="flex items-center gap-2">
              <span :key="beatKey" class="beat w-3 h-3 rounded-full bg-cyan-300"
                    :style="{ animationDuration: 60 / bpm + 's' }"></span>
              <span class="text-3xl font-mono">{{ bpm.toFixed(1) }}</span><span class="text-xs text-gray-400">BPM</span>
            </div>
            <div class="flex gap-1">
              <button @click="send({ bpm: Math.max(20, state.bpm / 2), music_sync: false })" class="flex-1 py-1 rounded bg-white/10 hover:bg-white/20 text-xs">½×</button>
              <button @click="send({ bpm: Math.min(300, state.bpm * 2), music_sync: false })" class="flex-1 py-1 rounded bg-white/10 hover:bg-white/20 text-xs">2×</button>
            </div>
            <button @click="send({ music_sync: !state.music_sync })"
                    class="py-1 rounded-lg ring-1 text-xs"
                    :class="state.music_sync ? 'bg-emerald-600/40 ring-emerald-400/60' : 'bg-white/5 ring-white/10'">
              🎵 Musik folgen {{ state.music_sync ? "AN" : "AUS" }}
              <span class="text-gray-400">({{ musicBpm >= 40 ? musicBpm.toFixed(0) : "—" }})</span></button>
          </div>
        </div>
      </div>

      <div class="bg-white/5 rounded-xl p-4">
        <div class="flex items-center justify-between mb-3">
          <span class="text-xs uppercase text-gray-400">Strobe</span>
          <button @click="send({ strobe_on: !state.strobe_on })"
                  class="px-4 py-1.5 rounded-lg font-bold text-sm ring-2 transition"
                  :class="state.strobe_on ? 'bg-yellow-300 text-black ring-yellow-100' : 'bg-white/5 ring-white/20'">
            {{ state.strobe_on ? "AN" : "AUS" }} · S</button>
        </div>
        <SpeedControl :sync="state.strobe_sync" :mult="state.strobe_mult" :hz="state.strobe_hz" :bpm="bpm"
                      :min="0.5" :max="20" :mults="[0.25, 0.5, 1, 2, 4]"
                      @change="(c) => send({ ...(c.sync !== undefined && { strobe_sync: c.sync }),
                                             ...(c.mult !== undefined && { strobe_mult: c.mult }),
                                             ...(c.hz !== undefined && { strobe_hz: c.hz }) })" />
        <div class="flex gap-2 mt-3">
          <button @click="send({ strobe_white: !state.strobe_white })" class="flex-1 py-1.5 rounded-lg text-xs ring-1"
                  :class="state.strobe_white ? 'bg-white/30 ring-white/50' : 'bg-white/5 ring-white/10'">
            {{ state.strobe_white ? "Weiß blitzen" : "Effekte takten" }}</button>
          <button @click="send({ strobe_alt: !state.strobe_alt })" class="flex-1 py-1.5 rounded-lg text-xs ring-1"
                  :class="state.strobe_alt ? 'bg-yellow-400/30 ring-yellow-300/60' : 'bg-white/5 ring-white/10'">
            Strips abwechselnd</button>
        </div>
      </div>

      <div class="bg-white/5 rounded-xl p-4">
        <div class="flex justify-between text-xs uppercase text-gray-400 mb-3"><span>Dimmer</span>
          <span class="font-mono text-white text-sm">{{ Math.round(state.brightness * 100) }}%</span></div>
        <input type="range" min="0" max="1" step="0.01" :value="state.brightness"
               @input="send({ brightness: +$event.target.value })" class="w-full accent-fuchsia-500 h-10" />
        <div class="grid grid-cols-4 gap-1 mt-2">
          <button v-for="v in [0.1, 0.25, 0.5, 1]" :key="v" @click="send({ brightness: v })"
                  class="py-1.5 rounded bg-white/10 hover:bg-white/20 text-xs">{{ v * 100 }}%</button>
        </div>
      </div>
    </div>

    <!-- Szenen -->
    <div class="bg-white/5 rounded-xl p-4">
      <div class="flex flex-wrap items-center gap-2 mb-3">
        <span class="text-xs uppercase text-gray-400 mr-auto">Szenen
          <span class="normal-case">— eigene Effekt-Stapel, kombinierbar</span></span>
        <div class="flex rounded-lg bg-black/30 p-0.5 text-xs font-semibold">
          <button @click="send({ scene_exclusive: false })" class="px-2.5 py-1 rounded-md"
                  :class="!state.scene_exclusive ? 'bg-fuchsia-500 text-black' : 'text-gray-400'">Stapeln</button>
          <button @click="send({ scene_exclusive: true })" class="px-2.5 py-1 rounded-md"
                  :class="state.scene_exclusive ? 'bg-fuchsia-500 text-black' : 'text-gray-400'">Einzeln</button>
        </div>
        <button @click="createScene(false)" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold">+ Neue Szene</button>
        <button @click="createScene(true)" class="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-xs">+ aus Live-Pult</button>
      </div>
      <div class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
        <div v-for="sc in scenes" :key="sc.id" class="relative rounded-lg ring-1 overflow-hidden transition"
             :class="[isActive(sc.id) ? 'ring-fuchsia-300 bg-fuchsia-600/70' : 'ring-white/10 bg-white/5 hover:bg-white/15',
                      editId === sc.id ? 'outline outline-2 outline-offset-2 outline-cyan-300' : '']">
          <button @click="toggleScene(sc.id)" class="w-full pt-3 pb-4 px-2 text-sm font-semibold active:scale-95 transition">
            {{ sc.name }}
            <span class="block text-[10px] font-normal opacity-70">{{ isActive(sc.id) ? "AN" : "aus" }}</span>
          </button>
          <div class="absolute bottom-0 inset-x-0 h-1.5" :style="{ background: lookCss(sc) }"></div>
          <button @click.stop="editId = editId === sc.id ? null : sc.id" title="Szene programmieren"
                  class="absolute top-1 right-1 w-6 h-6 rounded-md bg-black/40 hover:bg-black/70 text-xs">✎</button>
        </div>
        <div v-if="!scenes.length" class="col-span-full text-sm text-gray-500 py-4 text-center">
          Noch keine Szenen — „+ Neue Szene" anlegen.</div>
      </div>
    </div>

    <!-- Effekte (Live-Pult oder Szene programmieren) -->
    <div class="rounded-xl p-4" :class="editScene ? 'bg-cyan-500/10 ring-2 ring-cyan-400/50' : 'bg-white/5'">
      <div v-if="editScene" class="flex flex-wrap items-center gap-2 mb-3">
        <span class="text-xs uppercase text-cyan-300">Szene programmieren:</span>
        <input :value="editScene.name" @change="sendTarget({ name: $event.target.value })"
               class="px-2 py-1 rounded bg-black/40 text-sm font-semibold w-40" />
        <label class="flex items-center gap-2 text-xs text-gray-400">Szenen-Stärke
          <input type="range" min="0" max="1" step="0.01" :value="editScene.level"
                 @input="sendTarget({ level: +$event.target.value })" class="w-28 accent-cyan-400" />
          <span class="font-mono w-9">{{ Math.round(editScene.level * 100) }}%</span></label>
        <button @click="sceneOp('move', { id: editId, delta: -1 })" class="px-2 py-1 rounded bg-white/10 text-xs" title="nach vorne">◀</button>
        <button @click="sceneOp('move', { id: editId, delta: 1 })" class="px-2 py-1 rounded bg-white/10 text-xs" title="nach hinten">▶</button>
        <button @click="deleteScene(editId)" class="px-2 py-1 rounded bg-red-500/30 hover:bg-red-500/50 text-xs">Löschen</button>
        <button @click="editId = null" class="ml-auto px-4 py-1.5 rounded-lg bg-cyan-500 text-black text-sm font-semibold">Fertig</button>
      </div>
      <div v-else class="flex justify-between text-xs uppercase text-gray-400 mb-3">
        <span>Live-Effekte <span class="normal-case">— beliebig kombinierbar, Szenen laufen zusätzlich</span></span>
        <span class="normal-case">✎ an einer Szene = Szene programmieren</span>
      </div>

      <div class="grid grid-cols-3 sm:grid-cols-6 lg:grid-cols-11 gap-2">
        <div v-for="e in EFFECTS" :key="e.id" class="relative rounded-lg ring-1 transition"
             :class="[layer(e.id).on ? 'bg-fuchsia-600 ring-fuchsia-300' : 'bg-white/5 ring-white/10 hover:bg-white/15',
                      focus === e.id ? 'outline outline-2 outline-offset-2 outline-white/70' : '']">
          <button @click="toggleEffect(e.id)" class="w-full pt-3 pb-2 flex flex-col items-center gap-0.5 text-sm font-medium active:scale-95 transition">
            <span class="text-xl">{{ e.icon }}</span>{{ e.label }}
            <span class="text-[10px] opacity-70">{{ layer(e.id).on ? "AN" : "aus" }} · {{ tempoBadge(layer(e.id)) }}</span>
          </button>
          <button @click.stop="focus = e.id" title="Farbe, Stärke & Tempo"
                  class="absolute top-1.5 right-1.5 w-5 h-5 rounded-full ring-2 ring-black/60"
                  :style="{ background: layerCss(e.id, target) }"></button>
        </div>
        <button @click="focus = 'base'" class="rounded-lg ring-1 py-3 flex flex-col items-center gap-1 text-sm font-medium"
                :class="focus === 'base' ? 'outline outline-2 outline-offset-2 outline-white/70 ring-white/30 bg-white/10' : 'ring-white/10 bg-white/5 hover:bg-white/15'">
          <span class="w-6 h-6 rounded-full ring-2 ring-black/60" :style="{ background: rgbCss(target.hue ?? 0, target.saturation ?? 1) }"></span>
          Grundfarbe<span class="text-[10px] opacity-60">für Auto-Farben</span>
        </button>
      </div>

      <!-- Eigene Muster -->
      <div class="flex items-center gap-2 mt-4 mb-2 text-xs uppercase text-gray-400">
        <span>Eigene Muster</span><span class="normal-case">— im Muster-Editor selbst programmiert</span></div>
      <div class="grid grid-cols-3 sm:grid-cols-6 lg:grid-cols-11 gap-2">
        <div v-for="pat in patterns" :key="pat.id" class="relative rounded-lg ring-1 transition overflow-hidden"
             :class="[layer('p_' + pat.id).on ? 'bg-fuchsia-600 ring-fuchsia-300' : 'bg-white/5 ring-white/10 hover:bg-white/15',
                      focus === 'p_' + pat.id ? 'outline outline-2 outline-offset-2 outline-white/70' : '']">
          <button @click="toggleEffect('p_' + pat.id)" class="w-full pt-3 pb-3 px-1 flex flex-col items-center gap-0.5 text-sm font-medium active:scale-95 transition">
            <span class="text-xl">🧩</span><span class="truncate max-w-full">{{ pat.name }}</span>
            <span class="text-[10px] opacity-70">{{ layer('p_' + pat.id).on ? "AN" : "aus" }} · {{ tempoBadge(layer('p_' + pat.id)) }}</span>
          </button>
          <div class="absolute bottom-0 inset-x-0 h-1.5" :style="{ background: patternCss(pat, target) }"></div>
          <button @click.stop="focus = 'p_' + pat.id" title="Stärke & Tempo"
                  class="absolute top-1 left-1 w-6 h-6 rounded-md bg-black/40 hover:bg-black/70 text-xs">⚙</button>
          <button @click.stop="editPatternId = pat.id; focus = 'p_' + pat.id" title="Muster bearbeiten"
                  class="absolute top-1 right-1 w-6 h-6 rounded-md bg-black/40 hover:bg-black/70 text-xs">✎</button>
        </div>
        <button @click="createPattern()" class="rounded-lg ring-1 ring-dashed ring-emerald-400/50 bg-emerald-500/10 hover:bg-emerald-500/20 py-3 flex flex-col items-center gap-1 text-sm font-medium">
          <span class="text-xl">＋</span>Neues Muster</button>
      </div>

      <!-- Editor des gewählten Effekts -->
      <div class="mt-4 pt-4 border-t border-white/10">
        <div v-if="focus === 'base'" class="max-w-xl">
          <div class="text-sm font-semibold mb-1">🎨 Grundfarbe</div>
          <p class="text-xs text-gray-400 mb-3">Flächen mit Auto-Farbe nehmen diese Farbe, Muster eine passende Akzentfarbe dazu.
            {{ editScene ? "" : "FLASH blitzt in dieser Farbe." }}</p>
          <ColorPicker :hue="target.hue" :saturation="target.saturation" :palette="palette"
                       @change="(c) => sendTarget(c)" />
        </div>
        <div v-else class="grid lg:grid-cols-2 gap-6">
          <div v-if="focused.pattern">
            <div class="text-sm font-semibold mb-2">🧩 {{ focused.label }}</div>
            <p class="text-xs text-gray-400 mb-3">{{ focused.pattern.segments }} Segmente · {{ focused.pattern.steps.length }} Schritte ·
              Übergang {{ focused.pattern.transition === "soft" ? "weich" : "hart" }}</p>
            <div class="h-6 rounded mb-3 ring-1 ring-white/10" :style="{ background: patternCss(focused.pattern, target) }"></div>
            <button @click="editPatternId = focused.pattern.id"
                    class="px-4 py-2 rounded-lg bg-cyan-500 text-black font-semibold text-sm">✎ Muster bearbeiten</button>
          </div>
          <div v-else>
            <div class="flex items-center justify-between mb-3">
              <span class="text-sm font-semibold">{{ focused.icon }} {{ focused.label }} — Farbe</span>
              <button v-if="focus !== 'rainbow'" @click="sendLayer(focus, { color_auto: !layer(focus).color_auto })"
                      class="px-3 py-1 rounded-lg ring-1 text-xs"
                      :class="layer(focus).color_auto ? 'bg-emerald-600/40 ring-emerald-400/60' : 'bg-white/5 ring-white/10'">
                Auto-Farbe {{ layer(focus).color_auto ? "AN" : "AUS" }}</button>
            </div>
            <p v-if="focus === 'rainbow'" class="text-sm text-gray-400">Regenbogen nutzt alle Farben.</p>
            <template v-else>
              <p v-if="layer(focus).color_auto" class="text-xs text-gray-400 mb-2">
                Automatisch {{ focused.kind === "Fläche" ? "die Grundfarbe" : "passend zur Grundfarbe" }} — Farbe antippen für eine eigene.</p>
              <div v-if="TWO_COLOR.includes(focus)" class="text-xs text-gray-400 mb-1">
                Farbe 1 {{ focus === "police" ? "(Segmente 1, 3, …)" : "(Anfang)" }}</div>
              <ColorPicker :hue="layer(focus).color_auto ? layer(focus).eff_hue ?? 0 : layer(focus).hue"
                           :saturation="layer(focus).color_auto ? layer(focus).eff_saturation ?? 1 : layer(focus).saturation"
                           :palette="palette" @change="(c) => sendLayer(focus, { ...c, color_auto: false })" />
              <template v-if="TWO_COLOR.includes(focus)">
                <div class="text-xs text-gray-400 mt-4 mb-1">Farbe 2 {{ focus === "police" ? "(Segmente 2, 4, …)" : "(Ende)" }}</div>
                <ColorPicker :hue="layer(focus).color_auto ? layer(focus).eff_hue2 ?? 0.62 : layer(focus).hue2"
                             :saturation="layer(focus).color_auto ? layer(focus).eff_saturation2 ?? 1 : layer(focus).saturation2"
                             :palette="palette"
                             @change="(c) => sendLayer(focus, { hue2: c.hue, saturation2: c.saturation, color_auto: false })" />
              </template>
            </template>
          </div>
          <div class="space-y-5">
            <div>
              <div class="flex justify-between text-sm mb-1"><span class="font-semibold">Stärke</span>
                <span class="font-mono">{{ Math.round((layer(focus).level ?? 1) * 100) }}%</span></div>
              <input type="range" min="0" max="1" step="0.01" :value="layer(focus).level"
                     @input="sendLayer(focus, { level: +$event.target.value })" class="w-full accent-fuchsia-500 h-8" />
            </div>
            <div v-if="focus === 'police'" class="space-y-3">
              <div>
                <div class="text-sm font-semibold mb-2">Aufteilung</div>
                <div class="grid grid-cols-4 gap-1">
                  <button v-for="n in [2, 4, 6, 8]" :key="n" @click="sendLayer('police', { segments: n })"
                          class="py-1.5 rounded-md text-sm ring-1"
                          :class="layer('police').segments === n ? 'bg-fuchsia-600/60 ring-fuchsia-300' : 'bg-white/5 ring-white/10 hover:bg-white/15'">
                    {{ n === 4 ? "Viertel" : n + " Teile" }}</button>
                </div>
              </div>
              <div class="grid grid-cols-2 gap-1">
                <button @click="sendLayer('police', { blink: true })" class="py-1.5 rounded-md text-sm ring-1"
                        :class="layer('police').blink ? 'bg-fuchsia-600/60 ring-fuchsia-300' : 'bg-white/5 ring-white/10'">
                  Doppelblitz 🚨</button>
                <button @click="sendLayer('police', { blink: false })" class="py-1.5 rounded-md text-sm ring-1"
                        :class="!layer('police').blink ? 'bg-fuchsia-600/60 ring-fuchsia-300' : 'bg-white/5 ring-white/10'">
                  Farbwechsel ⇄</button>
              </div>
            </div>
            <div v-if="focus === 'gradient'" class="grid grid-cols-2 gap-1">
              <button @click="sendLayer('gradient', { move: false })" class="py-1.5 rounded-md text-sm ring-1"
                      :class="!layer('gradient').move ? 'bg-fuchsia-600/60 ring-fuchsia-300' : 'bg-white/5 ring-white/10'">
                Statisch</button>
              <button @click="sendLayer('gradient', { move: true })" class="py-1.5 rounded-md text-sm ring-1"
                      :class="layer('gradient').move ? 'bg-fuchsia-600/60 ring-fuchsia-300' : 'bg-white/5 ring-white/10'">
                Bewegt ⇢</button>
            </div>
            <div v-if="focus !== 'solid' && !(focus === 'gradient' && !layer('gradient').move)">
              <div class="text-sm font-semibold mb-2">Tempo</div>
              <SpeedControl :sync="layer(focus).sync" :mult="layer(focus).mult" :hz="layer(focus).hz" :bpm="bpm"
                            :mults="mults" @change="(c) => sendLayer(focus, c)" />
              <p class="text-xs text-gray-500 mt-2">♩ Global = läuft im globalen Takt (×-Faktor pro Beat). TAP = eigenes Tempo eintippen.</p>
            </div>
            <button @click="sendLayer(focus, { on: !layer(focus).on })"
                    class="w-full py-2.5 rounded-lg font-semibold ring-1"
                    :class="layer(focus).on ? 'bg-fuchsia-600 ring-fuchsia-300' : 'bg-white/5 ring-white/10'">
              {{ focused.label }} {{ layer(focus).on ? "AN" : "AUS" }}{{ editScene ? ` in „${editScene.name}"` : "" }}</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Erweitert -->
    <details class="bg-white/5 rounded-xl p-4">
      <summary class="text-xs uppercase text-gray-400 cursor-pointer">Erweitert</summary>
      <div class="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-4">
        <div class="grid grid-cols-2 gap-2 sm:col-span-2">
          <button @click="send({ direction: -state.direction })"
                  class="py-2.5 rounded-lg text-sm ring-1 bg-white/5 ring-white/10 hover:bg-white/15">
            Richtung {{ state.direction > 0 ? "→" : "←" }}</button>
          <button v-for="o in [{ k: 'mirror', label: 'Gespiegelt ⇆' }, { k: 'beat_sync', label: 'Beat-Pump 🥁' },
                               { k: 'bump_beat', label: 'Bump auf jeden Beat' }]"
                  :key="o.k" @click="send({ [o.k]: !state[o.k] })" class="py-2.5 rounded-lg text-sm ring-1"
                  :class="state[o.k] ? 'bg-fuchsia-600/60 ring-fuchsia-300/60' : 'bg-white/5 ring-white/10 hover:bg-white/15'">
            {{ o.label }}</button>
        </div>
        <label class="block">
          <div class="flex justify-between text-sm mb-1"><span>Bump-Stärke</span>
            <span class="font-mono">{{ Math.round(state.bump_gain * 100) }}%</span></div>
          <input type="range" min="0" max="1" step="0.01" :value="state.bump_gain"
                 @input="send({ bump_gain: +$event.target.value })" class="w-full accent-sky-400" />
        </label>
        <label class="block">
          <div class="flex justify-between text-sm mb-1"><span>Bump-Länge</span>
            <span class="font-mono">{{ (+state.bump_decay).toFixed(2) }} s</span></div>
          <input type="range" min="0.05" max="1" step="0.01" :value="state.bump_decay"
                 @input="send({ bump_decay: +$event.target.value })" class="w-full accent-sky-400" />
        </label>
        <label class="block">
          <div class="flex justify-between text-sm mb-1"><span>Blinder ausblenden</span>
            <span class="font-mono">{{ (+state.blinder_fade).toFixed(1) }} s</span></div>
          <input type="range" min="0.2" max="5" step="0.1" :value="state.blinder_fade"
                 @input="send({ blinder_fade: +$event.target.value })" class="w-full accent-amber-300" />
        </label>
        <label class="block">
          <div class="flex justify-between text-sm mb-1"><span>Szenen überblenden</span>
            <span class="font-mono">{{ (+state.scene_fade).toFixed(1) }} s</span></div>
          <input type="range" min="0" max="5" step="0.1" :value="state.scene_fade"
                 @input="send({ scene_fade: +$event.target.value })" class="w-full accent-fuchsia-400" />
        </label>
      </div>
      <p class="text-xs text-gray-500 mt-4">
        Tastatur: Leertaste = Alles aus (halten) · B = Blinder · F = Flash · Enter = Bump · 1–9, 0 = Effekte · T = Tap · S = Strobe an/aus.
        Beat-Pump lässt alles im globalen Takt pumpen. Flächen (Solid, Atmen, Regenbogen, Farbwechsel) mischen sich wie Licht,
        Muster (Chase, Theater, Welle, Funkeln) liegen deckend darüber.
      </p>
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
.bump { animation: bump 0.3s ease-out; }
@keyframes bump { from { background: rgba(125, 211, 252, 0.9); color: #000; } to { background: rgba(56, 189, 248, 0.2); } }
.beat { animation: beat linear infinite; }
@keyframes beat { 0% { opacity: 1; transform: scale(1.3); } 30% { opacity: 0.25; transform: scale(1); } 100% { opacity: 0.15; } }
</style>
