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
  <div class="space-y-2.5">
    <div class="flex items-center gap-2">
      <div class="seg">
        <button :class="{ on: sync }" @click="emit('change', { sync: true })">Takt</button>
        <button :class="{ on: !sync }" @click="emit('change', { sync: false, hz: Math.round(effHz * 100) / 100 })">Frei</button>
      </div>
      <span class="ml-auto num text-[13px] text-sub">{{ fmtHz(effHz) }}<span class="text-muted"> Hz</span></span>
      <button :key="tapped" @pointerdown.prevent="tap" class="btn btn-sm tap-flash touch-none" title="Tempo eintippen">TAP</button>
    </div>
    <div v-if="sync" class="seg seg-fill">
      <button v-for="m in mults" :key="m" :class="{ on: mult === m }" @click="emit('change', { mult: m })">
        <span class="num">×{{ MULT_LABELS[m] }}</span></button>
    </div>
    <input v-else v-fill type="range" min="0" max="1000" step="1" :value="pos"
           @input="emit('change', { hz: Math.round(fromPos(+$event.target.value) * 100) / 100 })" />
  </div>
</template>

<style scoped>
.tap-flash { animation: tap-flash .25s ease-out; }
@keyframes tap-flash { from { background: var(--color-accent); color: var(--color-accent-ink); } }
</style>
