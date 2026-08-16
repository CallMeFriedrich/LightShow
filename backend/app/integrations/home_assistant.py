"""Home-Assistant-Client (REST).

Ruft HA-Services auf (Schalter, Smart-Plugs, Nebelmaschine an Switch) über die
REST-API mit Long-Lived-Token. Fehlertolerant: HA offline → Fehler wird gefangen,
die Licht-Engine läuft unbeeinflusst weiter.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


class HAClient:
    def __init__(self, url: str, token: str, client: httpx.AsyncClient | None = None) -> None:
        self.base = url.rstrip("/")
        self.token = token
        self._own = client is None
        self._client = client or httpx.AsyncClient(timeout=5)

    @property
    def configured(self) -> bool:
        return bool(self.base and self.token)

    async def call_service(self, domain: str, service: str, data: dict | None = None) -> bool:
        if not self.configured:
            return False
        url = f"{self.base}/api/services/{domain}/{service}"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            r = await self._client.post(url, headers=headers, json=data or {})
            r.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("HA-Service %s.%s fehlgeschlagen: %s", domain, service, exc)
            return False

    async def toggle(self, entity_id: str) -> bool:
        domain = entity_id.split(".", 1)[0] if "." in entity_id else "homeassistant"
        return await self.call_service(domain, "toggle", {"entity_id": entity_id})

    async def turn_on(self, entity_id: str) -> bool:
        domain = entity_id.split(".", 1)[0] if "." in entity_id else "homeassistant"
        return await self.call_service(domain, "turn_on", {"entity_id": entity_id})

    async def turn_off(self, entity_id: str) -> bool:
        domain = entity_id.split(".", 1)[0] if "." in entity_id else "homeassistant"
        return await self.call_service(domain, "turn_off", {"entity_id": entity_id})

    async def close(self) -> None:
        if self._own:
            await self._client.aclose()
