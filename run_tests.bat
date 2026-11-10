@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
".venv\Scripts\python.exe" -m pytest rani\tests -q
echo.
echo Now the REAL Windows checks (safe: reads/sets volume, opens and closes Notepad, takes a screenshot):
".venv\Scripts\python.exe" rani\tests\live_windows_check.py
pause
