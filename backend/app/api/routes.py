"""REST-Routen: Status, Show-Konfiguration, Info.

Die Show läuft autonom (SceneManager). Gesteuert wird über die persistente
``ShowConfig`` (§ Regelwerk). Manuelles Pult (Interface 2) folgt in Slice 3.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..effects.features import FEATURES
from ..effects.scene import POOL_CALM, POOL_ENERGETIC

_PLAYER_ACTIONS = {"play", "pause", "play_pause", "next", "previous"}


class ConfigPatch(BaseModel):
    """Teil-Update der ShowConfig (nur gesetzte Felder werden übernommen)."""

    changes: dict


class BaseHue(BaseModel):
    hue: float


class Volume(BaseModel):
    value: float


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    def state(request: Request):
        return request.app.state.lightshow

    @router.get("/status")
    async def status(request: Request):
        return state(request).status()

    @router.get("/config")
    async def get_config(request: Request):
        return state(request).show_cfg.to_dict()

    @router.post("/config")
    async def set_config(body: ConfigPatch, request: Request):
        st = state(request)
        applied = st.update_config(body.changes)
        return {"applied": applied, "config": st.show_cfg.to_dict()}

    @router.get("/effects")
    async def effects():
        return {
            "features": {name: cls.__doc__ or "" for name, cls in FEATURES.items()},
            "pools": {"calm": POOL_CALM, "energetic": POOL_ENERGETIC},
        }

    @router.post("/base_hue")
    async def base_hue(body: BaseHue, request: Request):
        state(request).show.set_base_hue(body.hue)
        return {"base_hue": round(state(request).show.base_hue, 3)}

    # ── Music Assistant ──
    @router.get("/player")
    async def player(request: Request):
        return state(request).player.to_dict()

    @router.post("/player/volume")
    async def player_volume(body: Volume, request: Request):
        ok = await state(request).player_command("volume", body.value)
        return {"ok": ok}

    @router.post("/player/{action}")
    async def player_action(action: str, request: Request):
        if action not in _PLAYER_ACTIONS:
            raise HTTPException(status_code=404, detail=f"Unbekannte Aktion: {action}")
        ok = await state(request).player_command(action)
        return {"ok": ok}

    return router
