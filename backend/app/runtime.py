"""Runtime-Layer — verdrahtet alle Komponenten und die entkoppelten Tasks.

Tasks (alle supervised, self-healing):
* **audio_task** — AudioSource → Analyse → ``audio.analysis``.
* **render_task** — FrameClock (30–44 Hz) → ShowEngine → Outputs; UI gethrottelt.
* **mass_task** — Music-Assistant-Client (Player-State, Steuerung), optional.

Latenzkritischer Pfad (Audio→Render→Output) ist von langsamem I/O (MASS/HTTP)
entkoppelt: MASS-Zustand wird gecacht, Cover-Farbe asynchron geladen.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from .audio.analysis import Analyzer
from .audio.models import AnalysisFrame
from .audio.source import build_source
from .config import Settings, get_settings
from .core.clock import FrameClock
from .core.engine import Engine
from .core.event_bus import EventBus
from .effects.compositor import ShowEngine
from .effects.config import ShowConfig
from .integrations.color import fetch_hue
from .integrations.home_assistant import HAClient
from .integrations.lookahead import LookAhead
from .integrations.models import PlayerState
from .integrations.music_assistant import MassClient
from .output.artnet import ArtnetOutput
from .output.base import OutputRouter
from .output.virtual import VirtualOutput
from .output.wled import WledOutput
from .persistence.console import ConsoleManager
from .persistence.devices import load_devices, save_devices
from .persistence.store import DropStore

log = logging.getLogger(__name__)


class AppState:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.bus = EventBus()
        self.supervisor = Engine(self.bus)

        self.show_cfg = ShowConfig.load(self.settings.data_dir)
        pixels = self.settings.led_count

        # Output-Router: virtueller Preview + WLED-Knoten.
        self.router = OutputRouter()
        self.preview = VirtualOutput(pixels=pixels)
        self.router.add(self.preview)
        self._pixels = pixels

        # Geräte: persistierte Liste (UI-verwaltet); Erstbefüllung aus ENV.
        self._devices_path = f"{self.settings.data_dir}/devices.json"
        self.devices = load_devices(self._devices_path)
        if not self.devices:
            self.devices = [
                {"id": n.id, "name": n.name or n.id, "host": n.host, "pixels": n.pixels, "port": n.port}
                for n in self.settings.all_wled_nodes()
            ]
            if self.devices:
                save_devices(self._devices_path, self.devices)
        for d in self.devices:
            self.router.add(self._make_output(d))

        fixtures = len(self.devices) or self.settings.fixtures
        self.show = ShowEngine(self.show_cfg, pixels=pixels, fixtures=fixtures)

        # Licht-Pult + Home Assistant.
        self.console = ConsoleManager(f"{self.settings.data_dir}/console.json")
        self.ha = HAClient(self.settings.ha_url, self.settings.ha_token)

        analysis_rate = self.settings.audio_sample_rate / self.settings.audio_block_size
        self.analyzer = Analyzer(
            sample_rate=self.settings.audio_sample_rate,
            fft_size=self.settings.fft_size,
            n_bands=self.settings.bands,
            frame_rate=analysis_rate,
        )
        self.latest_analysis = AnalysisFrame(bands=[0.0] * self.settings.bands)
        self._preview_decimator = 0

        # ── Music Assistant + Look-ahead ──
        self.player = PlayerState(online=False)
        self._player_ts = 0.0        # loop.time() der letzten Player-Aktualisierung
        self._player_elapsed = 0.0
        self.store = DropStore(f"{self.settings.data_dir}/lightshow.sqlite")
        self.lookahead = LookAhead()
        self._http: httpx.AsyncClient | None = None
        self._last_cover_url = ""
        self._source = None  # aktive AudioSource (für Steuerung, z. B. SendSpin)
        # MASS-WS-Client nur mit Token (die MASS-2.9-WS-API verlangt Auth). Ohne Token
        # aus → kein Spam; Player-Metadaten kommen dann über SendSpin.
        self.mass = (
            MassClient(self.settings.mass_url, self.settings.mass_player_id, on_state=self._on_player_state)
            if (self.settings.mass_url and self.settings.mass_token) else None
        )

    # ── Tasks ──
    async def _audio_task(self) -> None:
        source = build_source(self.settings, on_metadata=self._on_sendspin_meta)
        self._source = source
        log.info("Audio-Quelle: %s", source.name)
        try:
            async for pcm in source.frames():
                frame = self.analyzer.process(pcm)
                self.latest_analysis = frame
                self.bus.publish("audio.analysis", frame)
        finally:
            self._source = None
            await source.close()

    async def _render_task(self) -> None:
        clock = FrameClock(float(self.settings.frame_rate))
        loop = asyncio.get_running_loop()
        last = loop.time()
        async for _ in clock.ticks():
            now = loop.time()
            dt = now - last
            last = now
            a = self.latest_analysis

            buildup, predicted = self._lookahead_step(now, a)
            buf, fixture_gains = self.show.render(a, now, dt, buildup, predicted)
            await self.router.broadcast(buf, fixture_gains)

            self._preview_decimator = (self._preview_decimator + 1) % 4
            if self._preview_decimator == 0:
                self.bus.publish("render.preview", self.preview.as_hex())
                self.bus.publish("show.status", self.show.status)

    def _lookahead_step(self, now: float, a: AnalysisFrame) -> tuple[float, bool]:
        """Elapsed interpolieren, Realtime-Drops aufzeichnen, Build-up berechnen."""
        if not (self.player.online and self.player.is_playing and self.player.track.id):
            return 0.0, False
        elapsed = self._player_elapsed + (now - self._player_ts)
        if a.drop_now and self.lookahead.record_drop(elapsed):
            tid = self.player.track.id
            asyncio.create_task(asyncio.to_thread(self.store.add_drop, tid, elapsed))
        return self.lookahead.compute(elapsed)

    # ── MASS-Callback ──
    async def _on_player_state(self, state: PlayerState) -> None:
        loop = asyncio.get_running_loop()
        self.player = state
        self._player_ts = loop.time()
        self._player_elapsed = state.elapsed
        self.bus.publish("player.state", state.to_dict())

        # Track-Wechsel → Drops laden + Cover-Farbe.
        if state.track.id != self.lookahead.track_id:
            drops = await asyncio.to_thread(self.store.get_drops, state.track.id)
            self.lookahead.set_track(state.track.id, drops)
        if self.show_cfg.album_art_color and state.track.image_url != self._last_cover_url:
            self._last_cover_url = state.track.image_url
            asyncio.create_task(self._apply_cover_hue(state.track.image_url))

    async def _apply_cover_hue(self, url: str) -> None:
        hue = await fetch_hue(url, self._http)
        if hue is not None:
            self.show.set_base_hue(hue)
            log.info("Album-Cover-Farbe → base_hue=%.3f", hue)

    # ── SendSpin-Metadaten (Titel/Cover/State) → Player-Panel + Look-ahead ──
    def _on_sendspin_meta(self, meta: dict) -> None:
        """Sync-Callback aus dem SendSpin-Client (läuft im Event-Loop)."""
        loop = asyncio.get_running_loop()
        p = self.player
        p.online = bool(meta.get("online", p.online))
        if "state" in meta:
            p.state = meta["state"]
        if "artist" in meta:
            p.track.artist = meta["artist"]
        if "album" in meta:
            p.track.album = meta["album"]
        if "duration" in meta:
            p.track.duration = meta["duration"]
        if "elapsed" in meta:
            p.elapsed = meta["elapsed"]
            self._player_ts = loop.time()
            self._player_elapsed = meta["elapsed"]
        if "title" in meta:
            p.track.title = meta["title"]
        img = meta.get("image_url")
        if img and img != self._last_cover_url:
            self._last_cover_url = img
            p.track.image_url = img
            if self.show_cfg.album_art_color:
                asyncio.create_task(self._apply_cover_hue(img))
        # SendSpin liefert keine stabile Track-ID → Key aus Artist/Titel für Drops.
        tid = f"{p.track.artist}—{p.track.title}".strip("— ")
        if tid and tid != self.lookahead.track_id:
            p.track.id = tid
            asyncio.create_task(self._reload_drops(tid))
        self.bus.publish("player.state", p.to_dict())

    async def _reload_drops(self, track_id: str) -> None:
        drops = await asyncio.to_thread(self.store.get_drops, track_id)
        self.lookahead.set_track(track_id, drops)

    def register_tasks(self) -> None:
        self.supervisor.register("audio", self._audio_task, restart=True)
        self.supervisor.register("render", self._render_task, restart=True)
        if self.mass:
            self.supervisor.register("mass", self.mass.run, restart=True)

    async def start(self) -> None:
        self._http = httpx.AsyncClient(timeout=5)
        self.register_tasks()
        self.supervisor.start()

    async def stop(self) -> None:
        await self.supervisor.stop()
        await self.router.close()
        await self.ha.close()
        if self._http:
            await self._http.aclose()
        self.store.close()

    # ── Steuer-API (für REST/WS) ──
    def status(self) -> dict:
        return {
            "audio_source": self.settings.audio_source,
            "frame_rate": self.settings.frame_rate,
            "fixtures": self.show.fixtures,
            "show": self.show.status,
            "config": self.show_cfg.to_dict(),
            "player": self.player.to_dict(),
            "tasks": self.supervisor.status(),
            "devices": [
                {"id": d.id, "name": d.name, "pixels": d.pixels, "online": d.online}
                for d in self.router.devices
            ],
        }

    def update_config(self, changes: dict) -> list[str]:
        return self.show_cfg.update(changes)

    # ── Geräte-Verwaltung (WLED / ArtNet) ──
    def _make_output(self, d: dict):
        px = int(d.get("pixels", self._pixels))
        if d.get("type") == "artnet":
            return ArtnetOutput(d["id"], d.get("name") or d["id"], d["host"], px,
                                int(d.get("port", 6454)), int(d.get("universe", 0)))
        return WledOutput(d["id"], d.get("name") or d["id"], d["host"], px, int(d.get("port", 4048)))

    def list_devices(self) -> list[dict]:
        online = {d.id: d.online for d in self.router.devices}
        return [{**d, "online": online.get(d["id"])} for d in self.devices]

    def add_device(self, host: str, name: str = "", pixels: int | None = None,
                   type: str = "wled", port: int | None = None, universe: int = 0) -> dict:
        host = host.strip()
        prefix = "artnet" if type == "artnet" else "wled"
        dev_id = f"{prefix}-" + host.replace(".", "-").replace(":", "-")
        self.remove_device(dev_id)  # bestehendes gleiches Gerät ersetzen
        entry = {
            "id": dev_id, "type": type, "name": name.strip() or host, "host": host,
            "pixels": int(pixels or self._pixels),
            "port": int(port if port is not None else (6454 if type == "artnet" else 4048)),
        }
        if type == "artnet":
            entry["universe"] = int(universe)
        self.devices.append(entry)
        self.router.add(self._make_output(entry))
        save_devices(self._devices_path, self.devices)
        self._update_fixtures()
        return entry

    def remove_device(self, dev_id: str) -> bool:
        before = len(self.devices)
        self.devices = [d for d in self.devices if d["id"] != dev_id]
        self.router.remove(dev_id)
        save_devices(self._devices_path, self.devices)
        self._update_fixtures()
        return len(self.devices) < before

    def _update_fixtures(self) -> None:
        self.show.fixtures = len(self.devices) or self.settings.fixtures

    # ── Licht-Pult: Trigger einer Button/Fader-Aktion ──
    async def console_trigger(self, action: dict) -> bool:
        kind = action.get("type")
        if kind == "config":
            return bool(self.update_config({action["key"]: action["value"]}))
        if kind == "brightness":
            self.update_config({"brightness": float(action["value"])}); return True
        if kind == "base_hue":
            self.show.set_base_hue(float(action["value"])); return True
        if kind == "player":
            return await self.player_command(action.get("cmd", ""), action.get("value"))
        if kind == "ha":
            svc = action.get("service", "toggle")
            eid = action.get("entity_id", "")
            if svc == "toggle":
                return await self.ha.toggle(eid)
            if svc == "turn_on":
                return await self.ha.turn_on(eid)
            if svc == "turn_off":
                return await self.ha.turn_off(eid)
            return await self.ha.call_service(action.get("domain", "homeassistant"), svc,
                                              {"entity_id": eid} if eid else None)
        return False

    async def player_command(self, action: str, value: float | None = None) -> bool:
        """Playback-Steuerung — bevorzugt über die aktive SendSpin-Quelle, sonst MASS."""
        src = self._source
        if src is not None and hasattr(src, "command"):
            act = action
            if action == "play_pause":
                act = "pause" if self.player.state == "playing" else "play"
            if await src.command(act, value):
                return True
        if not self.mass:
            return False
        cmds = {
            "play": self.mass.play, "pause": self.mass.pause,
            "play_pause": self.mass.play_pause, "next": self.mass.next,
            "previous": self.mass.previous,
        }
        if action == "volume" and value is not None:
            return await self.mass.set_volume(value)
        fn = cmds.get(action)
        return await fn() if fn else False
