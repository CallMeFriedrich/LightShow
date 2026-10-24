<script setup>
import { computed, ref } from "vue";
import { createTapper, MULT_LABELS, fmtHz } from "./tap.js";

// Tempo eines Effekts/Strobes: synchron zum globalen Tempo (× Faktor) oder eigenes Tempo in Hz.
const props = defineProps({
  sync: { type: Boolean, default: true },
  mult: { type: Number, default: 1 },
  hz: { type: Number, default: 1 },
  bpm: { type: Number, default: 120 },          // effektives globales Tempo
  min: { type: Number, default: 0.02 },
  max: { type: Number, default: 10 },
  mults: { type: Array, default: () => [0.125, 0.25, 0.5, 1, 2, 4] },
});
const emit = defineEmits(["change"]);

const effHz = computed(() => (props.sync ? (props.bpm / 60) * props.mult : props.hz));
// Logarithmischer Slider (0…1000), damit langsame Tempi fein einstellbar sind.
const pos = computed(() => Math.round((Math.log(props.hz / props.min) / Math.log(props.max / props.min)) * 1000));
const fromPos = (p) => props.min * (props.max / props.min) ** (p / 1000);

const tapped = ref(0);
const tap = createTapper((hz) => {
  tapped.value++;
  if (hz) emit("change", { sync: false, hz: Math.min(props.max, Math.max(props.min, Math.round(hz * 100) / 100)) });
});
</script>

<template>
  <div>
    <div class="flex items-center gap-2 mb-2">
      <div class="flex rounded-lg bg-black/30 p-0.5 text-xs font-semibold">
        <button @click="emit('change', { sync: true })" class="px-2.5 py-1 rounded-md"
                :class="sync ? 'bg-cyan-500 text-black' : 'text-gray-400'">♩ Global</button>
        <button @click="emit('change', { sync: false, hz: Math.round(effHz * 100) / 100 })" class="px-2.5 py-1 rounded-md"
                :class="!sync ? 'bg-cyan-500 text-black' : 'text-gray-400'">Eigenes</button>
      </div>
      <span class="ml-auto font-mono text-sm">{{ fmtHz(effHz) }} Hz</span>
      <button :key="tapped" @pointerdown.prevent="tap"
              class="tap px-3 py-1 rounded-lg bg-cyan-500/20 ring-1 ring-cyan-300/50 text-xs font-bold active:bg-cyan-300 active:text-black touch-none">
        TAP</button>
    </div>
    <div v-if="sync" class="grid gap-1" :style="{ gridTemplateColumns: `repeat(${mults.length}, minmax(0,1fr))` }">
      <button v-for="m in mults" :key="m" @click="emit('change', { mult: m })"
              class="py-1.5 rounded-md text-sm ring-1"
              :class="mult === m ? 'bg-cyan-500/40 ring-cyan-300' : 'bg-white/5 ring-white/10 hover:bg-white/15'">
        ×{{ MULT_LABELS[m] }}</button>
    </div>
    <input v-else type="range" min="0" max="1000" step="1" :value="pos"
           @input="emit('change', { hz: Math.round(fromPos(+$event.target.value) * 100) / 100 })"
           class="w-full accent-cyan-400 h-8" />
  </div>
</template>

<style scoped>
.tap { animation: tap 0.25s ease-out; }
@keyframes tap { from { box-shadow: 0 0 0 5px rgba(103, 232, 249, 0.6); } to { box-shadow: 0 0 0 0 rgba(103, 232, 249, 0); } }
</style>
