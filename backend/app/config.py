"""Zentrale Konfiguration aus Umgebungsvariablen (12-Factor).

Alle Werte haben sichere Defaults, sodass die App auch ohne `.env` startet
(Fallback: synthetische Audio-Quelle, virtueller Output).
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WledNode(BaseModel):
    """Konfiguration eines einzelnen WLED-Knotens."""

    id: str
    name: str = ""
    host: str
    port: int = 4048  # DDP
    pixels: int = 60


class Settings(BaseSettings):
    """Aus ENV geladene Anwendungs-Einstellungen (Präfix ``LIGHTSHOW_``)."""

    model_config = SettingsConfigDict(
        env_prefix="LIGHTSHOW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    data_dir: str = "./data"

    # Audio-Quelle
    audio_source: Literal["snapcast", "pcm_tcp", "synthetic", "sendspin"] = "synthetic"
    audio_sample_rate: int = 48000
    audio_channels: int = 2
    audio_block_size: int = 1024

    snapclient_bin: str = "snapclient"
    snapcast_host: str = "127.0.0.1"
    snapcast_port: int = 1704

    # SendSpin (natives Music-Assistant-Protokoll)
    # mode: listen = wir werben per mDNS, MASS verbindet sich zu uns (Standard-Discovery);
    #       connect = wir wählen den Server aktiv an (ws://host:port/sendspin).
    sendspin_mode: Literal["listen", "connect"] = "listen"
    sendspin_name: str = "LightShow"
    sendspin_host: str = ""       # nur für mode=connect
    sendspin_port: int = 0        # 0 = Default je Modus (listen:8928, connect:8927)

    pcm_tcp_host: str = "127.0.0.1"
    pcm_tcp_port: int = 4953

    # Analyse
    fft_size: int = 2048
    bands: int = 16

    # Output / Render
    frame_rate: int = 40
    # LED-Topologie (Hardware): Canvas-Länge + Anzahl paralleler Strips.
    # Setup: 2 Strips à 480 LEDs (gespiegelt, mit Strobe-Alternation).
    led_count: int = 480
    fixtures: int = 2
    # Einfachster Weg, WLED anzubinden: IP(s) kommagetrennt, je `wled_pixels` LEDs.
    wled_hosts: str = ""          # z. B. "10.10.1.50,10.10.1.51"
    wled_pixels: int = 480        # LEDs pro Host aus wled_hosts
    # Fortgeschritten (überschreibt nichts, wird zusätzlich genutzt): volle JSON-Liste.
    wled_nodes: list[WledNode] = Field(default_factory=list)

    def all_wled_nodes(self) -> list[WledNode]:
        """WLED-Knoten aus der einfachen Host-Liste + der JSON-Liste zusammenführen."""
        nodes = list(self.wled_nodes)
        for i, host in enumerate(h.strip() for h in self.wled_hosts.split(",")):
            if host:
                nodes.append(WledNode(id=f"wled{i + 1}", name=f"WLED {i + 1}",
                                      host=host, pixels=self.wled_pixels))
        return nodes

    # Integrationen (Slice 2/3)
    mass_url: str = ""          # z. B. http://192.168.1.10:8095
    mass_token: str = ""        # MASS-WS-Auth-Token; leer → MASS-WS-Client aus (SendSpin liefert Metadaten)
    mass_player_id: str = ""    # optional: bestimmten Player wählen (sonst aktiver)
    ha_url: str = ""
    ha_token: str = ""

    @field_validator("wled_nodes", mode="before")
    @classmethod
    def _parse_wled_nodes(cls, value: object) -> object:
        """Erlaubt JSON-String aus ENV (``LIGHTSHOW_WLED_NODES=[...]``)."""
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            return json.loads(value)
        return value


@lru_cache
def get_settings() -> Settings:
    """Cached Settings-Singleton."""
    return Settings()
