<script setup>
import { ref, reactive, onMounted, onUnmounted, computed } from "vue";

const connected = ref(false);
const analysis = reactive({
  bands: [], rms: 0, peak: 0, bass: 0, mids: 0, highs: 0,
  energy: 0, mood: 0, bpm: 0, beat: false, onset: 0, drop: false,
  song_time: 0, silence: false,
});
const show = reactive({ scene: "—", pattern: "—", bass_passage: false, blackout: false, strobe: false, eff_intensity: 0, buildup: 0, drop: false });
const player = reactive({ online: false, state: "idle", elapsed: 0, player_name: "", track: { title: "", artist: "", album: "", image_url: "", duration: 0 } });
const preview = ref([]);
const status = ref(null);
const cfg = reactive({
  intensity: 0.6, brightness: 1.0, smoothing: 0.5,
  blackouts: true, strobes: true, scene_seconds: 60,
});
const beatPulse = ref(0);
const dropFlash = ref(0);

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
      if (m.data.drop) dropFlash.value = 1;
    } else if (m.type === "preview") preview.value = m.data;
    else if (m.type === "show") Object.assign(show, m.data);
    else if (m.type === "player") Object.assign(player, m.data);
    else if (m.type === "status") { status.value = m.data; Object.assign(cfg, m.data.config); if (m.data.player) Object.assign(player, m.data.player); }
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
const newDev = reactive({ host: "", name: "", pixels: 480 });
async function loadDevices() {
  devices.value = (await (await fetch("/api/devices")).json()).devices || [];
}
async function addDevice() {
  if (!newDev.host.trim()) return;
  const r = await fetch("/api/devices", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ host: newDev.host, name: newDev.name, pixels: newDev.pixels }),
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
  dropFlash.value *= 0.9;
  raf = requestAnimationFrame(animate);
}
onMounted(() => { connect(); loadConfig(); loadDevices(); animate(); });
onUnmounted(() => { clearTimeout(reconnectTimer); cancelAnimationFrame(raf); ws && ws.close(); });

const pct = (v, s = 1) => Math.min(100, v * 100 * s);
const moodLabel = computed(() => (analysis.mood >= 0.45 ? "energetic" : "calm"));
const isSynthetic = computed(() => status.value?.audio_source === "synthetic");
</script>

<template>
  <div class="min-h-screen p-4 sm:p-6 max-w-5xl mx-auto"
       :style="{ background: dropFlash > 0.05 ? `rgba(217,70,239,${dropFlash * 0.15})` : 'transparent' }">
    <header class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold tracking-tight">Light<span class="text-fuchsia-500">Show</span></h1>
      <div class="flex items-center gap-2 text-sm">
        <span class="w-2.5 h-2.5 rounded-full" :class="connected ? 'bg-emerald-400' : 'bg-red-500'"></span>
        {{ connected ? "verbunden" : "getrennt" }}
      </div>
    </header>

    <!-- Hinweis: Testsignal statt echter Musik -->
    <div v-if="isSynthetic"
         class="mb-4 px-4 py-2 rounded-lg bg-amber-500/15 ring-1 ring-amber-500/40 text-amber-200 text-sm">
      ⚠️ Audio-Quelle <span class="font-mono">synthetic</span> — die Werte stammen aus einem
      <b>Testsignal</b>, nicht aus echter Musik. Für Musik-Reaktivität
      <span class="font-mono">LIGHTSHOW_AUDIO_SOURCE=snapcast</span> setzen.
    </div>

    <!-- Music Assistant Player -->
    <div class="bg-white/5 rounded-xl p-4 mb-4 flex items-center gap-4">
      <div class="w-16 h-16 rounded-lg bg-black/40 overflow-hidden flex-shrink-0 ring-1 ring-white/10">
        <img v-if="player.track.image_url" :src="player.track.image_url" class="w-full h-full object-cover" />
      </div>
      <div class="min-w-0 flex-1">
        <div v-if="player.online" class="truncate font-medium">
          {{ player.track.title || "—" }}
        </div>
        <div v-else class="text-gray-500 text-sm">Music Assistant offline</div>
        <div class="truncate text-sm text-gray-400">{{ player.track.artist }}</div>
        <div v-if="player.track.duration" class="flex items-center gap-2 mt-1 text-xs text-gray-500">
          <span class="font-mono">{{ fmtTime(player.elapsed) }}</span>
          <div class="flex-1 h-1 bg-black/40 rounded overflow-hidden">
            <div class="h-full bg-fuchsia-500"
                 :style="{ width: Math.min(100, (player.elapsed / player.track.duration) * 100) + '%' }"></div>
          </div>
          <span class="font-mono">{{ fmtTime(player.track.duration) }}</span>
        </div>
      </div>
      <div class="flex items-center gap-1">
        <button @click="playerCmd('previous')" :disabled="!player.online"
                class="w-9 h-9 rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-30">⏮</button>
        <button @click="playerCmd('play_pause')" :disabled="!player.online"
                class="w-11 h-11 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-500 disabled:opacity-30 text-lg">
          {{ player.state === "playing" ? "⏸" : "▶" }}
        </button>
        <button @click="playerCmd('next')" :disabled="!player.online"
                class="w-9 h-9 rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-30">⏭</button>
      </div>
    </div>

    <!-- Kennzahlen -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
      <div class="bg-white/5 rounded-xl p-4">
        <div class="text-xs uppercase text-gray-400">BPM</div>
        <div class="text-3xl font-mono">{{ analysis.bpm.toFixed(0) }}</div>
      </div>
      <div class="bg-white/5 rounded-xl p-4">
        <div class="text-xs uppercase text-gray-400">Mood</div>
        <div class="text-xl font-mono">{{ analysis.mood.toFixed(2) }}
          <span class="text-xs text-gray-400">{{ moodLabel }}</span></div>
        <div class="h-2 bg-black/40 rounded mt-1 overflow-hidden">
          <div class="h-full bg-amber-400" :style="{ width: pct(analysis.mood) + '%' }"></div>
        </div>
      </div>
      <div class="bg-white/5 rounded-xl p-4">
        <div class="text-xs uppercase text-gray-400">Energy</div>
        <div class="h-2 bg-black/40 rounded mt-2 overflow-hidden">
          <div class="h-full bg-cyan-400" :style="{ width: pct(analysis.energy) + '%' }"></div>
        </div>
      </div>
      <div class="bg-white/5 rounded-xl p-4 transition-all"
           :style="{ boxShadow: `0 0 ${beatPulse * 40}px rgba(217,70,239,${beatPulse})` }">
        <div class="text-xs uppercase text-gray-400">Beat</div>
        <div class="text-3xl" :style="{ transform: `scale(${1 + beatPulse * 0.4})` }">●</div>
      </div>
    </div>

    <!-- Bass / Mitten / Höhen -->
    <div class="grid grid-cols-3 gap-3 mb-4">
      <div v-for="k in ['bass','mids','highs']" :key="k" class="bg-white/5 rounded-xl p-3">
        <div class="text-xs uppercase text-gray-400 mb-1">{{ k }}</div>
        <div class="h-2 bg-black/40 rounded overflow-hidden">
          <div class="h-full" :class="k==='bass'?'bg-red-500':k==='mids'?'bg-lime-400':'bg-sky-400'"
               :style="{ width: pct(analysis[k]) + '%' }"></div>
        </div>
      </div>
    </div>

    <!-- Aktuelle Szene -->
    <div class="bg-white/5 rounded-xl p-4 mb-4">
      <div class="flex items-center justify-between flex-wrap gap-2">
        <div>
          <div class="text-xs uppercase text-gray-400">Aktive Szene</div>
          <div class="text-lg font-medium">{{ show.scene }} · <span class="text-gray-400">{{ show.pattern }}</span></div>
        </div>
        <div class="flex gap-2">
          <span v-if="analysis.silence" class="px-2 py-1 rounded bg-blue-500/30 text-xs">idle</span>
          <span v-if="show.bass_passage" class="px-2 py-1 rounded bg-red-500/30 text-xs">bass</span>
          <span v-if="show.strobe" class="px-2 py-1 rounded bg-yellow-400/40 text-xs">strobe</span>
          <span v-if="show.blackout" class="px-2 py-1 rounded bg-black text-xs ring-1 ring-white/20">blackout</span>
          <span v-if="analysis.drop" class="px-2 py-1 rounded bg-fuchsia-500/40 text-xs">DROP</span>
        </div>
      </div>
      <div v-if="show.buildup > 0.01" class="mt-2">
        <div class="flex justify-between text-xs text-gray-400 mb-1"><span>Build-up (Look-ahead)</span>
          <span class="font-mono">{{ Math.round(show.buildup * 100) }}%</span></div>
        <div class="h-1.5 bg-black/40 rounded overflow-hidden">
          <div class="h-full bg-orange-400 transition-[width] duration-100" :style="{ width: show.buildup * 100 + '%' }"></div>
        </div>
      </div>
    </div>

    <!-- Frequenzbänder -->
    <div class="bg-white/5 rounded-xl p-4 mb-4">
      <div class="text-xs uppercase text-gray-400 mb-3">Frequenzbänder</div>
      <div class="flex items-end gap-1 h-32">
        <div v-for="(b, i) in analysis.bands" :key="i" class="flex-1 rounded-t transition-[height] duration-75"
             :style="{ height: Math.max(2, b * 100) + '%',
                       background: `hsl(${200 - i * (200 / analysis.bands.length)} 90% 55%)` }"></div>
      </div>
    </div>

    <!-- LED-Preview -->
    <div class="bg-white/5 rounded-xl p-4 mb-4">
      <div class="text-xs uppercase text-gray-400 mb-3">LED-Preview ({{ preview.length }} px)</div>
      <div class="flex h-8 rounded-lg overflow-hidden ring-1 ring-white/10">
        <div v-for="(c, i) in preview" :key="i" class="flex-1" :style="{ background: c }"></div>
      </div>
    </div>

    <!-- Show-Konfiguration -->
    <div class="bg-white/5 rounded-xl p-4">
      <div class="text-xs uppercase text-gray-400 mb-4">Show-Konfiguration</div>
      <div class="grid sm:grid-cols-2 gap-x-8 gap-y-4">
        <label class="block">
          <div class="flex justify-between text-sm mb-1"><span>Intensität</span>
            <span class="font-mono">{{ (+cfg.intensity).toFixed(2) }}</span></div>
          <input type="range" min="0" max="1" step="0.01" v-model.number="cfg.intensity"
                 @change="patch({ intensity: cfg.intensity })" class="w-full accent-fuchsia-500" />
        </label>
        <label class="block">
          <div class="flex justify-between text-sm mb-1"><span>Helligkeit</span>
            <span class="font-mono">{{ Math.round(cfg.brightness * 100) }}%</span></div>
          <input type="range" min="0" max="1" step="0.01" v-model.number="cfg.brightness"
                 @change="patch({ brightness: cfg.brightness })" class="w-full accent-fuchsia-500" />
        </label>
        <label class="block">
          <div class="flex justify-between text-sm mb-1"><span>Glättung (Anti-Flicker)</span>
            <span class="font-mono">{{ (+cfg.smoothing).toFixed(2) }}</span></div>
          <input type="range" min="0" max="0.95" step="0.01" v-model.number="cfg.smoothing"
                 @change="patch({ smoothing: cfg.smoothing })" class="w-full accent-fuchsia-500" />
        </label>
        <label class="block">
          <div class="flex justify-between text-sm mb-1"><span>Szenendauer</span>
            <span class="font-mono">{{ cfg.scene_seconds }}s</span></div>
          <input type="range" min="5" max="180" step="5" v-model.number="cfg.scene_seconds"
                 @change="patch({ scene_seconds: cfg.scene_seconds })" class="w-full accent-fuchsia-500" />
        </label>
      </div>
      <div class="flex gap-6 mt-4">
        <label class="flex items-center gap-2 text-sm">
          <input type="checkbox" v-model="cfg.blackouts" @change="patch({ blackouts: cfg.blackouts })"
                 class="accent-fuchsia-500" /> Blackouts
        </label>
        <label class="flex items-center gap-2 text-sm">
          <input type="checkbox" v-model="cfg.strobes" @change="patch({ strobes: cfg.strobes })"
                 class="accent-fuchsia-500" /> Strobes
        </label>
      </div>
    </div>

    <!-- WLED-Geräte -->
    <div class="bg-white/5 rounded-xl p-4 mt-4">
      <div class="text-xs uppercase text-gray-400 mb-3">WLED-Geräte</div>
      <div v-if="devices.length" class="space-y-2 mb-3">
        <div v-for="d in devices" :key="d.id" class="flex items-center gap-3 text-sm">
          <span class="w-2 h-2 rounded-full flex-shrink-0"
                :class="d.id==='virtual' ? 'bg-gray-500' : (d.online===false ? 'bg-red-500' : 'bg-emerald-400')"></span>
          <span class="font-medium">{{ d.name }}</span>
          <span class="text-gray-400 font-mono text-xs">{{ d.host || "Preview" }}</span>
          <span v-if="d.pixels" class="text-gray-500 text-xs">· {{ d.pixels }} px</span>
          <button v-if="d.host" @click="removeDevice(d.id)"
                  class="ml-auto text-xs px-2 py-1 rounded bg-red-500/20 hover:bg-red-500/40">Entfernen</button>
        </div>
      </div>
      <div v-else class="text-sm text-gray-500 mb-3">Noch keine WLED-Geräte — nur virtueller Preview.</div>
      <div class="flex flex-wrap items-end gap-2">
        <label class="text-xs text-gray-400">IP-Adresse
          <input v-model="newDev.host" placeholder="10.10.1.50"
                 class="block mt-1 px-2 py-1 rounded bg-black/40 text-sm w-40 font-mono" /></label>
        <label class="text-xs text-gray-400">Name
          <input v-model="newDev.name" placeholder="Links"
                 class="block mt-1 px-2 py-1 rounded bg-black/40 text-sm w-28" /></label>
        <label class="text-xs text-gray-400">LEDs
          <input v-model.number="newDev.pixels" type="number"
                 class="block mt-1 px-2 py-1 rounded bg-black/40 text-sm w-20" /></label>
        <button @click="addDevice"
                class="px-4 py-1.5 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-500 text-sm font-medium">Hinzufügen</button>
      </div>
    </div>

    <footer class="mt-8 text-center text-xs text-gray-500">
      Quelle: {{ status?.audio_source ?? "…" }} · {{ status?.frame_rate ?? "…" }} Hz ·
      Fixtures: {{ status?.fixtures ?? "…" }} · eff. Intensität: {{ show.eff_intensity }}
    </footer>
  </div>
</template>
