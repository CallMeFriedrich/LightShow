import { createApp } from "vue";
import App from "./App.vue";
import "./style.css";

const app = createApp(App);

// v-fill: Füllstand eines Faders (input type=range) als CSS-Variable --fill,
// damit die Spur bis zum Regler eingefärbt ist (WebKit/Blink; Firefox kann das nativ).
function setFill(el) {
  const min = Number(el.min || 0), max = Number(el.max || 100);
  const p = max > min ? ((Number(el.value) - min) / (max - min)) * 100 : 0;
  el.style.setProperty("--fill", `${Math.min(100, Math.max(0, p))}%`);
}
app.directive("fill", {
  mounted(el) { setFill(el); el.addEventListener("input", () => setFill(el)); },
  updated: setFill,
});

app.mount("#app");
