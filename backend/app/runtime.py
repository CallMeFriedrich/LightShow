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
from .integrations.lookahead import LookAhead
from .integrations.models import PlayerState
from .integrations.music_assistant import MassClient
from .output.base import OutputRouter
from .output.virtual import VirtualOutput
from .output.wled import WledOutput
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
        wled_nodes = self.settings.all_wled_nodes()
        for node in wled_nodes:
            self.router.add(
                WledOutput(node.id, node.name or node.id, node.host, node.pixels, node.port)
            )
        fixtures = len(wled_nodes) or self.settings.fixtures
        self.show = ShowEngine(self.show_cfg, pixels=pixels, fixtures=fixtures)

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
        # MASS-WS-Client nur mit Token (die MASS-2.9-WS-API verlangt Auth). Ohne Token
        # aus → kein Spam; Player-Metadaten kommen dann über SendSpin.
        self.mass = (
            MassClient(self.settings.mass_url, self.settings.mass_player_id, on_state=self._on_player_state)
            if (self.settings.mass_url and self.settings.mass_token) else None
        )

    # ── Tasks ──
    async def _audio_task(self) -> None:
        source = build_source(self.settings, on_metadata=self._on_sendspin_meta)
        log.info("Audio-Quelle: %s", source.name)
        try:
            async for pcm in source.frames():
                frame = self.analyzer.process(pcm)
                self.latest_analysis = frame
                self.bus.publish("audio.analysis", frame)
        finally:
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

    async def player_command(self, action: str, value: float | None = None) -> bool:
        """Delegiert Player-Kommandos an MASS (No-op, wenn MASS nicht konfiguriert)."""
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
