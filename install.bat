@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title RANI AI - Install
echo ============================================================
echo   RANI AI installer  (owner: Wali Hasan)
echo   Just let it run - it installs everything by itself.
echo ============================================================
echo.

:detect
set "PY="
for %%V in (3.12 3.13 3.11 3.10) do (
  if not defined PY (
    py -%%V --version >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1 && set "PY=python"
)
if defined PY goto found
if defined PYTRIED goto nopython
set "PYTRIED=1"
where winget >nul 2>&1 || goto nopython
echo Python 3.10 - 3.13 was not found. Installing Python 3.12 automatically ...
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%LOCALAPPDATA%\Programs\Python\Launcher;%PATH%"
goto detect

:found
echo Using: %PY%
%PY% --version

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment ...
  %PY% -m venv .venv || goto fail
)
echo Upgrading pip ...
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto fail
echo Installing RANI packages (first time takes a few minutes; PySide6 is large) ...
".venv\Scripts\python.exe" -m pip install -r requirements-rani.txt || goto fail

if not exist ".env" copy /Y ".env.example" ".env" >nul

echo.
echo ------------------------------------------------------------
echo  OFFLINE AI (Ollama): used automatically when every cloud AI
echo  has reached its limit or the internet is off.
echo  One time download of about 2 GB. It starts in 15 seconds;
echo  press N to skip (RANI still works online).
echo ------------------------------------------------------------
choice /C YN /T 15 /D Y /M "Install offline AI now"
if errorlevel 2 goto skipai
".venv\Scripts\python.exe" -m rani --setup-ai
:skipai

echo.
echo Running checks ...
".venv\Scripts\python.exe" -m rani --offline-doctor
echo.
choice /C YN /T 15 /D Y /M "Start RANI automatically when Windows starts"
if errorlevel 2 goto skipauto
".venv\Scripts\python.exe" -m rani --autostart on
:skipauto
echo.
echo ============================================================
echo  Install finished.
echo  Optional: put your API keys (Gemini, Grok, Groq ...) in the
echo  .env file or in RANI Settings - AI Brain.
echo ============================================================
choice /C YN /T 10 /D Y /M "Start RANI now"
if errorlevel 2 goto end
start "" ".venv\Scripts\pythonw.exe" "%~dp0rani_launcher.pyw"
:end
pause
exit /b 0

:nopython
echo.
echo Could not install Python automatically.
echo Please install Python 3.12 from https://www.python.org/downloads/ (tick "Add python.exe to PATH") and run install.bat again.
pause
exit /b 1

:fail
echo.
echo Install FAILED. Read the message above, then see TROUBLESHOOTING.md
pause
exit /b 1
