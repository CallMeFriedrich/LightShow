# LightShow — Architektur

> Modulares, containerisiertes Licht- & Effektsteuerungssystem.
> Audio-reaktive Lichtsteuerung, synchron zu einer Music-Assistant-Player-Gruppe.
>
> **Status:** Greenfield. Dieses Dokument ist die verbindliche Referenz. Änderungen an
> der Architektur werden **zuerst hier** dokumentiert, dann implementiert.

---

## 1. Leitprinzipien

1. **Strikte Entkopplung (AsyncIO).** Audio-Analyse, Effekt-Rendering, Output-Broadcasting
   (30–44 Hz) und WebSocket-Kommunikation laufen als eigenständige `asyncio`-Tasks. Kein
   Task darf einen anderen blockieren. Kommunikation ausschließlich über einen internen
   **Event-Bus** (async pub/sub) und **bounded Queues** (Drop-Oldest statt Backpressure-Stau).
2. **Fehlertoleranz first.** Ausfall von Home Assistant, Music Assistant oder eines
   WLED/ArtNet-Knotens darf die Audio-/Licht-Engine **nie** blockieren oder crashen. Jede
   externe Integration hat autonome Reconnect-Logik mit Backoff und einen definierten
   Degraded-Mode.
3. **Latenz < 10 ms im UI-Pfad.** Der Render→Output-Pfad ist von langsamen I/O-Operationen
   (HTTP zu MASS/HA) entkoppelt. UI-Updates werden gethrottelt, nicht pro Frame gepusht.
4. **Austauschbare Treiber/Quellen.** `AudioSource`, `OutputDevice` und `Integration` sind
   abstrakte Schnittstellen. Neue Quellen (PCM/TCP), Outputs (ArtNet/DMX) oder Integrationen
   werden ohne Änderung des Kerns nachgerüstet.
5. **Konfiguration über Umgebungsvariablen** (12-Factor). Kein Hardcoding von Hosts/Ports.
   `.env` für lokale WSL-Tests, vorbereitet für GitHub-Release.

---

## 2. Systemüberblick

```
                          ┌──────────────────────────────────────────────┐
                          │                LightShow Server               │
                          │              (Python, FastAPI, AsyncIO)       │
  Music Assistant         │                                              │
  ┌───────────┐  Snapcast │   ┌───────────┐   ┌───────────┐  ┌─────────┐ │   WLED-Knoten
  │  MASS     │──stream──▶│──▶│ AudioSource│─▶│ Analysis  │─▶│ Effect  │ │   ┌────────┐
  │  Player-  │           │   │ (Snapcast) │  │ FFT/Beat/ │  │ Engine  │─┼──▶│ WLED 1 │ (DDP)
  │  Gruppe   │◀─control──│   └───────────┘  │ Bands/    │  │ (Render │ │   ├────────┤
  └───────────┘  (WS/API) │        │         │ Onset     │  │  30–44Hz│─┼──▶│ WLED n │
                          │        │         └─────┬─────┘  └────┬────┘ │   └────────┘
  Home Assistant          │        │               │             │      │
  ┌───────────┐  WS/REST  │   ┌────▼───────────────▼─────────────▼────┐ │   ArtNet/DMX
  │   HA      │◀─────────▶│   │            Event-Bus (async)          │ │   ┌────────┐
  └───────────┘           │   └────┬───────────────┬─────────────┬────┘ │   │ Fixture│ (opt.)
                          │        │               │             │      │   └────────┘
                          │   ┌────▼────┐     ┌─────▼─────┐  ┌────▼────┐ │
                          │   │ WS-Hub  │     │ REST API  │  │ Output  │ │
                          │   │ (UI)    │     │           │  │ Router  │ │
                          │   └────┬────┘     └───────────┘  └─────────┘ │
                          └────────┼─────────────────────────────────────┘
                                   │  WebSocket + REST (LAN)
                       ┌───────────┴───────────┐
                  ┌────▼─────┐            ┌─────▼──────┐
                  │Dashboard │            │ Licht-Pult │   (Vue 3 + Vite + Tailwind)
                  │(Interf.1)│            │ (Interf.2) │
                  └──────────┘            └────────────┘
```

---

## 3. Backend-Module

Verzeichnis: `backend/app/`

| Modul | Verantwortung | Status |
|-------|---------------|--------|
| `config.py` | Pydantic-Settings aus ENV, zentrale Konfiguration | Slice 1 |
| `core/event_bus.py` | Async Pub/Sub, typisierte Topics, Drop-Oldest-Queues | Slice 1 |
| `core/engine.py` | Orchestrator: startet/überwacht alle Tasks (Supervisor) | Slice 1 |
| `core/clock.py` | Frame-Clock für konstante Output-Rate (30–44 Hz) | Slice 1 |
| `audio/source.py` | `AudioSource`-ABC + Factory | Slice 1 |
| `audio/snapcast.py` | Snapcast-Client (PCM via `snapclient`-Subprozess) | Slice 1 |
| `audio/sendspin.py` | SendSpin-Client (natives MASS-Protokoll, via `aiosendspin`) | Slice 2 |
| `audio/synthetic.py` | Synthetische Quelle (Testen ohne Hardware) | Slice 1 |
| `audio/analysis.py` | Realtime-FFT, Frequenzbänder, Beat/BPM, Onset | Slice 1 |
| `audio/models.py` | `PCMFrame`, `AnalysisFrame` (Dataclasses) | Slice 1 |
| `output/base.py` | `OutputDevice`-ABC + Router | Slice 1 |
| `output/wled.py` | WLED-Treiber (DDP-Push, JSON-State) | Slice 1 |
| `output/virtual.py` | Virtueller Output (Preview im UI, Tests) | Slice 1 |
| `output/artnet.py` | ArtNet/DMX (UDP) | Slice 3 (Stub) |
| `effects/base.py` | `Layer`-ABC, `RenderContext`, Farb-/Zeichen-Helfer | Slice 1 |
| `effects/config.py` | `ShowConfig` (persistente `[config]`-Parameter, §Regelwerk) | Slice 1 |
| `effects/baselayers.py` | Ambient, BassWash, Spectrum, Idle | Slice 1 |
| `effects/features.py` | ColorDrift, Comet, Dual, Bounce, Theater, Quad | Slice 1 |
| `effects/bass.py` | BlockToggle, BassBounce (Bass-Passagen) | Slice 1 |
| `effects/overlays.py` | BeatPulse, Sparkle | Slice 1 |
| `effects/sectors.py` | Sektor-Muster/Masken (mirror, feather, floor) | Slice 1 |
| `effects/scene.py` | SceneManager (mood-Pools, Gewichtung, Richtung) | Slice 1 |
| `effects/output_fx.py` | Blackout, Strobe (Output-Layer) | Slice 1 |
| `effects/compositor.py` | `ShowEngine` — komponiert die Show pro Frame | Slice 1 |
| `api/ws.py` | WebSocket-Hub (State-Broadcast, Kommandos) | Slice 1 |
| `api/routes.py` | REST (Status, Effekte, Player, Pult-Layout) | Slice 1 |
| `integrations/music_assistant.py` | MASS-WS-Client: Player-State, Steuerung, Reconnect | Slice 2 |
| `integrations/color.py` | Album-Cover-Farbe → `base_hue` (§1) | Slice 2 |
| `integrations/lookahead.py` | Build-ups vor bekannten Drops (§9) | Slice 2 |
| `integrations/home_assistant.py` | HA: WS/REST, Geräte schalten | Slice 3 (Stub) |
| `persistence/store.py` | SQLite: erkannte Drops pro Track (§9) | Slice 2 |
| `main.py` | FastAPI-App, Lifespan, Static-Serving | Slice 1 |

### 3.1 Datenfluss (Hot Path, latenzkritisch)

```
AudioSource ──PCMFrame──▶ Analysis ──AnalysisFrame──▶ EffectEngine ──FrameBuffer──▶ OutputRouter ──▶ WLED
                                          │
                                          └──(throttled, ~15 Hz)──▶ WS-Hub ──▶ UI
```

- **Hot Path** (Audio→Output) nutzt direkte `asyncio.Queue`s mit `maxsize` und Drop-Oldest.
- **UI-Pfad** ist bewusst entkoppelt & gethrottelt (max. ~15 Hz), damit langsame Clients den
  Render-Loop nie ausbremsen.
- **Kein `await` auf externes HTTP** (MASS/HA) im Hot Path. Deren Zustand wird gecacht.

### 3.2 Event-Bus Topics

| Topic | Payload | Producer | Consumer |
|-------|---------|----------|----------|
| `audio.pcm` | `PCMFrame` | AudioSource | Analysis |
| `audio.analysis` | `AnalysisFrame` | Analysis | EffectEngine, WS-Hub |
| `render.frame` | `FrameBuffer` | EffectEngine | OutputRouter, WS-Hub (preview) |
| `control.command` | `Command` | WS-Hub/REST | EffectEngine, Integrations |
| `system.status` | `StatusEvent` | alle | WS-Hub |

---

## 4. Audio-Pipeline

- **Quelle:** Snapcast. Music Assistant streamt an eine Player-Gruppe
  (Gäste-Lautsprecher + Licht-Server) über einen Snapcast-Server. Auf dem Licht-Host läuft
  ein `snapclient`, dessen PCM-Ausgabe LightShow einliest. Dadurch **phasensynchron** zur
  Beschallung, ohne Audiokabel.
- **Abstraktion:** `AudioSource` liefert normierte `PCMFrame`s (float32, mono/stereo,
  konfigurierbare Samplerate/Blockgröße). Implementierungen: `SendSpinSource` (natives
  MASS-Protokoll), `SnapcastSource`, `PcmTcpSource` (roher PCM/TCP), `SyntheticSource`
  (Testsignal, Default-Fallback wenn keine Quelle erreichbar — hält die Pipeline lebendig).
- **SendSpin (bevorzugt, Slice 2):** SendSpin ist das native, sample-genaue MASS-Protokoll
  (die Boxen des Nutzers verwenden es bereits). `SendSpinSource` setzt auf die offizielle
  Bibliothek `aiosendspin` auf — diese kapselt Noise-`KKpsk2`-Handshake, Framing, Clock-Sync
  und Codec-Decoding (FLAC/PCM → PCM). Wir registrieren uns als **Player** (unpaired,
  Sentinel-PSK, `trust_level='none'`) und erhalten dekodierte PCM-Chunks. Modi: `listen`
  (mDNS-Advertising, MASS verbindet sich) oder `connect` (aktives Anwählen). **Status v0.1:**
  gegen die Bibliothek verifiziert, Live-Test an der MASS-Instanz steht aus.
- **Analyse** (`analysis.py`, reine NumPy-Berechnung im Executor/dediziertem Task):
  - **FFT** mit Hann-Fenster, konfigurierbare FFT-Größe.
  - **Frequenzbänder** (log-verteilt, z. B. 8/16/32 Bänder) → normalisierte Magnituden.
  - **Beat/BPM:** Energie-basierte Onset-Detection (Spectral Flux) + Tempo-Schätzung über
    Autokorrelation der Onset-Envelope. (Upgrade-Pfad: `aubio`/`librosa` optional.)
  - **Onset-Flags** für perkussive Trigger.
  - Ergebnis: `AnalysisFrame` (bands, rms/peak, bpm, beat_now, onset).

---

## 5. Output-Engine

- **WLED (Primär):** `WledOutput` via **DDP** (UDP:4048) für Realtime-Pixel-Push; WLED-JSON-API
  (HTTP) für State/Segmente/native Effekte. DDP ist verbindungslos → ideal für
  Fehlertoleranz (Paketverlust unkritisch, kein Blocking).
- **OutputRouter:** mappt den gerenderten `FrameBuffer` auf 1..n Output-Geräte
  (Segment-/Pixel-Mapping). Broadcastet mit fester Rate über `core/clock.py`.
- **ArtNet/DMX (Sekundär, Slice 3):** `ArtnetOutput` (UDP). Datenmodell generisch:
  Fixtures mit Kanal-Definitionen (Dimmer, RGB, Strobe, ...), damit LED-Streifen, Nebel,
  Laser und später weitere DMX-Geräte ohne Kern-Änderung ergänzt werden können.
- **Virtueller Output:** spiegelt den Frame ins UI (Live-Preview) und für Tests ohne Hardware.

### 5.1 Fixture-/Geräte-Datenmodell (vorbereitet für DMX)

```
Device
 ├─ id, name, type: "wled" | "artnet" | "virtual"
 ├─ transport: { host, port, protocol }
 └─ mapping:
     ├─ pixel_count (LED)  ODER
     └─ channels: [ {name, offset, type: dimmer|red|green|blue|strobe|...} ]  (DMX)
```

---

## 5a. Show-Engine (Effekt-Regelwerk)

Die Effekt-Logik folgt dem **Effekt-Regelwerk** (siehe `docs/EFFEKT-REGELWERK.md`).
Die `ShowEngine` (`effects/compositor.py`) komponiert je Frame eine **float-Canvas**
[0,1] aus gestapelten Layern und quantisiert am Ende nach uint8.

**Layer-Reihenfolge pro Frame:**
1. **Inhalt** — je nach Zustand:
   - *Idle* (Stille): blauer Grund + beiger Chase (§8).
   - *Bass-Passage* (`bass>0.4 & highs<0.22 & mids<0.45`): Base/Spectrum gedämpft,
     darüber BlockToggle **oder** BassBounce (§5).
   - *Normal*: Ambient → BassWash → Spectrum → Feature-Effekt der Szene → BeatPulse → Sparkle.
2. **Sektor-Maske** (§2) — inaktive Sektoren aus; **nach Drop kurz „full" übersteuert**.
3. **Anti-Flicker-Glättung** (`smoothing`) auf den Inhalt (Strobe/Blackout bleiben crisp).
4. **Strobe** (§4) — nur auf Drops; crisp; liefert Fixture-Gains für 2-Strip-Alternation.
5. **Blackout** (§3) — **ganz zuletzt, gewinnt immer**; harter Aus-Schnitt, gehalten,
   dann knackig an (kein Fade).

**Szenen/Sektoren:** `SceneManager` wählt alle `scene_seconds` einen Feature-Effekt
(Pool nach `mood`), ein gewichtetes Sektor-Muster (full ×9) und eine Chase-Richtung.

**Intensität:** blitzige Layer skalieren mit `eff_intensity = intensity × (0.35 + 0.65 × mood)`;
Farbe/Spektrum sind davon unabhängig (§1).

**Persistenz:** `ShowConfig` liegt als `data/config.yaml` (atomarer Write) → überlebt Neustart.

**Music Assistant (Slice 2, umgesetzt):** Album-Cover-Farbe als Basisfarbe (`album_art_color`)
und **Look-ahead/Build-ups vor bekannten Drops** (§9). Da MASS die **Track-Identität** +
Abspielposition liefert, entfällt Audio-Fingerprinting: erkannte Drops werden pro `track_id`
in SQLite (`data/lightshow.sqlite`, pro Track gedeckelt) gespeichert und beim Wiederabspielen
prädiktiv genutzt. Realtime-Drop-Erkennung ergänzt das für unbekannte Tracks.

## 6. Integrationen

- **Music Assistant (Slice 2, umgesetzt):** WebSocket-Client (`integrations/music_assistant.py`).
  Player-Steuerung (Play/Pause/Skip/Volume), Track-Metadaten, Cover, elapsed. Zustand wird
  gepollt **und** eventgetrieben, gecacht und über Event-Bus/WS ans Dashboard gespiegelt.
  **Autonome Reconnect-Logik** mit Backoff; Degraded-Mode (`online=False`) bei Ausfall — die
  Licht-Engine läuft unbeeinflusst weiter. Kommandonamen defensiv (MASS-2.x-API-Annahme).
- **Home Assistant (Slice 3):** WebSocket- + REST-Client. Geräte via Trigger oder manuelle
  UI-Buttons schalten (z. B. Nebelmaschine an Smart-Plug/Switch). Reconnect mit Backoff,
  Degraded-Mode wenn HA offline.

---

## 7. Frontend (Vue 3 + Vite + Tailwind)

Verzeichnis: `frontend/`. Zwei getrennte Vue-Apps, ein gemeinsames Client-Package
(WS-Client, Typen, UI-Primitives).

### Interface 1 — Haupt-Dashboard (`frontend/dashboard`)
- Live-Audio-Visualisierung (BPM, Peak, Frequenzbänder, Onset).
- Music-Assistant-Steuerung (Player-State, Track-Info, Cover, Playlists).
- Zuordnung Audio-Trigger → Lichteffekt.

### Interface 2 — Digitales Licht-Pult (`frontend/console`)
- Frei anordbares **Grid-Layout**: Buttons, Fader, Knobs, XY-Pads.
- Effekte triggern, manuelles Dimmen/Faden, HA-Aktionen (Nebel-Push).
- Eigene Effekte erstellen & speichern.
- **Persistenz:** Layout serverseitig gespeichert (`persistence/store.py`), übersteht Neustart.
- **Undo/Redo (kritisch):** Jede Layout-/Zuordnungsänderung geht durch einen Command-Stack
  (Undo/Redo-Historie), serverseitig versioniert.

### Kommunikation
- **WebSocket** für Live-State (Audio, Render-Preview, Status) und Kommandos.
- **REST** für CRUD (Effekte, Layouts, Geräte, Player-Aktionen).

---

## 8. Persistenz

- **Slice 1:** JSON-Dateien unter `data/` (einfach, transparent, versionierbar).
- **Später optional:** SQLite via SQLModel, falls relationaler Bedarf steigt.
- Gespeichert: Geräte/Devices, Effekte (inkl. benutzerdefiniert), Pult-Layouts,
  Undo/Redo-Historie, Trigger-Zuordnungen.
- **Fail-Safety:** atomare Writes (temp + rename), Schema-Versionierung.

---

## 9. Fehlertoleranz & Supervision

- `core/engine.py` ist ein **Task-Supervisor**: startet alle Tasks, überwacht sie, startet
  gecrashte Tasks mit Backoff neu, meldet Status auf `system.status`.
- Jede Integration/Quelle/Output kapselt eigene Reconnect-Schleife (exponential backoff, jitter).
- **Degraded-Mode:** Audio fehlt → EffectEngine läuft mit Idle-/Fallback-Effekt weiter.
  Output-Knoten offen → wird übersprungen, Rest läuft. MASS/HA offen → UI zeigt „offline",
  Kernpfad unberührt.

---

## 10. Deployment

- **`Dockerfile`:** Multi-Stage. Stage 1 baut die Vue-Frontends (Node), Stage 2 Python-Runtime
  (schlank), serviert die gebauten Assets statisch via FastAPI.
- **`docker-compose.yml`:** Service `lightshow` (+ optional `snapserver`/`snapclient` für
  lokale WSL-Tests). Netzwerk `host`-nah für UDP (DDP/ArtNet) bzw. Portfreigaben dokumentiert.
- **ENV:** `.env.example` als Vorlage; alle Hosts/Ports/Feature-Flags konfigurierbar.
- **GitHub:** Release wird vorbereitet, aber **kein Push ohne ausdrückliche Rücksprache**.

---

## 11. Delivery-Plan (Slices)

- **Slice 1 (dieser Durchstich):** Vertikaler Kern — AudioSource (Snapcast + Synthetic) →
  Analysis → EffectEngine → WLED-Output + minimales Dashboard, WS-Hub, Docker, ENV.
- **Slice 2 (umgesetzt):** Music-Assistant-Integration (Player, Cover-Farbe), SQLite-Persistenz
  + Look-ahead/Build-ups vor Drops, Dashboard-Player-Panel.
- **Slice 3:** Licht-Pult (Grid, Fader, XY, Undo/Redo), Home Assistant, ArtNet/DMX.
- **Slice 4:** Härtung, Tests, Performance-Tuning, Release-Vorbereitung.

---

## 12. Tech-Stack (Zusammenfassung)

| Bereich | Wahl |
|---------|------|
| Backend | Python 3.12, FastAPI, Uvicorn, AsyncIO |
| Audio-DSP | NumPy (Realtime-FFT/Beat), optional aubio/librosa |
| Output | WLED DDP/JSON (UDP), ArtNet (UDP, optional) |
| Frontend | Vue 3, Vite, Tailwind CSS |
| Persistenz | JSON (Slice 1) → optional SQLite/SQLModel |
| Deployment | Docker, docker-compose, WSL-getestet |
