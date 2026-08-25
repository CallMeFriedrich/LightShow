# SendSpin-Speaker (Windows/Linux)

Macht aus einem PC/Laptop einen **SendSpin-Lautsprecher** für Music Assistant —
kompatibel mit **MASS 2.9.x** (nutzt `aiosendspin 6.0.5`, ohne Verschlüsselung).
So lässt sich der Rechner mit **LightShow** in eine SendSpin-Sync-Gruppe legen →
**Ton kommt aus dem Rechner, Licht von LightShow, synchron.**

> Warum nicht die „Sendspin for Windows"-App? Die nutzt SDK 9.x (Verschlüsselung)
> und ist mit MASS 2.9.x (6.0.5) inkompatibel („Server closed the connection during
> client/init"). Dieser Client passt zur MASS-Version.

## Windows — Einrichtung

1. **Python installieren** (falls nicht vorhanden): [python.org/downloads](https://www.python.org/downloads/) →
   **Python 3.12 oder neuer**. Bei der Installation **„Add Python to PATH" anhaken**.

2. **Diesen Ordner holen** — entweder das ganze Repo klonen …
   ```
   git clone https://github.com/CallMeFriedrich/LightShow
   ```
   … oder als ZIP herunterladen und den Ordner `speaker` entpacken.

3. **Die alte „Sendspin for Windows"-App schließen** (sonst belegt sie den Port 8928).

4. **`run.bat` doppelklicken.** Beim ersten Start werden die Abhängigkeiten
   installiert, danach startet der Speaker. Fenster offen lassen.

   Alternativ in der Eingabeaufforderung:
   ```
   cd speaker
   pip install -r requirements.txt
   python sendspin_speaker.py "Laptop"
   ```
   (Der Name in Anführungszeichen ist frei wählbar — so heißt das Gerät in MASS.)

5. **In Music Assistant** erscheint jetzt ein neues **SendSpin-Gerät** mit deinem Namen.
   Leg es mit **LightShow** in eine **Sync-Gruppe** und spiele Musik auf die Gruppe →
   Ton aus dem Laptop, Licht synchron.

## Nützliches

- **Ausgabegerät wählen** (falls der Ton aufs falsche Gerät geht): erst die Geräte auflisten
  ```
  python sendspin_speaker.py --devices
  ```
  dann den Index als zweites Argument mitgeben:
  ```
  python sendspin_speaker.py "Laptop" 5
  ```

- **Automatisch mit Windows starten:** `Win+R` → `shell:startup` → eine **Verknüpfung
  zu `run.bat`** in diesen Autostart-Ordner legen.

## Linux

Gleiche Idee. `sounddevice` braucht PortAudio:
```
sudo apt install -y python3-pip libportaudio2
cd speaker && pip install -r requirements.txt
python3 sendspin_speaker.py "Wohnzimmer-PC"
```

## Hinweise

- Läuft im **listen/mDNS-Modus** — der Rechner muss **direkt im LAN** hängen (kein NAT),
  damit MASS ihn findet (wie bei LightShow).
- Bietet **PCM** an → MASS sendet rohes PCM, kein Codec/Decode nötig.
- Die Wiedergabe erfolgt mit kleinem Puffer bei Ankunft der Chunks — für Ton+Licht
  völlig ausreichend synchron. (Sample-genaue Mehrraum-Sync über Timestamps kann bei
  Bedarf nachgerüstet werden.)
