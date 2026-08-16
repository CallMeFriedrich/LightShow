# LightShow

Modulares, containerisiertes Licht- & Effektsteuerungssystem. Audio-reaktive
Lichtsteuerung (Realtime-FFT/Beat), synchron zu einer Music-Assistant-Player-Gruppe,
mit WLED als primärem Output.

> Architektur & Delivery-Plan: siehe [`ARCHITECTURE.md`](ARCHITECTURE.md).
> **Aktueller Stand: Slice 1** — vertikaler Durchstich (Audio → Analyse → WLED → Dashboard).

## Features (Slice 1)

- **Audio-Capture** über austauschbare `AudioSource`: **SendSpin** (natives MASS-Protokoll,
  via `aiosendspin`) · Snapcast · PCM/TCP · Synthetic-Fallback.
- **Realtime-Analyse:** FFT, Frequenzbänder, Bass/Mitten/Höhen, `energy`, `mood`, Onset,
  Beat/BPM und Realtime-Drop-Erkennung.
- **Show-Engine** nach [Effekt-Regelwerk](docs/EFFEKT-REGELWERK.md): Layer-Compositor mit
  Ambient/BassWash/Spectrum, Feature-Effekten (Comet/Dual/Bounce/Theater/Quad/ColorDrift),
  Bass-Passagen (BlockToggle/BassBounce), Szenen & Sektoren, Blackouts, Strobes, Idle — 30–44 Hz.
- **WLED-Output** via DDP (UDP), verbindungslos & fehlertolerant.
- **Music Assistant** (Slice 2): Player-Steuerung, Track/Cover im Dashboard, Cover-Farbe als
  Basisfarbe, und **Look-ahead** — erkannte Drops pro Track (SQLite) für Build-ups beim
  Wiederabspielen. Autonome Reconnect-Logik, Degraded-Mode bei Ausfall.
- **Dashboard** (Vue 3 + Vite + Tailwind) mit Live-Visualisierung & Steuerung.
- **Async & entkoppelt:** Audio, Render und WebSocket laufen als überwachte Tasks
  (Auto-Restart mit Backoff); ausgefallene Geräte/Quellen blockieren nichts.

## Schnellstart (Docker, WSL)

```bash
cp .env.example .env          # erforderlich (danach anpassen)
docker compose up --build     # Compose v2 (Plugin)
# oder mit dem älteren Standalone-Tool:
docker-compose up --build     # Compose v1 (z. B. 1.29.x)
```

Dashboard: <http://localhost:8000> · REST: `/api` · WebSocket: `/ws`

Ohne Konfiguration läuft die App mit **synthetischer Audio-Quelle** und
**virtuellem Output** (LED-Preview im Dashboard) — sofort testbar ohne Hardware.

### WLED anbinden

In `.env`:

```bash
LIGHTSHOW_WLED_NODES=[{"id":"strip1","name":"Wohnzimmer","host":"192.168.1.50","pixels":60}]
```

### Snapcast als Audio-Quelle

```bash
LIGHTSHOW_AUDIO_SOURCE=snapcast
LIGHTSHOW_SNAPCAST_HOST=192.168.1.10
```

## Entwicklung

**Backend** (benötigt Python 3.12 + Abhängigkeiten aus `backend/requirements.txt`):

```bash
cd backend && python -m app.main
```

**Frontend** (Dev-Server mit Hot-Reload, proxyt `/api` + `/ws` ans Backend):

```bash
cd frontend/dashboard && npm install && npm run dev
```

## Projektstruktur

```
backend/app/
  core/        Event-Bus, Task-Supervisor, Frame-Clock
  audio/       Quellen (Snapcast/PCM/Synthetic) + Analyse
  effects/     Effekt-ABC, Registry, Builtins, Render-Engine
  output/      OutputRouter, WLED (DDP), virtueller Output
  api/         WebSocket-Hub, REST-Routen
  runtime.py   Verdrahtung + entkoppelte Tasks
  main.py      FastAPI-App, Lifespan, Static-Serving
frontend/dashboard/   Vue-3-Dashboard (Interface 1)
```

## Roadmap

- **Slice 1 ✓:** Audio → Show-Engine (Regelwerk) → WLED + Dashboard.
- **Slice 2 ✓:** Music Assistant (Player, Cover-Farbe), SQLite-Persistenz + Look-ahead/Drops.
- **Slice 3 ✓:** Digitales Licht-Pult (Grid/Buttons/Fader/XY, Undo/Redo, persistiert),
  Home Assistant (Switches/Nebel via Token), ArtNet/DMX-Output, WLED-Verwaltung im UI.
- **Slice 4:** Härtung, Tests, Release.
