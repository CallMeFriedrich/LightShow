# Effekt-Regelwerk — WLED Lichtshow

Verbindliche Spezifikation der Effekt-Logik (vom Nutzer vorgegeben). Der Code in
`backend/app/effects/` setzt dieses Dokument um.

Legende:  `[config]` = in `data/config.yaml` (GUI-änderbar, `ShowConfig`).
          `[code]`   = fest im Code (Klassen-Defaults der Layer).

**Umsetzungsstand (LightShow):** Realtime-Teile aktiv. An Music Assistant gekoppelt
(Slice 2, noch offen): §9 Look-ahead/Build-ups und Album-Cover-Basisfarbe.

---

## 1. Grundverhalten

- **Intensität** `[config: intensity]` = **0.6**  (0 ruhig … 1 aggressiv)
  - Regel: passt sich automatisch an den Song an (Regler = Obergrenze; tatsächlich
    = intensity × (0.35 + 0.65 × mood)).
  - Regel: Intensität steuert NUR die blitzigen Layer (Beat-Flash, Sparkles, Strobes).
    Farbe/Buntheit ist davon unabhängig.
- **Helligkeit** `[config: brightness]` = **1.0**  (globaler Master-Dimmer)
- **Glättung / Anti-Flicker** `[config: smoothing]` = **0.5**  (0…0.95, höher = ruhiger)
- **Farb-Buntheit:** der Streifen soll NICHT überall dieselbe Farbe haben.
  - Basis-Layer (Ambient, BassWash) sind Farbverläufe `[code]`:
    - Ambient Hue-Spanne über den Streifen = **0.15**, Drift = 0.03
    - BassWash Hue-Spanne = **0.12**, Energie-Shift = 0.08
  - Spektrum (bunte Frequenz-Farben) ist prominent und NICHT von der Intensität gedämpft.
    - Spektrum Hue-Spanne `[code]` = **0.45**  (kleiner = weniger Regenbogen, eine Farbfamilie)
- **Album-Cover-Farbe** wird als Basisfarbe genommen `[config: album_art_color]` = **true**

---

## 2. Szenen & Sektoren

Eine „Szene" = welcher Feature-Effekt läuft + welche Abschnitte des Streifens leuchten.

- **Szenendauer** `[config: scene_seconds]` = **60** s  (wie oft gewechselt wird; höher = seltener)
- **Sektor-Grundpegel** `[config: section_floor]` = **0.0**  (umgesetzt: inaktive Sektoren ganz aus)
  - Regel: inaktive Sektoren gehen ganz aus, laufen nicht gedimmt weiter (Fokus auf aktiven),
    aber deutlich erkennbar. (kleiner = mehr Kontrast)
- Regel: Sektor-Muster sind **spiegelsymmetrisch** um die Mitte.
- Regel: **weiche/abgerundete** Sektor-Kanten (Feather-Breite `[code]` = **3.5 %** des Streifens).
- Regel: Sektoren nicht zu häufig → „full" (ganzer Streifen) ist hoch gewichtet.
  - Muster-Gewichtung `[code]`: full ×9, sonst je 1× von: center, edges, thirds_out, quarters, mid_third
- Regel: nach einem **Drop MUSS der ganze Streifen** an (Sektoren werden übersteuert).

---

## 3. Blackouts

- **An/Aus** `[config: blackouts]` = **true**
- **Wahrscheinlichkeit** `[config: blackout_chance]` = **0.6**  (pro passendem Beat)
- **Mindestpause** `[config: blackout_cooldown]` = **9** s  (Abstand zwischen Blackouts)
- **Dauer** `[config: blackout_hold]` = **0.45** s  (wie lange ganz schwarz)
- Regel: echter Blackout = **harter Schnitt auf schwarz**, wirklich spürbar gehalten, dann **knackig
  wieder an** (kein langsames Fade).
- Auslöser `[code]`: nur auf einem Beat wenn mood > 0.5 und energy > 0.45.

---

## 4. Strobes

- **An/Aus** `[config: strobes]` = **true**
- **Wahrscheinlichkeit** `[config: strobe_chance]` = **0.3**  (× effektive Intensität)
- **Abwechseln der 2 Strips** `[config: strobe_alt_chance]` = **0.5**  (Chance, dass sich bei
  einem Strobe die zwei Fixtures abwechseln statt gemeinsam zu blitzen; nur bei ≥2 Fixtures)
- **Intro-Verbot** `[config: strobe_min_song_s]` = **30** s  (keine Strobes in den ersten N s eines Songs)
- Regel: **nur auf echten Drops** (kein Zufalls-Spam auf Energie-Peaks).
- Typen `[code]` (pro Burst zufällig gewählt): **white**, **random unicolor**, **random color**.
- Burst-Dauer `[code]` = 0.5–1.0 s, Blitzrate = 16tel-Noten, Cooldown = 8 s.

---

## 5. Bass-Passagen (Breakdown / nur Bass)

Erkennung `[code]`: bass > 0.4 und Höhen < 0.22 und Mitten < 0.45.

- **Block-Anteil** `[config: bass_block_chance]` = **0.9**  (Anteil 36-LED-Block-Effekt vs. Bounce)
- **BlockToggle** `[code]`: Blockgröße = **36** LEDs, schaltet auf jeden Bass-Schlag um,
  alle Blöcke gleiche Farbe; die nicht fokussierten Blöcke sind AUS. In Bass-Passagen werden
  Ambient/Wash/Spectrum abgedunkelt, damit der Block-Effekt dominiert.
- **BassBounce** `[code]`: Komet, der bei jedem Bass-Schlag zum anderen Ende schwingt,
  getimed aufs gemessene Bass-Intervall.

---

## 6. Feature-Effekte & Auswahl nach Song

Pro Szene wird EIN „Feature-Effekt" gewählt, passend zum Song-Charakter:

- **Ruhige Songs** (mood < 0.45) `[code]`: Pool = **colordrift, comet, quad, colordrift**
- **Energiereiche Songs** (mood ≥ 0.45) `[code]`: Pool = **theater, dual, bounce, comet**
- Regel: Chase-**Richtung** variiert pro Szene zufällig.

Verfügbare Effekte:
- **colordrift** — langsamer, driftender Farbverlauf (ruhig, kein Blinken)
- **comet** — einzelner Komet, tempo-synchron
- **dual** — zwei Kometen von beiden Enden zur Mitte
- **bounce** — Komet ping-pong hin und her
- **theater** — gleichmäßig marschierende Punkte
- **quad** — 4 Teile, (1+3)/(2+4) im sanften Crossfade, gleiche Farbe
- **spectrum** — bunte Frequenzbänder über den Streifen (läuft immer mit, §1)

Layer, die je nach mood/energy dazukommen `[code]`:
- **Beat-Flash** (BeatPulse) — kurzer Blitz auf Beats (nur bei höherem mood, × Intensität)
- **Sparkles** — zufällige Funken auf Höhen-Onsets (nur bei hohem mood, × Intensität)

---

## 7. Einzelne Effekt-Parameter `[code]` (gain = Helligkeit, 0…~1)

| Effekt        | gain | weitere Parameter                                  |
|---------------|------|----------------------------------------------------|
| Ambient       | 0.28 | breath-speed 0.4, hue-spanne 0.15                  |
| BassWash      | 0.6  | hue-spanne 0.12                                    |
| Spectrum      | 0.9  | hue-spanne 0.45                                    |
| Comet         | 0.9  | tail 0.12, beats/sweep 4                           |
| DualComet     | 0.9  | tail 0.12, beats/sweep 4                           |
| BounceComet   | 0.9  | tail 0.10, beats/sweep 2                           |
| TheaterChase  | 0.85 | spacing 16, beats/step 0.5                         |
| QuadAlternate | 0.9  | beats/toggle 2                                     |
| ColorDrift    | 0.7  | hue-spanne 0.30, speed 0.03                        |
| BlockToggle   | 0.95 | block 36, schwelle 0.5                             |
| BassBounce    | 0.95 | tail 0.10                                          |
| Sparkle       | 0.9  | decay 0.18 (höher = längeres Nachleuchten)         |
| BeatPulse     | 0.6  | decay 0.16                                         |

---

## 8. Idle (nichts spielt)

- Regel: bei Stille → **hell-dunkelblauer** Hintergrund (driftender Helligkeitsverlauf auf
  Blau) + **beiger** langsamer Chase.
- `[code]`: Stille-Schwelle rms < 0.002; Blau-Hue 0.60; Chase-Durchlauf ~12 s.

---

## 9. Look-ahead / Drops  (Slice 2, benötigt Music Assistant + Song-Cache)

- Regel: **Build-up vor** einem bekannten Drop hochfahren `[code]`: ~6 s vorher, beschleunigend.
- Regel: **auf dem Drop** → ganzer Streifen full + (evtl.) Strobe.
- Ein Song kann **mehrere Drops** haben (alle werden gespeichert, nächster Drop wird gesucht).

---

## Persistenz-Kompromiss (Song-Cache, Slice 2)

- Cache als Datei (`data/lightshow.sqlite`) → überlebt Neustart.
- Gegen Festplatten-Wachstum: pro Song **~15.000 Hashes gedeckelt**
  (~90 Songs/6 h × ~15k × ~24 B ≈ ~30 MB). Song-Profile sind winzig.
- **Effekt-Konfiguration** persistiert bereits jetzt als `data/config.yaml`.
