<script setup>
import { ref, reactive, onMounted, onUnmounted, computed, provide } from "vue";
import { Play, Pause, SkipBack, SkipForward, Music2, Plus, Trash2, Rainbow, Square, ChevronsRight, Power, Activity } from "lucide-vue-next";
import Console from "./Console.vue";
import Manual from "./Manual.vue";

const view = ref("dashboard");

// Betriebsart + manueller Pult-Zustand (per WS zwischen allen Clients synchron).
const mode = ref("auto");
const manual = reactive({
  layers: {}, hue: 0.62, saturation: 1, brightness: 1, direction: 1, mirror: false, beat_sync: false,
  bpm: 120, music_sync: false, strobe_on: false, strobe_hz: 8, strobe_sync: false, strobe_mult: 2,
  strobe_white: true, strobe_alt: false, blinder_fade: 1.5, bump_gain: 0.6, bump_decay: 0.16, bump_beat: false, scene_fade: 1, scene_exclusive: false,
  scenes: {}, scene_order: [], active_scenes: [], patterns: {}, pattern_order: [],
  blackout: false, blinder: false, flash: false,
});
const palette = ref([]);
const mults = ref([0.125, 0.25, 0.5, 1, 2, 4]);
const manualTouched = {};  // lokale Änderungen (Pfad → Zeit) kurz vor Server-Echos schützen (Fader-Jitter)
provide("manualTouched", manualTouched);
provide("wsSend", (msg) => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  ws.send(JSON.stringify(msg));
  return true;
});
// Server-Zustand feldweise übernehmen: frisch lokal geänderte Felder überspringen,
// abgeleitete Farben (eff_*) immer übernehmen, gelöschte Szenen entfernen.
function mergeState(target, src, path, now) {
  const isObj = (v) => v && typeof v === "object" && !Array.isArray(v);
  for (const [k, v] of Object.entries(src)) {
    const p = path ? `${path}.${k}` : k;
    if (isObj(v)) {
      if (!isObj(target[k])) target[k] = {};
      mergeState(target[k], v, p, now);
    } else if (k.startsWith("eff_") || !(now - (manualTouched[p] || 0) < 800)) {
      target[k] = v;
    }
  }
  if (path === "scenes" || path === "patterns") for (const k of Object.keys(target)) if (!(k in src)) delete target[k];
}
function applyManual(info) {
  if (!info) return;
  if (info.mode) mode.value = info.mode;
  if (info.palette) palette.value = info.palette;
  if (info.mults) mults.value = info.mults;
  if (info.state) mergeState(manual, info.state, "", Date.now());
}
provide("applyManual", applyManual);
async function setMode(m) {
  mode.value = m;
  if (m === "manual") view.value = "manual";
  await fetch("/api/mode", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: m }),
  });
}

const connected = ref(false);
const analysis = reactive({
  bands: [], rms: 0, peak: 0, bass: 0, mids: 0, highs: 0,
  energy: 0, mood: 0, bpm: 0, beat: false, onset: 0, drop: false,
  song_time: 0, silence: false,
});
const show = reactive({ scene: "—", pattern: "—", section: "verse", bass_passage: false, blackout: false, strobe: false, eff_intensity: 0, buildup: 0, drop: false, next_drop_s: null, coverage: 0 });
const SECTION_COLORS = { intro: "#60a5fa", build: "#f5a524", drop: "#f0534f", verse: "#a3a3ad", break: "#818cf8", outro: "#72727c" };
const SECTION_LABELS = { intro: "Intro", build: "Build-up", drop: "Drop / Chorus", verse: "Verse", break: "Breakdown", outro: "Outro" };
const player = reactive({ online: false, state: "idle", elapsed: 0, player_name: "", track: { title: "", artist: "", album: "", image_url: "", duration: 0 } });
const preview = ref([]);
const status = ref(null);
const cfg = reactive({
  intensity: 0.6, brightness: 1.0, smoothing: 0.5,
  blackouts: true, strobes: true, scene_seconds: 60,
});
const beatPulse = ref(0);

let ws = null, reconnectTimer = null, raf = null;

function wsUrl() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws`;
}
function connect() {
  ws = new WebSocket(wsUrl());
  ws.onopen = () => (connected.value = true);
  ws.onclose = () => { connected.value = false; reconnectTimer = setTimeout(connect, 1000); };
  ws.onerror = () => ws && ws.close();
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "analysis") {
      Object.assign(analysis, m.data);
      if (m.data.beat) beatPulse.value = 1;
    } else if (m.type === "preview") preview.value = m.data;
    else if (m.type === "show") Object.assign(show, m.data);
    else if (m.type === "player") Object.assign(player, m.data);
    else if (m.type === "manual") applyManual(m.data);
    else if (m.type === "status") {
      status.value = m.data; Object.assign(cfg, m.data.config);
      if (m.data.player) Object.assign(player, m.data.player);
      applyManual(m.data.manual);
      if (m.data.mode === "manual") view.value = "manual";
    }
  };
}
async function loadConfig() {
  const j = await (await fetch("/api/config")).json();
  Object.assign(cfg, j);
}
async function patch(changes) {
  await fetch("/api/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ changes }),
  });
}
async function playerCmd(action) {
  await fetch(`/api/player/${action}`, { method: "POST" });
}

const devices = ref([]);
const newDev = reactive({ host: "", name: "", pixels: 480, reverse: false });
async function testPattern(pattern) {
  await fetch("/api/devices/test", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pattern, seconds: 6 }),
  });
}
async function loadDevices() {
  devices.value = (await (await fetch("/api/devices")).json()).devices || [];
}
async function addDevice() {
  if (!newDev.host.trim()) return;
  const r = await fetch("/api/devices", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ host: newDev.host, name: newDev.name, pixels: newDev.pixels, reverse: newDev.reverse }),
  });
  devices.value = (await r.json()).devices || [];
  newDev.host = ""; newDev.name = "";
}
async function removeDevice(id) {
  const r = await fetch(`/api/devices/${id}`, { method: "DELETE" });
  devices.value = (await r.json()).devices || [];
}
const fmtTime = (s) => {
  s = Math.max(0, Math.floor(s || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

function animate() {
  beatPulse.value *= 0.85;
  raf = requestAnimationFrame(animate);
}
onMounted(() => { connect(); loadConfig(); loadDevices(); animate(); });
onUnmounted(() => { clearTimeout(reconnectTimer); cancelAnimationFrame(raf); ws && ws.close(); });

const pct = (v, s = 1) => Math.min(100, v * 100 * s);
const moodLabel = computed(() => (analysis.mood >= 0.45 ? "energisch" : "ruhig"));
const TABS = [{ id: "dashboard", label: "Dashboard" }, { id: "manual", label: "Manuell" }, { id: "console", label: "Pult" }];
const TEST_PATTERNS = [
  { id: "rainbow", label: "Regenbogen", icon: Rainbow }, { id: "solid", label: "Weiß", icon: Square },
  { id: "chase", label: "Lauflicht", icon: ChevronsRight }, { id: "off", label: "Aus", icon: Power },
];
const isSynthetic = computed(() => status.value?.audio_source === "synthetic");
</script>

<template>
  <div class="min-h-screen">
    <!-- Kopfzeile -->
    <header class="sticky top-0 z-40 border-b border-line bg-canvas/90 backdrop-blur">
      <div class="mx-auto max-w-[1400px] px-4 sm:px-6 flex flex-wrap items-center gap-x-6">
        <div class="flex items-center gap-2.5 h-14">
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <rect x="1" y="7" width="4" height="10" rx="1" fill="var(--color-accent)" />
            <rect x="7" y="2" width="4" height="15" rx="1" fill="var(--color-accent)" opacity=".8" />
            <rect x="13" y="10" width="4" height="7" rx="1" fill="var(--color-accent)" opacity=".55" />
          </svg>
          <span class="font-semibold tracking-tight text-[15px]">LightShow</span>
        </div>

        <nav class="order-last sm:order-none w-full sm:w-auto flex items-stretch gap-1 -mb-px h-10 sm:h-14">
          <button v-for="t in TABS" :key="t.id" @click="view = t.id"
                  class="px-3 text-[13px] font-medium border-b-2 transition-colors"
                  :class="view === t.id ? 'text-ink border-accent' : 'text-muted border-transparent hover:text-sub'">
            {{ t.label }}</button>
        </nav>

        <div class="ml-auto flex items-center gap-4 h-14">
          <div class="seg seg-accent" title="Betriebsart">
            <button :class="{ on: mode === 'auto' }" @click="setMode('auto')">Auto</button>
            <button :class="{ on: mode === 'manual' }" @click="setMode('manual')">Manuell</button>
          </div>
          <span class="flex items-center gap-2 text-xs text-sub">
            <span class="led" :class="connected ? 'live' : 'danger'"></span>
            <span class="hidden sm:inline">{{ connected ? "Verbunden" : "Getrennt" }}</span>
          </span>
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-[1400px] px-4 sm:px-6 py-5">
      <Manual v-if="view === 'manual'" :mode="mode" :state="manual" :palette="palette" :preview="preview"
              :mults="mults" :bpm-eff="mode === 'manual' ? show.bpm_eff || 0 : 0"
              :music-bpm="analysis.bpm" @set-mode="setMode" />
      <Console v-show="view === 'console'" />

      <div v-show="view === 'dashboard'" class="space-y-4">
        <div v-if="isSynthetic" class="notice">
          <Activity class="w-4 h-4 text-accent shrink-0" />
          <span>Audio-Quelle <span class="num text-ink">synthetic</span> — die Werte stammen aus einem Testsignal.
            Für echte Musik <span class="num text-ink">LIGHTSHOW_AUDIO_SOURCE</span> setzen.</span>
        </div>

        <div class="grid lg:grid-cols-12 gap-4">
          <!-- Player -->
          <section class="panel lg:col-span-7 p-4 flex items-center gap-4">
            <div class="w-[72px] h-[72px] rounded-md bg-raised border border-line overflow-hidden shrink-0 grid place-items-center">
              <img v-if="player.track.image_url" :src="player.track.image_url" class="w-full h-full object-cover" />
              <Music2 v-else class="w-5 h-5 text-faint" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="eyebrow mb-1">{{ !player.online ? "Music Assistant offline" : player.state === "playing" ? "Wiedergabe" : "Pausiert" }}</div>
              <div class="truncate font-medium text-[15px]">{{ player.track.title || "—" }}</div>
              <div class="truncate text-[13px] text-sub">{{ player.track.artist || " " }}</div>
              <div v-if="player.track.duration" class="mt-2.5 flex items-center gap-2.5 text-[11px] num text-muted">
                <span>{{ fmtTime(player.elapsed) }}</span>
                <div class="meter flex-1"><div :style="{ width: Math.min(100, (player.elapsed / player.track.duration) * 100) + '%' }"></div></div>
                <span>{{ fmtTime(player.track.duration) }}</span>
              </div>
            </div>
            <div class="flex items-center gap-1">
              <button @click="playerCmd('previous')" :disabled="!player.online" class="btn btn-ghost btn-icon" title="Zurück"><SkipBack /></button>
              <button @click="playerCmd('play_pause')" :disabled="!player.online" class="btn btn-primary btn-icon !w-10 !h-10 !rounded-full" title="Play/Pause">
                <Pause v-if="player.state === 'playing'" /><Play v-else class="translate-x-px" /></button>
              <button @click="playerCmd('next')" :disabled="!player.online" class="btn btn-ghost btn-icon" title="Weiter"><SkipForward /></button>
            </div>
          </section>

          <!-- Kennzahlen -->
          <section class="panel lg:col-span-5 grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4 divide-x divide-line">
            <div class="p-4">
              <div class="flex items-center justify-between"><span class="eyebrow">BPM</span>
                <span class="led" :class="{ on: beatPulse > 0.3 }"></span></div>
              <div class="display text-[30px] leading-tight mt-1.5">{{ analysis.bpm ? analysis.bpm.toFixed(0) : "—" }}</div>
            </div>
            <div class="p-4">
              <div class="eyebrow">Mood</div>
              <div class="mt-1.5 flex items-baseline gap-1.5"><span class="display text-[30px] leading-tight">{{ analysis.mood.toFixed(2) }}</span></div>
              <div class="text-[11px] text-muted -mt-0.5">{{ moodLabel }}</div>
            </div>
            <div class="p-4">
              <div class="eyebrow">Energie</div>
              <div class="display text-[30px] leading-tight mt-1.5">{{ Math.round(analysis.energy * 100) }}<span class="text-sm text-muted">%</span></div>
              <div class="meter mt-1.5"><div :style="{ width: pct(analysis.energy) + '%' }"></div></div>
            </div>
            <div class="p-4">
              <div class="eyebrow">Pegel</div>
              <div class="display text-[30px] leading-tight mt-1.5">{{ Math.round(analysis.rms * 100) }}<span class="text-sm text-muted">%</span></div>
              <div class="meter mt-1.5"><div :style="{ width: pct(analysis.rms, 2) + '%' }"></div></div>
            </div>
          </section>

          <!-- Spektrum -->
          <section class="panel lg:col-span-7">
            <div class="panel-h"><span class="eyebrow">Spektrum</span>
              <span class="ml-auto text-[11px] text-muted num">{{ analysis.bands.length }} Bänder</span></div>
            <div class="p-4">
              <div class="relative h-36 flex items-end gap-[3px]">
                <div class="absolute inset-0 flex flex-col justify-between pointer-events-none">
                  <div v-for="n in 4" :key="n" class="border-t border-line/70"></div>
                </div>
                <div v-for="(b, i) in analysis.bands" :key="i" class="relative flex-1 rounded-t-[2px] bg-sub/80"
                     :style="{ height: Math.max(1.5, b * 100) + '%' }"></div>
              </div>
              <div class="grid grid-cols-3 gap-4 mt-4">
                <div v-for="k in [['bass', 'Bass'], ['mids', 'Mitten'], ['highs', 'Höhen']]" :key="k[0]">
                  <div class="flex justify-between text-[11px] mb-1.5"><span class="text-muted">{{ k[1] }}</span>
                    <span class="num text-sub">{{ Math.round(analysis[k[0]] * 100) }}</span></div>
                  <div class="meter"><div :style="{ width: pct(analysis[k[0]]) + '%', background: k[0] === 'bass' ? 'var(--color-accent)' : '' }"></div></div>
                </div>
              </div>
            </div>
          </section>

          <!-- Show-Status -->
          <section class="panel lg:col-span-5">
            <div class="panel-h"><span class="eyebrow">Show</span>
              <span class="ml-auto flex items-center gap-2 text-xs text-sub">
                <span class="w-2 h-2 rounded-full" :style="{ background: SECTION_COLORS[show.section] || '#a3a3ad' }"></span>
                {{ SECTION_LABELS[show.section] || show.section }}</span></div>
            <div class="p-4 space-y-4">
              <div>
                <div class="text-[11px] text-muted mb-1">Aktive Szene</div>
                <div class="text-[15px] font-medium truncate">{{ show.scene }}
                  <span v-if="show.pattern && show.pattern !== 'full'" class="text-sub font-normal">· {{ show.pattern }}</span></div>
              </div>
              <div class="flex flex-wrap gap-1.5">
                <span v-if="analysis.silence" class="chip"><span class="led"></span>Stille</span>
                <span v-if="show.bass_passage" class="chip"><span class="led on"></span>Bass-Passage</span>
                <span v-if="show.strobe" class="chip"><span class="led on"></span>Strobe</span>
                <span v-if="show.blackout" class="chip"><span class="led danger"></span>Blackout</span>
                <span v-if="analysis.drop" class="chip !text-ink"><span class="led danger"></span>Drop</span>
                <span v-if="show.next_drop_s != null" class="chip">Drop in <span class="num text-ink">{{ show.next_drop_s }} s</span></span>
                <span v-if="show.coverage > 0" class="chip">Struktur <span class="num text-ink">{{ Math.round(show.coverage * 100) }} %</span> gelernt</span>
                <span v-if="!analysis.silence && !show.bass_passage && !show.strobe && !show.blackout && !analysis.drop && show.next_drop_s == null && !(show.coverage > 0)"
                      class="text-xs text-faint">Keine Ereignisse</span>
              </div>
              <div v-if="show.buildup > 0.01">
                <div class="flex justify-between text-[11px] mb-1.5"><span class="text-muted">Build-up</span>
                  <span class="num text-sub">{{ Math.round(show.buildup * 100) }} %</span></div>
                <div class="meter"><div :style="{ width: show.buildup * 100 + '%', background: 'var(--color-accent)' }"></div></div>
              </div>
            </div>
          </section>

          <!-- Ausgabe -->
          <section class="panel lg:col-span-12 p-4">
            <div class="flex items-center mb-2.5"><span class="eyebrow">Ausgabe</span>
              <span class="ml-auto text-[11px] text-muted num">{{ preview.length }} px</span></div>
            <div class="flex h-5 rounded-[4px] overflow-hidden bg-black border border-line">
              <div v-for="(c, i) in preview" :key="i" class="flex-1" :style="{ background: c }"></div>
            </div>
          </section>

          <!-- Show-Konfiguration -->
          <section class="panel lg:col-span-7">
            <div class="panel-h"><span class="eyebrow">Automatik</span>
              <span class="ml-auto text-[11px] text-muted">gilt im Auto-Modus</span></div>
            <div class="p-4 grid sm:grid-cols-2 gap-x-8 gap-y-4">
              <label class="block">
                <div class="flex justify-between text-[13px] mb-1"><span class="text-sub">Intensität</span>
                  <span class="num">{{ (+cfg.intensity).toFixed(2) }}</span></div>
                <input v-fill type="range" min="0" max="1" step="0.01" v-model.number="cfg.intensity" @change="patch({ intensity: cfg.intensity })" />
              </label>
              <label class="block">
                <div class="flex justify-between text-[13px] mb-1"><span class="text-sub">Helligkeit</span>
                  <span class="num">{{ Math.round(cfg.brightness * 100) }} %</span></div>
                <input v-fill type="range" min="0" max="1" step="0.01" v-model.number="cfg.brightness" @change="patch({ brightness: cfg.brightness })" />
              </label>
              <label class="block">
                <div class="flex justify-between text-[13px] mb-1"><span class="text-sub">Glättung</span>
                  <span class="num">{{ (+cfg.smoothing).toFixed(2) }}</span></div>
                <input v-fill type="range" min="0" max="0.95" step="0.01" v-model.number="cfg.smoothing" @change="patch({ smoothing: cfg.smoothing })" />
              </label>
              <label class="block">
                <div class="flex justify-between text-[13px] mb-1"><span class="text-sub">Szenendauer</span>
                  <span class="num">{{ cfg.scene_seconds }} s</span></div>
                <input v-fill type="range" min="5" max="180" step="5" v-model.number="cfg.scene_seconds" @change="patch({ scene_seconds: cfg.scene_seconds })" />
              </label>
              <div class="sm:col-span-2 flex flex-wrap gap-6 pt-1">
                <button v-for="o in [['blackouts', 'Blackouts'], ['strobes', 'Strobes']]" :key="o[0]"
                        @click="cfg[o[0]] = !cfg[o[0]]; patch({ [o[0]]: cfg[o[0]] })"
                        class="flex items-center gap-2.5 text-[13px] text-sub hover:text-ink">
                  <span class="switch" :class="{ on: cfg[o[0]] }"></span>{{ o[1] }}</button>
              </div>
            </div>
          </section>

          <!-- Geräte -->
          <section class="panel lg:col-span-5">
            <div class="panel-h"><span class="eyebrow">Geräte</span>
              <span class="ml-auto text-[11px] text-muted num">{{ devices.length }}</span></div>
            <div v-if="devices.length" class="divide-y divide-line">
              <div v-for="d in devices" :key="d.id" class="flex items-center gap-3 px-4 h-11 text-[13px]">
                <span class="led" :class="d.online === false ? 'danger' : 'live'"></span>
                <span class="font-medium truncate">{{ d.name }}</span>
                <span class="num text-xs text-muted">{{ d.host }}</span>
                <span v-if="d.pixels" class="num text-xs text-faint">{{ d.pixels }} px</span>
                <button @click="removeDevice(d.id)" class="btn btn-ghost btn-sm btn-icon ml-auto" title="Entfernen"><Trash2 /></button>
              </div>
            </div>
            <div v-else class="px-4 py-3 text-[13px] text-muted">Keine Geräte — nur die Vorschau ist aktiv.</div>
            <div class="p-4 border-t border-line space-y-3">
              <div class="grid grid-cols-[1fr_1fr_76px] gap-2">
                <input v-model="newDev.host" placeholder="IP-Adresse" class="field num" />
                <input v-model="newDev.name" placeholder="Name" class="field" />
                <input v-model.number="newDev.pixels" type="number" title="LEDs" class="field num no-spin" />
              </div>
              <div class="flex items-center gap-3">
                <button @click="newDev.reverse = !newDev.reverse" class="flex items-center gap-2.5 text-[13px] text-sub hover:text-ink">
                  <span class="switch" :class="{ on: newDev.reverse }"></span>Gespiegelt</button>
                <button @click="addDevice" class="btn btn-primary btn-sm ml-auto"><Plus />Hinzufügen</button>
              </div>
              <div class="pt-3 border-t border-line">
                <div class="text-[11px] text-muted mb-2">Testbild · 6 s</div>
                <div class="flex flex-wrap gap-1.5">
                  <button v-for="t in TEST_PATTERNS" :key="t.id" @click="testPattern(t.id)" class="btn btn-sm">
                    <component :is="t.icon" />{{ t.label }}</button>
                </div>
              </div>
            </div>
          </section>
        </div>

        <footer class="pt-2 pb-4 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-faint num">
          <span>Quelle {{ status?.audio_source ?? "…" }}</span>
          <span>{{ status?.frame_rate ?? "…" }} Hz</span>
          <span>{{ status?.fixtures ?? "…" }} Fixtures</span>
          <span>Intensität {{ show.eff_intensity ?? "–" }}</span>
        </footer>
      </div>
    </main>
  </div>
</template>
