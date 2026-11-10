"""Offline AI helper: find / install / start Ollama and make sure RANI's local model is downloaded.

Used by  install.bat -> `python -m rani --setup-ai`  and, silently, by the Ollama provider the first time
the cloud models are unavailable (limit finished or no internet).  Everything here is best-effort: a failure
never stops RANI, it only means the offline fallback is not ready yet.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

import requests

IS_WIN = sys.platform == "win32"
OLLAMA_SETUP_URL = "https://ollama.com/download/OllamaSetup.exe"
_pulling: set[str] = set()
_lock = threading.Lock()


def find_ollama() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    if IS_WIN:
        for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")):
            if base:
                p = Path(base) / "Programs" / "Ollama" / "ollama.exe"
                q = Path(base) / "Ollama" / "ollama.exe"
                for c in (p, q):
                    if c.exists():
                        return str(c)
    return None


def is_running(url: str, timeout: float = 1.5) -> bool:
    try:
        return requests.get(url.rstrip("/") + "/api/tags", timeout=timeout).status_code == 200
    except requests.RequestException:
        return False


def installed_models(url: str) -> list[str]:
    try:
        r = requests.get(url.rstrip("/") + "/api/tags", timeout=3)
        return [m.get("name", "") for m in r.json().get("models", [])]
    except (requests.RequestException, ValueError):
        return []


def model_in(names: list[str], model: str) -> bool:
    return model in names or (":" not in model and f"{model}:latest" in names)


def has_model(url: str, model: str) -> bool:
    return model_in(installed_models(url), model)


def start_serve() -> bool:
    exe = find_ollama()
    if not exe:
        return False
    flags = 0
    if IS_WIN:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    try:
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, creationflags=flags)
        return True
    except OSError:
        return False


def ensure_running(url: str, wait: float = 12.0) -> bool:
    """Make sure the Ollama server answers; start it when it is installed but not running."""
    if is_running(url):
        return True
    if not start_serve():
        return False
    end = time.time() + wait
    while time.time() < end:
        if is_running(url):
            return True
        time.sleep(0.5)
    return False


def remove_gui_autostart() -> int:
    """Ollama's desktop app adds itself to Windows startup and opens a window at every login. RANI only needs the
    background server (which RANI starts itself), so remove that startup entry. Returns how many were removed."""
    if not IS_WIN:
        return 0
    removed = 0
    try:
        startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        for lnk in startup.glob("Ollama*.lnk"):
            lnk.unlink()
            removed += 1
    except OSError:
        pass
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE) as k:
            for name in ("Ollama", "ollama", "Ollama App"):
                try:
                    winreg.DeleteValue(k, name)
                    removed += 1
                except OSError:
                    pass
    except (ImportError, OSError):
        pass
    return removed


def close_gui() -> bool:
    """Close the Ollama desktop window/tray app that the installer opens. The server is restarted headless."""
    try:
        import psutil
        hit = False
        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() == "ollama app.exe":     # the GUI only, never ollama.exe (server)
                try:
                    p.terminate()
                    hit = True
                except psutil.Error:
                    pass
        return hit
    except ImportError:
        return False


def quiet_gui(url: str) -> None:
    """After installing: no Ollama window, no Ollama at login, but the offline AI server still running."""
    remove_gui_autostart()
    if close_gui():
        time.sleep(1.5)
    ensure_running(url, wait=20)                 # if closing the app also stopped the server, start it headless


def pull_model(url: str, model: str, progress: Callable[[str], None] = lambda s: None) -> bool:
    """Download a model through the Ollama API (works on every OS, shows progress)."""
    try:
        with requests.post(url.rstrip("/") + "/api/pull", json={"model": model, "stream": True},
                           stream=True, timeout=(5, 600)) as r:
            if r.status_code != 200:
                progress(f"pull failed: HTTP {r.status_code}")
                return False
            last = ""
            for line in r.iter_lines():
                if not line:
                    continue
                d = json.loads(line)
                if d.get("error"):
                    progress("pull failed: " + str(d["error"]))
                    return False
                msg = d.get("status", "")
                if d.get("total") and d.get("completed"):
                    msg += f" {d['completed'] * 100 // d['total']}%"
                if msg != last:
                    progress(msg)
                    last = msg
        return has_model(url, model)
    except (requests.RequestException, ValueError) as e:
        progress(f"pull failed: {e}")
        return False


def pull_in_background(url: str, model: str) -> None:
    """Start downloading the offline model once, quietly (so the NEXT time it is offline it just works)."""
    with _lock:
        if model in _pulling:
            return
        _pulling.add(model)

    def run():
        try:
            pull_model(url, model)
        finally:
            with _lock:
                _pulling.discard(model)
    threading.Thread(target=run, daemon=True, name="rani-ollama-pull").start()


def install_ollama(progress: Callable[[str], None] = print) -> bool:
    """Windows: winget first, then the official installer silently. Returns True when ollama.exe exists."""
    if find_ollama():
        return True
    if not IS_WIN:
        progress("Automatic Ollama install is only for Windows. See https://ollama.com/download")
        return False
    if shutil.which("winget"):
        progress("Installing Ollama with winget ...")
        try:
            subprocess.run(["winget", "install", "-e", "--id", "Ollama.Ollama", "--silent",
                            "--accept-package-agreements", "--accept-source-agreements"], timeout=1200)
        except (OSError, subprocess.SubprocessError) as e:
            progress(f"winget failed: {e}")
        if find_ollama():
            return True
    progress("Downloading the official Ollama installer ...")
    try:
        target = Path(tempfile.gettempdir()) / "OllamaSetup.exe"
        with requests.get(OLLAMA_SETUP_URL, stream=True, timeout=(10, 120)) as r:
            r.raise_for_status()
            with open(target, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        subprocess.run([str(target), "/SILENT", "/NORESTART"], timeout=1200)
    except (OSError, requests.RequestException, subprocess.SubprocessError) as e:
        progress(f"installer failed: {e}")
    return bool(find_ollama())


def setup(settings, progress: Callable[[str], None] = print) -> bool:
    """Full offline-AI setup: install Ollama, start it, download the model. Safe to run again and again."""
    url, model = str(settings.get("ollama_url")), str(settings.get("ollama_model"))
    if not install_ollama(progress):
        progress("Offline AI NOT ready: Ollama could not be installed. RANI still works with the cloud AIs.")
        return False
    progress("Starting Ollama ...")
    if not ensure_running(url, wait=40):
        progress("Offline AI NOT ready: Ollama did not start. Open the Ollama app once, then run install.bat again.")
        return False
    quiet_gui(url)                               # close the Ollama window the installer opened; no popup at login
    if has_model(url, model):
        progress(f"Model {model} is already downloaded.")
        return True
    progress(f"Downloading offline model {model} (about 2 GB, one time only) ...")
    ok = pull_model(url, model, progress)
    progress("Offline AI is READY." if ok else "Model download failed - run install.bat again when the internet is on.")
    return ok
