<script setup>
import { ref, reactive, onMounted } from "vue";
import { Undo2, Redo2, Pencil, Plus, X, LayoutGrid } from "lucide-vue-next";

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
    { label: "Modus: AUTO", action: { type: "mode", value: "auto" } },
    { label: "Modus: MANUELL", action: { type: "mode", value: "manual" } },
    { label: "Manuell: Chase an/aus", action: { type: "manual", toggle: "chase" } },
    { label: "Manuell: Regenbogen an/aus", action: { type: "manual", toggle: "rainbow" } },
    { label: "Manuell: Funkeln an/aus", action: { type: "manual", toggle: "sparkle" } },
    { label: "Manuell: Polizei an/aus", action: { type: "manual", toggle: "police" } },
    { label: "Manuell: Verlauf an/aus", action: { type: "manual", toggle: "gradient" } },
    { label: "Manuell: Strobe an/aus", action: { type: "manual", flip: "strobe_on" } },
    { label: "Manuell: Bump", action: { type: "manual", bump: true } },
    { label: "Szene an/aus (Name)", action: { type: "scene", name: "Party" }, hint: "Szenen-Name anpassen" },
    { label: "HA: Gerät schalten", action: { type: "ha", service: "toggle", entity_id: "switch.nebelmaschine" }, hint: "entity_id anpassen" },
  ],
  fader: [
    { label: "Intensität", bind: { type: "config", key: "intensity" } },
    { label: "Helligkeit", bind: { type: "brightness" } },
    { label: "Glättung", bind: { type: "config", key: "smoothing" } },
    { label: "Basis-Farbe", bind: { type: "base_hue" } },
    { label: "Manuell: Dimmer", bind: { type: "manual", key: "brightness" } },
    { label: "Manuell: Farbton", bind: { type: "manual", key: "hue" } },
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
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <div>
        <div class="text-[15px] font-medium">Pult</div>
        <div class="text-[12px] text-muted">Eigene Buttons, Fader und XY-Pads für häufige Aktionen.</div>
      </div>
      <div class="ml-auto flex items-center gap-1.5">
        <button @click="undo" :disabled="!canUndo" class="btn btn-sm btn-ghost btn-icon" title="Rückgängig"><Undo2 /></button>
        <button @click="redo" :disabled="!canRedo" class="btn btn-sm btn-ghost btn-icon" title="Wiederholen"><Redo2 /></button>
        <button v-if="editMode" @click="showAdd = true" class="btn btn-sm"><Plus />Hinzufügen</button>
        <button @click="editMode = !editMode" class="btn btn-sm" :class="editMode ? 'btn-primary' : ''">
          <Pencil v-if="!editMode" />{{ editMode ? "Fertig" : "Bearbeiten" }}</button>
      </div>
    </div>

    <div class="grid gap-3" :style="{ gridTemplateColumns: `repeat(${layout.columns}, minmax(0, 1fr))` }">
      <div v-for="(c, i) in layout.controls" :key="c.id"
           :draggable="editMode" @dragstart="onDragStart(i)" @dragover.prevent @drop="onDrop(i)"
           class="panel relative p-3 min-h-[96px] flex flex-col gap-2"
           :class="editMode ? 'cursor-move !border-dashed !border-line-strong' : ''">
        <button v-if="editMode" @click="removeControl(i)" title="Entfernen"
                class="absolute top-1.5 right-1.5 btn btn-ghost btn-sm btn-icon hover:!text-danger"><X /></button>
        <div class="text-[12px] text-sub truncate pr-6">{{ c.label }}</div>

        <button v-if="c.type === 'button'" @click="!editMode && trigger(c.action)"
                class="flex-1 rounded-[7px] border border-line-strong bg-raised text-[13px] font-medium hover:bg-hover active:bg-accent active:text-accent-ink active:border-transparent transition-colors">
          Auslösen</button>

        <input v-else-if="c.type === 'fader'" v-fill type="range" min="0" max="1" step="0.01" value="0"
               @input="faderInput(c, $event)" :disabled="editMode" class="mt-auto" />

        <div v-else-if="c.type === 'xy'" @pointermove="!editMode && ($event.buttons && xyMove(c, $event))"
             @pointerdown="!editMode && xyMove(c, $event)"
             class="flex-1 min-h-[80px] rounded-[7px] bg-canvas border border-line relative overflow-hidden touch-none"
             style="background-image: linear-gradient(var(--color-line) 1px, transparent 1px), linear-gradient(90deg, var(--color-line) 1px, transparent 1px); background-size: 25% 25%;">
          <div class="absolute w-3 h-3 rounded-full bg-accent shadow-[0_0_10px_var(--color-accent)] -translate-x-1/2 -translate-y-1/2"
               :style="{ left: (c._x ?? 0.5) * 100 + '%', top: (1 - (c._y ?? 0.5)) * 100 + '%' }"></div>
        </div>
      </div>

      <div v-if="!layout.controls.length" class="col-span-full panel border-dashed py-12 flex flex-col items-center gap-2 text-center">
        <LayoutGrid class="w-5 h-5 text-faint" />
        <div class="text-[13px] text-sub">Das Pult ist noch leer.</div>
        <div class="text-[12px] text-muted">Über „Bearbeiten" → „Hinzufügen" Buttons, Fader oder XY-Pads anlegen.</div>
      </div>
    </div>

    <!-- Hinzufügen-Dialog -->
    <div v-if="showAdd" class="fixed inset-0 z-50 bg-black/70 backdrop-blur-[2px] flex items-center justify-center p-4" @click.self="showAdd = false">
      <div class="panel w-full max-w-sm shadow-2xl shadow-black/60">
        <div class="panel-h"><span class="text-[13px] font-medium">Control hinzufügen</span>
          <button @click="showAdd = false" class="btn btn-ghost btn-sm btn-icon ml-auto"><X /></button></div>
        <div class="p-4 space-y-3">
          <div>
            <div class="text-[12px] text-muted mb-1.5">Typ</div>
            <div class="seg seg-fill">
              <button v-for="t in [['button', 'Button'], ['fader', 'Fader'], ['xy', 'XY-Pad']]" :key="t[0]"
                      :class="{ on: addType === t[0] }" @click="addType = t[0]; addPreset = 0">{{ t[1] }}</button>
            </div>
          </div>
          <label class="block">
            <div class="text-[12px] text-muted mb-1.5">Funktion</div>
            <select v-model.number="addPreset" class="field w-full">
              <option v-for="(p, idx) in PRESETS[addType]" :key="idx" :value="idx">{{ p.label }}</option>
            </select>
          </label>
          <p v-if="PRESETS[addType][addPreset]?.hint" class="text-[12px] text-accent">
            {{ PRESETS[addType][addPreset].hint }} — danach in <span class="num">data/console.json</span> anpassbar.</p>
          <div class="flex justify-end gap-2 pt-1">
            <button @click="showAdd = false" class="btn btn-sm btn-ghost">Abbrechen</button>
            <button @click="addControl" class="btn btn-sm btn-primary">Hinzufügen</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
