"""Datenmodelle der Integrationen (Music Assistant)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Track:
    id: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    image_url: str = ""
    duration: float = 0.0  # Sekunden

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "artist": self.artist,
            "album": self.album, "image_url": self.image_url,
            "duration": round(self.duration, 1),
        }


@dataclass(slots=True)
class PlayerState:
    """Aggregierter Zustand des aktiven Music-Assistant-Players."""

    online: bool = False           # MASS erreichbar?
    player_id: str = ""
    player_name: str = ""
    state: str = "idle"            # playing | paused | idle
    elapsed: float = 0.0           # Sekunden im aktuellen Track
    volume: float = 0.0            # 0..1
    track: Track = field(default_factory=Track)

    @property
    def is_playing(self) -> bool:
        return self.state == "playing"

    def to_dict(self) -> dict:
        return {
            "online": self.online,
            "player_id": self.player_id,
            "player_name": self.player_name,
            "state": self.state,
            "elapsed": round(self.elapsed, 1),
            "volume": round(self.volume, 3),
            "track": self.track.to_dict(),
        }
