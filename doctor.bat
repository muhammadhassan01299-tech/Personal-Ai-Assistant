@echo off
cd /d "%~dp0"
title RANI AI - Doctor
if not exist ".venv\Scripts\python.exe" (
  echo RANI is not installed yet. Run install.bat first.
  pause
  exit /b 1
)
powershell -NoProfile -Command "& '.venv\Scripts\python.exe' -m rani --doctor 2>&1 | Tee-Object -FilePath doctor_report.txt"
echo.
echo A copy of this report was saved to doctor_report.txt
pause
