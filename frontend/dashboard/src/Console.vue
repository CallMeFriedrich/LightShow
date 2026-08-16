<script setup>
import { ref, reactive, onMounted } from "vue";

const layout = reactive({ columns: 6, controls: [] });
const canUndo = ref(false);
const canRedo = ref(false);
const editMode = ref(false);
const showAdd = ref(false);
const dragIndex = ref(-1);

// Vordefinierte Aktionen für den Hinzufügen-Dialog (einfache Zuordnung).
const PRESETS = {
  button: [
    { label: "Blackouts AN", action: { type: "config", key: "blackouts", value: true } },
    { label: "Blackouts AUS", action: { type: "config", key: "blackouts", value: false } },
    { label: "Strobes AN", action: { type: "config", key: "strobes", value: true } },
    { label: "Strobes AUS", action: { type: "config", key: "strobes", value: false } },
    { label: "Play / Pause", action: { type: "player", cmd: "play_pause" } },
    { label: "Nächster Titel", action: { type: "player", cmd: "next" } },
    { label: "HA: Gerät schalten", action: { type: "ha", service: "toggle", entity_id: "switch.nebelmaschine" }, hint: "entity_id anpassen" },
  ],
  fader: [
    { label: "Intensität", bind: { type: "config", key: "intensity" } },
    { label: "Helligkeit", bind: { type: "brightness" } },
    { label: "Glättung", bind: { type: "config", key: "smoothing" } },
    { label: "Basis-Farbe", bind: { type: "base_hue" } },
  ],
  xy: [
    { label: "Intensität × Glättung", bindX: { type: "config", key: "intensity" }, bindY: { type: "config", key: "smoothing" } },
  ],
};

const addType = ref("button");
const addPreset = ref(0);

async function load() {
  const r = await (await fetch("/api/console")).json();
  Object.assign(layout, r.layout);
  canUndo.value = r.can_undo; canRedo.value = r.can_redo;
}
async function save() {
  const r = await (await fetch("/api/console", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ layout: { columns: layout.columns, controls: layout.controls } }),
  })).json();
  canUndo.value = r.can_undo; canRedo.value = r.can_redo;
}
async function undo() { apply(await (await fetch("/api/console/undo", { method: "POST" })).json()); }
async function redo() { apply(await (await fetch("/api/console/redo", { method: "POST" })).json()); }
function apply(r) { Object.assign(layout, r.layout); canUndo.value = r.can_undo; canRedo.value = r.can_redo; }

function addControl() {
  const p = PRESETS[addType.value][addPreset.value];
  const c = { id: "c" + Date.now(), type: addType.value, label: p.label, ...structuredClone(p) };
  delete c.hint;
  layout.controls.push(c);
  showAdd.value = false;
  save();
}
function removeControl(i) { layout.controls.splice(i, 1); save(); }

// Drag & Drop zum Umsortieren (freie Anordnung im Grid).
function onDragStart(i) { dragIndex.value = i; }
function onDrop(i) {
  if (dragIndex.value < 0 || dragIndex.value === i) return;
  const [moved] = layout.controls.splice(dragIndex.value, 1);
  layout.controls.splice(i, 0, moved);
  dragIndex.value = -1;
  save();
}

// Aktionen ausführen (Trigger ans Backend).
async function trigger(action) {
  await fetch("/api/console/trigger", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
}
function faderInput(c, e) {
  const v = parseFloat(e.target.value);
  trigger({ ...c.bind, value: v });
}
function xyMove(c, e) {
  const rect = e.currentTarget.getBoundingClientRect();
  const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
  const y = Math.min(1, Math.max(0, 1 - (e.clientY - rect.top) / rect.height));
  c._x = x; c._y = y;
  trigger({ ...c.bindX, value: x });
  trigger({ ...c.bindY, value: y });
}

onMounted(load);
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-4">
      <div class="text-xs uppercase text-gray-400">Digitales Licht-Pult</div>
      <div class="flex gap-2">
        <button @click="undo" :disabled="!canUndo"
                class="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-30 text-sm">↶ Undo</button>
        <button @click="redo" :disabled="!canRedo"
                class="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-30 text-sm">↷ Redo</button>
        <button @click="editMode = !editMode"
                class="px-3 py-1.5 rounded-lg text-sm"
                :class="editMode ? 'bg-fuchsia-600' : 'bg-white/10 hover:bg-white/20'">
          {{ editMode ? "Fertig" : "Bearbeiten" }}</button>
        <button v-if="editMode" @click="showAdd = true"
                class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-sm">+ Hinzufügen</button>
      </div>
    </div>

    <div class="grid gap-3" :style="{ gridTemplateColumns: `repeat(${layout.columns}, minmax(0, 1fr))` }">
      <div v-for="(c, i) in layout.controls" :key="c.id"
           :draggable="editMode" @dragstart="onDragStart(i)" @dragover.prevent @drop="onDrop(i)"
           class="relative rounded-xl bg-white/5 ring-1 ring-white/10 p-3 min-h-[90px] flex flex-col"
           :class="editMode ? 'cursor-move' : ''">
        <button v-if="editMode" @click="removeControl(i)"
                class="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-red-500 text-xs">×</button>
        <div class="text-xs text-gray-300 mb-2 truncate">{{ c.label }}</div>

        <button v-if="c.type === 'button'" @click="!editMode && trigger(c.action)"
                class="flex-1 rounded-lg bg-fuchsia-600/80 hover:bg-fuchsia-500 active:scale-95 transition text-sm font-medium">
          Auslösen</button>

        <input v-else-if="c.type === 'fader'" type="range"
               :min="c.bind.type === 'base_hue' ? 0 : 0" :max="1" step="0.01"
               @input="faderInput(c, $event)" :disabled="editMode"
               class="mt-auto w-full accent-fuchsia-500" />

        <div v-else-if="c.type === 'xy'" @pointermove="!editMode && ($event.buttons && xyMove(c, $event))"
             @pointerdown="!editMode && xyMove(c, $event)"
             class="flex-1 rounded-lg bg-black/40 relative overflow-hidden touch-none">
          <div class="absolute w-3 h-3 rounded-full bg-fuchsia-400 -translate-x-1/2 -translate-y-1/2"
               :style="{ left: (c._x ?? 0.5) * 100 + '%', top: (1 - (c._y ?? 0.5)) * 100 + '%' }"></div>
        </div>
      </div>

      <div v-if="!layout.controls.length" class="col-span-full text-sm text-gray-500 py-8 text-center">
        Noch leer. „Bearbeiten" → „+ Hinzufügen", um Buttons/Fader/XY-Pads anzulegen.
      </div>
    </div>

    <!-- Hinzufügen-Dialog -->
    <div v-if="showAdd" class="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-50"
         @click.self="showAdd = false">
      <div class="bg-neutral-900 rounded-xl p-5 w-full max-w-sm ring-1 ring-white/10">
        <div class="text-sm font-medium mb-3">Control hinzufügen</div>
        <label class="block text-xs text-gray-400 mb-1">Typ</label>
        <select v-model="addType" @change="addPreset = 0"
                class="w-full mb-3 px-2 py-1.5 rounded bg-black/40 text-sm">
          <option value="button">Button</option>
          <option value="fader">Fader</option>
          <option value="xy">XY-Pad</option>
        </select>
        <label class="block text-xs text-gray-400 mb-1">Funktion</label>
        <select v-model.number="addPreset" class="w-full mb-4 px-2 py-1.5 rounded bg-black/40 text-sm">
          <option v-for="(p, idx) in PRESETS[addType]" :key="idx" :value="idx">{{ p.label }}</option>
        </select>
        <p v-if="PRESETS[addType][addPreset]?.hint" class="text-xs text-amber-300 mb-3">
          Hinweis: {{ PRESETS[addType][addPreset].hint }} (danach im JSON/späteren Editor anpassbar)
        </p>
        <div class="flex justify-end gap-2">
          <button @click="showAdd = false" class="px-3 py-1.5 rounded bg-white/10 text-sm">Abbrechen</button>
          <button @click="addControl" class="px-3 py-1.5 rounded bg-fuchsia-600 text-sm">Hinzufügen</button>
        </div>
      </div>
    </div>
  </div>
</template>
