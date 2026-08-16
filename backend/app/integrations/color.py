"""Album-Cover-Farbe → base_hue (§1 album_art_color).

Lädt ein Cover und bestimmt einen **repräsentativen Farbton**: statt eines
matschigen Durchschnitts wird der *vibrante* (gesättigte/helle) Anteil per
zirkulärem Hue-Mittel gewichtet. Vollständig fehlertolerant — kein/ungültiges
Cover → ``None`` (die ShowEngine behält dann ihren Default-Hue).
"""
from __future__ import annotations

import io
import logging
import math

import httpx
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)


def extract_hue(image_bytes: bytes) -> float | None:
    """Repräsentativen Hue [0,1] aus Bild-Bytes bestimmen (oder None)."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    img.thumbnail((48, 48))
    hsv = np.asarray(img.convert("HSV"), dtype=np.float32).reshape(-1, 3) / 255.0
    h, s, v = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    mask = (s > 0.3) & (v > 0.2)
    if mask.sum() < 4:  # zu wenig Farbe → Gesamtbild nehmen
        mask = np.ones_like(s, dtype=bool)
    weights = s[mask] * v[mask]
    angles = h[mask] * 2 * math.pi
    x = float(np.sum(np.cos(angles) * weights))
    y = float(np.sum(np.sin(angles) * weights))
    if x == 0.0 and y == 0.0:
        return None
    hue = math.atan2(y, x) / (2 * math.pi)
    return hue % 1.0


async def fetch_hue(url: str, client: httpx.AsyncClient | None = None) -> float | None:
    """Cover von ``url`` laden und Hue extrahieren (fehlertolerant)."""
    if not url:
        return None
    own = client is None
    client = client or httpx.AsyncClient(timeout=5)
    try:
        r = await client.get(url)
        r.raise_for_status()
        return extract_hue(r.content)
    except Exception as exc:  # noqa: BLE001
        log.debug("Cover-Farbe fehlgeschlagen (%s): %s", url, exc)
        return None
    finally:
        if own:
            await client.aclose()
