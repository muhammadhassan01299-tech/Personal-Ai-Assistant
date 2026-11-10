@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m rani --stop
)
timeout /t 2 /nobreak >nul
rem If RANI did not answer, end any leftover RANI process
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*rani_launcher*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
echo RANI stopped.
exit /b 0
