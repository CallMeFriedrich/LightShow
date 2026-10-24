"""REST-Routen: Status, Show-Konfiguration, Info.

Die Show läuft autonom (SceneManager). Gesteuert wird über die persistente
``ShowConfig`` (§ Regelwerk). Manuelles Pult (Interface 2) folgt in Slice 3.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..effects.features import FEATURES
from ..effects.scene import SECTION_FEATURE

_PLAYER_ACTIONS = {"play", "pause", "play_pause", "next", "previous"}


class ConfigPatch(BaseModel):
    """Teil-Update der ShowConfig (nur gesetzte Felder werden übernommen)."""

    changes: dict


class BaseHue(BaseModel):
    hue: float


class Volume(BaseModel):
    value: float


class AddDevice(BaseModel):
    host: str
    name: str = ""
    pixels: int | None = None
    type: str = "wled"          # wled | artnet
    port: int | None = None
    universe: int = 0
    reverse: bool = False        # Streifen gespiegelt
    brightness: float = 1.0      # Per-Fixture-Dimmer
    cstart: float = 0.0          # Canvas-Bereichsanfang (0..1)
    cend: float = 1.0            # Canvas-Bereichsende (0..1)


class TestPattern(BaseModel):
    pattern: str = "rainbow"     # rainbow | solid | chase | off
    seconds: float = 6.0


class ConsoleLayout(BaseModel):
    layout: dict


class Action(BaseModel):
    action: dict


class Mode(BaseModel):
    mode: str                    # auto | manual


class ManualPatch(BaseModel):
    changes: dict


class SceneOp(BaseModel):
    id: str = ""
    name: str = ""
    from_live: bool = False
    changes: dict = {}
    on: bool | None = None
    delta: int = 0


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
            "section_feature": SECTION_FEATURE,
        }

    @router.post("/base_hue")
    async def base_hue(body: BaseHue, request: Request):
        state(request).show.set_base_hue(body.hue)
        return {"base_hue": round(state(request).show.base_hue, 3)}

    # ── Modus + manuelles Live-Pult ──
    @router.get("/mode")
    async def get_mode(request: Request):
        return {"mode": state(request).show_cfg.mode}

    @router.post("/mode")
    async def set_mode(body: Mode, request: Request):
        if body.mode not in ("auto", "manual"):
            raise HTTPException(status_code=400, detail="mode muss auto oder manual sein")
        return {"mode": state(request).set_mode(body.mode)}

    @router.get("/manual")
    async def manual_get(request: Request):
        return state(request).manual_info()

    @router.post("/manual")
    async def manual_set(body: ManualPatch, request: Request):
        st = state(request)
        applied = st.manual_update(body.changes)
        return {"applied": applied, **st.manual_info()}

    @router.post("/scenes/{op}")
    async def scene(op: str, body: SceneOp, request: Request):
        if op not in ("create", "update", "delete", "toggle", "move"):
            raise HTTPException(status_code=404, detail=f"Unbekannte Szenen-Aktion: {op}")
        sc = state(request).scene_op(op, body.id, name=body.name, from_live=body.from_live,
                                     changes=body.changes, on=body.on, delta=body.delta)
        return {"scene": sc, **state(request).manual_info()}

    @router.post("/patterns/{op}")
    async def pattern(op: str, body: SceneOp, request: Request):
        if op not in ("create", "duplicate", "update", "delete"):
            raise HTTPException(status_code=404, detail=f"Unbekannte Muster-Aktion: {op}")
        pat = state(request).pattern_op(op, body.id, name=body.name, changes=body.changes)
        return {"pattern": pat, **state(request).manual_info()}

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

    # ── Geräte-Verwaltung (WLED) ──
    @router.get("/devices")
    async def devices(request: Request):
        return {"devices": state(request).list_devices()}

    @router.post("/devices")
    async def add_device(body: AddDevice, request: Request):
        if not body.host.strip():
            raise HTTPException(status_code=400, detail="host fehlt")
        entry = state(request).add_device(
            body.host, body.name, body.pixels, body.type, body.port, body.universe,
            body.reverse, body.brightness, body.cstart, body.cend)
        return {"device": entry, "devices": state(request).list_devices()}

    @router.post("/devices/test")
    async def devices_test(body: TestPattern, request: Request):
        state(request).run_test_pattern(body.pattern, body.seconds)
        return {"ok": True}

    @router.delete("/devices/{device_id}")
    async def remove_device(device_id: str, request: Request):
        ok = state(request).remove_device(device_id)
        return {"ok": ok, "devices": state(request).list_devices()}

    # ── Licht-Pult (Interface 2) ──
    @router.get("/console")
    async def console_get(request: Request):
        return state(request).console.get()

    @router.post("/console")
    async def console_set(body: ConsoleLayout, request: Request):
        return state(request).console.set(body.layout)

    @router.post("/console/undo")
    async def console_undo(request: Request):
        return state(request).console.undo()

    @router.post("/console/redo")
    async def console_redo(request: Request):
        return state(request).console.redo()

    @router.post("/console/trigger")
    async def console_trigger(body: Action, request: Request):
        ok = await state(request).console_trigger(body.action)
        return {"ok": ok}

    return router
