<script setup>
import { computed } from "vue";

// Farbe als (hue, saturation) bei voller Helligkeit — Helligkeit regeln Stärke/Dimmer.
const props = defineProps({
  hue: { type: Number, default: 0 },
  saturation: { type: Number, default: 1 },
  palette: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
});
const emit = defineEmits(["change"]);

const pick = (h, s) => emit("change", { hue: Math.min(0.999, Math.max(0, h)), saturation: Math.min(1, Math.max(0, s)) });

// Farbfeld: x = Farbton, y = Sättigung (oben weiß, unten volle Farbe).
function padPick(e) {
  const r = e.currentTarget.getBoundingClientRect();
  pick((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height);
}
function padDown(e) {
  if (props.disabled) return;
  e.currentTarget.setPointerCapture?.(e.pointerId);
  padPick(e);
}

function hsvToRgb(h, s) {
  const i = Math.floor(h * 6), f = h * 6 - i, p = 1 - s, q = 1 - s * f, t = 1 - s * (1 - f);
  const [r, g, b] = [[1, t, p], [q, 1, p], [p, 1, t], [p, q, 1], [t, p, 1], [1, p, q]][((i % 6) + 6) % 6];
  return [r, g, b].map((v) => Math.round(v * 255));
}
const toHex = (h, s) => "#" + hsvToRgb(h, s).map((v) => v.toString(16).padStart(2, "0")).join("");
function fromHex(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h = 0;
  if (d) h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  pick(((h / 6) + 1) % 1, max ? d / max : 0);
}

const hex = computed(() => toHex(props.hue, props.saturation));
const isSel = (p) => Math.abs(p.saturation - props.saturation) < 0.02 &&
  (p.saturation < 0.02 || Math.abs(p.hue - props.hue) < 0.005);
defineExpose({ toHex });
</script>

<template>
  <div :class="disabled ? 'opacity-40 pointer-events-none' : ''">
    <div class="grid grid-cols-11 gap-1.5 mb-3">
      <button v-for="p in palette" :key="p.name" @click="pick(p.hue, p.saturation)" :title="p.name"
              class="aspect-square rounded-md ring-2 transition active:scale-90"
              :class="isSel(p) ? 'ring-white scale-110' : 'ring-white/10'"
              :style="{ background: toHex(p.hue, p.saturation) }"></button>
    </div>
    <div class="relative h-28 rounded-lg overflow-hidden cursor-crosshair touch-none ring-1 ring-white/10"
         @pointerdown="padDown" @pointermove="$event.buttons && !disabled && padPick($event)">
      <div class="absolute inset-0" style="background: linear-gradient(to right,#f00,#ff0,#0f0,#0ff,#00f,#f0f,#f00)"></div>
      <div class="absolute inset-0" style="background: linear-gradient(to bottom,#fff,rgba(255,255,255,0))"></div>
      <div class="absolute w-5 h-5 rounded-full ring-2 ring-black border-2 border-white -translate-x-1/2 -translate-y-1/2 pointer-events-none"
           :style="{ left: hue * 100 + '%', top: saturation * 100 + '%', background: hex }"></div>
    </div>
    <div class="flex items-center gap-3 mt-2 text-xs text-gray-400">
      <label class="flex items-center gap-2 cursor-pointer">
        <input type="color" :value="hex" @input="fromHex($event.target.value)"
               class="w-8 h-8 rounded bg-transparent cursor-pointer" />
        <span class="font-mono">{{ hex }}</span>
      </label>
      <span class="ml-auto">oben = weiß · unten = volle Farbe</span>
    </div>
  </div>
</template>
