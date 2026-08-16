"""FastAPI-App: Lifespan-Orchestrierung, WS-Endpoint, Static-Serving."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import build_router
from .api.ws import WsHub
from .config import get_settings
from .runtime import AppState

log = logging.getLogger(__name__)

# Static-Assets: gebautes Dashboard (Vite) unter web/, sonst übersprungen.
_WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    state = AppState(settings)
    hub = WsHub(state)
    app.state.lightshow = state
    app.state.ws_hub = hub

    await state.start()
    await hub.start()
    log.info("LightShow gestartet (Quelle=%s, Rate=%d Hz)", settings.audio_source, settings.frame_rate)
    try:
        yield
    finally:
        await hub.stop()
        await state.stop()
        log.info("LightShow gestoppt")


def create_app() -> FastAPI:
    app = FastAPI(title="LightShow", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # LAN-Tool; für Release ggf. einschränken
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(build_router())

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.app.state.ws_hub.connect(ws)

    if _WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
    else:
        @app.get("/")
        async def index():
            return {
                "app": "LightShow",
                "hint": "Frontend nicht gebaut. REST unter /api, WebSocket unter /ws.",
            }

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=bool(os.environ.get("LIGHTSHOW_RELOAD")),
    )


if __name__ == "__main__":
    main()
