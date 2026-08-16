"""AudioSource-Abstraktion + Factory.

Eine Quelle produziert asynchron ``PCMFrame``s. Konkrete Implementierungen
kapseln ihre eigene Reconnect-Logik. Fällt die konfigurierte Quelle aus,
sorgt der Supervisor für Neustart; als Netz gegen totale Stille kann auf
die synthetische Quelle zurückgefallen werden.
"""
from __future__ import annotations

import abc
from typing import AsyncIterator

from ..config import Settings
from .models import PCMFrame


class AudioSource(abc.ABC):
    """Abstrakte Audio-Quelle."""

    name: str = "audio"

    @abc.abstractmethod
    async def frames(self) -> AsyncIterator[PCMFrame]:
        """Async-Generator, der fortlaufend PCM-Blöcke liefert."""
        raise NotImplementedError
        yield  # pragma: no cover — macht die Methode zum Generator

    async def close(self) -> None:  # pragma: no cover — optional
        return None


def build_source(settings: Settings, on_metadata=None) -> AudioSource:
    """Factory: erzeugt die konfigurierte Quelle.

    ``on_metadata`` (optional) erhält Player-Metadaten der Quelle (SendSpin liefert
    Titel/Cover/Playback-State über denselben Kanal).
    """
    kind = settings.audio_source
    if kind == "snapcast":
        from .snapcast import SnapcastSource

        return SnapcastSource(settings)
    if kind == "pcm_tcp":
        from .snapcast import PcmTcpSource

        return PcmTcpSource(settings)
    if kind == "sendspin":
        from .sendspin import SendSpinSource

        return SendSpinSource(settings, on_metadata=on_metadata)
    from .synthetic import SyntheticSource

    return SyntheticSource(settings)
