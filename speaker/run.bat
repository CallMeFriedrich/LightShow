@echo off
cd /d "%~dp0"
echo === SendSpin-Speaker ===
echo Installiere Abhaengigkeiten (einmalig, kann etwas dauern)...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo FEHLER: pip/python nicht gefunden. Bitte Python 3.12+ von python.org installieren
  echo         und bei der Installation "Add Python to PATH" anhaken.
  pause
  exit /b 1
)
echo Starte...
python sendspin_speaker.py %*
pause
