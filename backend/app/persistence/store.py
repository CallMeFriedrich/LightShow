"""SQLite-Persistenz der Song-Struktur (erkannte Drops pro Track).

Da Music Assistant die **Track-Identität** (URI/ID) + Abspielposition liefert,
brauchen wir kein Audio-Fingerprinting: Drops werden pro ``track_id`` an ihrer
Position (Sekunden) gespeichert. Beim Wiederabspielen kann so **vor** dem Drop
hochgefahren werden (§9).

Wachstum ist unkritisch (nur wenige Drops je Song); zusätzlich pro Track auf
``CAP`` gedeckelt. Die Datei ``data/lightshow.sqlite`` überlebt Neustart.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

_TOL = 1.5   # s: Drops näher als das gelten als derselbe
_CAP = 24    # max. Drops je Track


class DropStore:
    def __init__(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS track_drops (
                   track_id TEXT NOT NULL,
                   position REAL NOT NULL,
                   hits     INTEGER NOT NULL DEFAULT 1,
                   updated  REAL NOT NULL,
                   PRIMARY KEY (track_id, position)
               )"""
        )
        # Gelerntes Energie-Profil je Track (1 Wert/Sekunde), über Wiedergaben gemittelt.
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS track_profile (
                   track_id TEXT PRIMARY KEY,
                   plays    INTEGER NOT NULL DEFAULT 1,
                   energy   TEXT NOT NULL,
                   updated  REAL NOT NULL
               )"""
        )
        self.db.commit()

    # ── Energie-Profil (Song-Lernen) ──
    def get_profile(self, track_id: str) -> list[float]:
        if not track_id:
            return []
        row = self.db.execute(
            "SELECT energy FROM track_profile WHERE track_id=?", (track_id,)
        ).fetchone()
        if not row:
            return []
        try:
            return [float(x) for x in json.loads(row[0])]
        except Exception:  # noqa: BLE001
            return []

    def save_profile(self, track_id: str, energies: list[float]) -> None:
        """Neues Profil elementweise mit dem bestehenden mitteln (gewichtet nach plays)."""
        if not track_id or not energies:
            return
        row = self.db.execute(
            "SELECT plays, energy FROM track_profile WHERE track_id=?", (track_id,)
        ).fetchone()
        now = time.time()
        if row:
            plays = int(row[0])
            try:
                old = [float(x) for x in json.loads(row[1])]
            except Exception:  # noqa: BLE001
                old = []
            n = max(len(old), len(energies))
            merged = []
            for i in range(n):
                o = old[i] if i < len(old) else None
                v = energies[i] if i < len(energies) else None
                if o is None:
                    merged.append(round(v, 4))
                elif v is None:
                    merged.append(round(o, 4))
                else:
                    merged.append(round((o * plays + v) / (plays + 1), 4))
            self.db.execute(
                "UPDATE track_profile SET plays=plays+1, energy=?, updated=? WHERE track_id=?",
                (json.dumps(merged), now, track_id),
            )
        else:
            self.db.execute(
                "INSERT INTO track_profile(track_id, plays, energy, updated) VALUES (?,1,?,?)",
                (track_id, json.dumps([round(e, 4) for e in energies]), now),
            )
        self.db.commit()

    def get_drops(self, track_id: str) -> list[float]:
        if not track_id:
            return []
        cur = self.db.execute(
            "SELECT position FROM track_drops WHERE track_id=? ORDER BY position",
            (track_id,),
        )
        return [float(r[0]) for r in cur.fetchall()]

    def add_drop(self, track_id: str, position: float) -> bool:
        """Speichert einen Drop (dedupliziert per Toleranz, gedeckelt). True = neu."""
        if not track_id or position < 0:
            return False
        rows = self.db.execute(
            "SELECT position, hits FROM track_drops WHERE track_id=? AND ABS(position-?)<?",
            (track_id, position, _TOL),
        ).fetchall()
        now = time.time()
        if rows:  # bekannter Drop → Position leicht mitteln, hits++
            old_pos = float(rows[0][0])
            new_pos = (old_pos * rows[0][1] + position) / (rows[0][1] + 1)
            self.db.execute(
                "UPDATE track_drops SET position=?, hits=hits+1, updated=? WHERE track_id=? AND position=?",
                (new_pos, now, track_id, old_pos),
            )
            self.db.commit()
            return False
        self.db.execute(
            "INSERT OR IGNORE INTO track_drops(track_id, position, updated) VALUES (?,?,?)",
            (track_id, position, now),
        )
        self._enforce_cap(track_id)
        self.db.commit()
        return True

    def _enforce_cap(self, track_id: str) -> None:
        count = self.db.execute(
            "SELECT COUNT(*) FROM track_drops WHERE track_id=?", (track_id,)
        ).fetchone()[0]
        if count > _CAP:
            # schwächste (wenigste hits, älteste) entfernen
            self.db.execute(
                """DELETE FROM track_drops WHERE rowid IN (
                       SELECT rowid FROM track_drops WHERE track_id=?
                       ORDER BY hits ASC, updated ASC LIMIT ?)""",
                (track_id, count - _CAP),
            )

    def close(self) -> None:
        self.db.close()
