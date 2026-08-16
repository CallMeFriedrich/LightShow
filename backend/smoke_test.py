"""Smoke-Test der Show-Engine + Pipeline (ohne Netzwerk/Hardware).

Prüft: WLED-DDP-Header, Sektor-Masken, ShowConfig-Persistenz, Analyse-Features,
ShowEngine in allen Pfaden (normal/bass/silence) sowie Blackout-gewinnt-zuletzt
und Strobe-auf-Drop, plus einen kurzen Runtime-Lauf mit synthetischer Quelle.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile

import numpy as np

from app.audio.models import AnalysisFrame
from app.config import Settings
from app.effects.compositor import ShowEngine
from app.effects.config import ShowConfig
from app.effects import sectors
from app.output.wled import WledOutput
from app.runtime import AppState


def test_wled_packet() -> None:
    dev = WledOutput("t", "t", "127.0.0.1", pixels=3)
    pkt = dev._make_packet(np.zeros((3, 3), dtype=np.uint8), 0, push=True)
    assert pkt[0] == 0x41 and len(pkt) == 19
    print("✓ WLED-DDP-Header ok")


def test_sectors() -> None:
    m = sectors.make_mask(144, "edges", floor=0.0)
    assert m.shape == (144,) and m[0] > 0.5 and m[72] < 0.1  # Mitte aus bei 'edges'
    # Spiegelsymmetrie
    assert abs(float(m[10]) - float(m[-11])) < 0.05
    full = sectors.make_mask(144, "full", 0.0)
    assert np.allclose(full, 1.0)
    print("✓ Sektor-Masken (mirror/feather/floor) ok")


def test_config_persist() -> None:
    with tempfile.TemporaryDirectory() as d:
        c = ShowConfig.load(d)
        assert c.intensity == 0.6 and c.blackout_hold == 0.45
        c.update({"intensity": 0.9, "unknown": 1})
        c2 = ShowConfig.load(d)  # neu laden → persistiert?
        assert c2.intensity == 0.9
    print("✓ ShowConfig lädt/persistiert (überlebt Neustart)")


def _af(**kw) -> AnalysisFrame:
    base = dict(bands=[0.5] * 16, rms=0.2, peak=0.6, bass=0.3, mids=0.4,
                highs=0.3, energy=0.4, mood=0.6, bpm=124, beat_now=False,
                onset=0.2, highs_onset=0.2, drop_now=False, song_time=90, silence=False)
    base.update(kw)
    return AnalysisFrame(**base)


def test_show_engine() -> None:
    cfg = ShowConfig()
    eng = ShowEngine(cfg, pixels=144, fixtures=2, seed=1)
    # Normal
    buf, gains = eng.render(_af(), 1.0, 0.025)
    assert buf.data.shape == (144, 3) and buf.data.dtype == np.uint8
    assert len(gains) == 2
    # Bass-Passage
    eng.render(_af(bass=0.8, highs=0.1, mids=0.3), 1.05, 0.025)
    assert eng.status["bass_passage"] is True
    # Silence → Idle
    eng.render(_af(silence=True, rms=0.0), 1.1, 0.025)
    # Blackout gewinnt zuletzt: erzwinge Trigger-Bedingungen
    cfg.blackout_chance = 1.0
    buf, _ = eng.render(_af(beat_now=True, mood=0.9, energy=0.9), 20.0, 0.025)
    assert int(buf.data.max()) == 0, "Blackout muss schwarz sein (gewinnt zuletzt)"
    print("✓ ShowEngine: normal/bass/idle + Blackout-gewinnt-zuletzt")


def test_strobe_on_drop() -> None:
    cfg = ShowConfig(strobe_chance=1.0, strobe_min_song_s=0, strobe_alt_chance=1.0)
    eng = ShowEngine(cfg, pixels=144, fixtures=2, seed=2)
    saw_alt = False
    t = 0.0
    for _ in range(40):
        t += 0.025
        drop = _af(drop_now=True, energy=0.9, song_time=60, mood=0.7)
        _, gains = eng.render(drop, t, 0.025)
        if gains != [1.0, 1.0]:
            saw_alt = True
    assert saw_alt, "Strobe-Alternation der 2 Fixtures nicht beobachtet"
    print("✓ Strobe auf Drop + 2-Strip-Alternation")


async def test_runtime() -> None:
    with tempfile.TemporaryDirectory() as d:
        st = AppState(Settings(audio_source="synthetic", frame_rate=40, data_dir=d))
        await st.start()
        await asyncio.sleep(1.5)
        a = st.latest_analysis
        assert a.peak > 0 and 0 <= a.mood <= 1 and len(a.bands) == 16
        assert len(st.preview.as_hex()) == st.preview.pixels
        assert "scene" in st.show.status
        await st.stop()
        print(f"✓ Runtime: peak={a.peak:.3f} bpm={a.bpm:.0f} mood={a.mood:.2f} "
              f"scene={st.show.status['scene']}")


def test_mass_parse() -> None:
    from app.integrations.music_assistant import _ws_url, parse_state
    assert _ws_url("http://10.0.0.5:8095") == "ws://10.0.0.5:8095/ws"
    assert _ws_url("https://mass.local") == "wss://mass.local/ws"
    player = {"player_id": "p1", "display_name": "Wohnzimmer", "state": "PLAYING", "volume_level": 50}
    queue = {"elapsed_time": 42.5, "current_item": {"duration": 200, "media_item": {
        "uri": "spotify://track/x", "name": "Song", "artists": [{"name": "Artist"}],
        "album": {"name": "Album"}, "metadata": {"images": [{"path": "http://cover/x.jpg"}]}}}}
    st = parse_state(player, queue)
    assert st.online and st.is_playing and st.player_name == "Wohnzimmer"
    assert st.elapsed == 42.5 and st.volume == 0.5
    assert st.track.title == "Song" and st.track.artist == "Artist"
    assert st.track.image_url == "http://cover/x.jpg" and st.track.duration == 200
    print("✓ MASS-Parser (player/queue → PlayerState) + ws-url")


def test_cover_color() -> None:
    import io
    from PIL import Image
    from app.integrations.color import extract_hue
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (0, 200, 0)).save(buf, format="PNG")  # grün
    hue = extract_hue(buf.getvalue())
    assert hue is not None and abs(hue - 1 / 3) < 0.05, hue  # grün ≈ 0.333
    assert extract_hue(b"not an image") is None
    print(f"✓ Cover-Farbe: grün → hue={hue:.3f}")


def test_dropstore() -> None:
    import tempfile, os
    from app.persistence.store import DropStore
    with tempfile.TemporaryDirectory() as d:
        s = DropStore(os.path.join(d, "t.sqlite"))
        assert s.add_drop("trackA", 30.0) is True
        assert s.add_drop("trackA", 30.5) is False  # dedupe (< Toleranz)
        assert s.add_drop("trackA", 60.0) is True
        assert len(s.get_drops("trackA")) == 2
        s.close()
        s2 = DropStore(os.path.join(d, "t.sqlite"))  # überlebt Reopen
        assert len(s2.get_drops("trackA")) == 2
        s2.close()
    print("✓ DropStore (dedupe + Persistenz)")


def test_lookahead() -> None:
    from app.integrations.lookahead import LookAhead
    la = LookAhead()
    la.set_track("trackA", [60.0])
    assert la.compute(50.0) == (0.0, False)         # zu früh
    b, pred = la.compute(56.0)                        # 4 s vorher → Build-up
    assert 0.0 < b < 1.0 and pred is False
    b, pred = la.compute(60.0)                        # auf dem Drop
    assert pred is True and b == 1.0
    assert la.record_drop(120.0) is True             # neuer Drop
    assert la.record_drop(120.4) is False            # dedupe
    print("✓ Look-ahead (Build-up + prädiktiver Drop + record)")


def main() -> int:
    test_wled_packet()
    test_sectors()
    test_config_persist()
    test_show_engine()
    test_strobe_on_drop()
    test_mass_parse()
    test_cover_color()
    test_dropstore()
    test_lookahead()
    asyncio.run(test_runtime())
    print("\nAlle Smoke-Tests bestanden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
