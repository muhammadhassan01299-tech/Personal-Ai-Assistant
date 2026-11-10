"""Installation / environment diagnostics. Run via doctor.bat or `python -m rani --doctor`."""
from __future__ import annotations

import importlib
import shutil
import socket
import sys

from . import startup
from .config import IS_WIN, get_secret

REQUIRED = [("PySide6.QtWebEngineWidgets", "PySide6"), ("psutil", "psutil"),
            ("requests", "requests"), ("edge_tts", "edge-tts"), ("pygame", "pygame"),
            ("speech_recognition", "SpeechRecognition"), ("PIL", "pillow"), ("pyaudio", "PyAudio")]
WINDOWS_ONLY = [("pycaw", "pycaw"), ("comtypes", "comtypes")]
OPTIONAL = [("keyboard", "keyboard (global hotkeys)"),
            ("keyring", "keyring (secure API keys)"), ("pyttsx3", "pyttsx3 (offline voice)"),
            ("pypdf", "pypdf (read PDFs)"), ("docx", "python-docx (Word files)")]


def _c(name, ok, detail=""):
    return {"name": name, "ok": bool(ok), "detail": str(detail)}


def run_checks(app=None, online: bool = True) -> list[dict]:
    out = [_c("Python >= 3.10", sys.version_info >= (3, 10), sys.version.split()[0]),
           _c("Windows", IS_WIN, sys.platform + ("" if IS_WIN else " - most checks need Windows"))]
    for mod, pkg in REQUIRED + (WINDOWS_ONLY if IS_WIN else []):
        try:
            importlib.import_module(mod)
            out.append(_c(f"package {pkg}", True, "installed"))
        except Exception as e:  # noqa: BLE001
            out.append(_c(f"package {pkg}", False, f"missing/broken: {type(e).__name__} -> pip install {pkg}"))
    for mod, label in OPTIONAL:
        try:
            importlib.import_module(mod)
            out.append(_c(f"optional {label}", True, "installed"))
        except Exception:
            out.append(_c(f"optional {label}", False, "not installed (optional feature unavailable)"))

    if app is not None:
        sp, ls = app.speaker, app.listener
        out.append(_c("audio output ready", sp.audio_ready(), getattr(sp, "last_error", "") or "mixer + endpoint ok"))
        out.append(_c("microphone", getattr(ls, "available", False), getattr(ls, "last_error", "") or "found"))
        st = app.brain.status()
        for name, ok in st.items():
            out.append(_c(f"AI provider {name}", ok, "ready" if ok else "not configured / not reachable"))
        try:
            from . import localai
            url, model = str(app.settings.get("ollama_url")), str(app.settings.get("ollama_model"))
            exe = localai.find_ollama()
            out.append(_c("offline AI (Ollama installed)", bool(exe), exe or "missing -> run: python -m rani --setup-ai"))
            if exe:
                out.append(_c(f"offline AI model {model}", localai.has_model(url, model),
                              "downloaded" if localai.has_model(url, model) else "not downloaded / Ollama not running -> python -m rani --setup-ai"))
        except Exception as e:  # noqa: BLE001
            out.append(_c("offline AI check", False, str(e)))
        out.append(_c("action registry", len(app.registry.names()) > 20, f"{len(app.registry.names())} actions"))
    if online:
        try:
            socket.create_connection(("speech.platform.bing.com", 443), timeout=4).close()
            out.append(_c("internet -> Edge neural voice service", True, "reachable"))
            try:
                import asyncio, tempfile, edge_tts
                from pathlib import Path
                p = Path(tempfile.gettempdir()) / "rani_doctor.mp3"

                async def go():
                    await edge_tts.Communicate("سلام", "ur-PK-UzmaNeural").save(str(p))
                asyncio.run(asyncio.wait_for(go(), 20))
                out.append(_c("voice ur-PK-UzmaNeural", p.exists() and p.stat().st_size > 500, f"{p.stat().st_size} bytes"))
            except Exception as e:  # noqa: BLE001
                out.append(_c("voice ur-PK-UzmaNeural", False, f"{type(e).__name__}: {str(e)[:100]}"))
        except OSError as e:
            out.append(_c("internet -> Edge neural voice service", False,
                          f"{e} (RANI falls back to the cached greeting / offline voice)"))
    if IS_WIN:
        from .winapi import _run
        out.append(_c("autostart registered", startup.is_autostart_enabled(),
                      startup.autostart_command() if startup.is_autostart_enabled() else "run install.bat or enable in Settings"))
        out.append(_c("NVIDIA GPU (nvidia-smi)", bool(shutil.which("nvidia-smi")), "found" if shutil.which("nvidia-smi") else "not on PATH (GPU stats unavailable)"))
        try:
            cp = _run(["powercfg", "/a"], 10)
            txt = cp.stdout
            sleep_ok = "Standby" in txt.split("not available")[0]
            hib = "Hibernate" in txt.split("not available")[0]
            out.append(_c("Windows Sleep available", sleep_ok, "S3/Modern Standby available" if sleep_ok else "sleep unavailable (see TROUBLESHOOTING)"))
            out.append(_c("Hibernate enabled (affects 'sleep')", True,
                          "ON - Windows may hibernate instead of sleeping; see TROUBLESHOOTING if sleep behaves like hibernate" if hib else "off"))
        except Exception as e:  # noqa: BLE001
            out.append(_c("powercfg", False, str(e)))
        try:
            from .winapi import WindowsBackend
            b = WindowsBackend()
            out.append(_c("volume control", True, f"volume {b.get_volume()}%"))
        except Exception as e:  # noqa: BLE001
            out.append(_c("volume control", False, f"{type(e).__name__}: {e}"))
    return out


def print_report(online=True) -> int:
    from .app import RaniApp
    from .voice import Listener, Speaker
    from .config import Settings
    s = Settings()
    app = RaniApp(settings=s, speaker=Speaker(s), listener=Listener(s))
    res = run_checks(app, online)
    bad = 0
    for r in res:
        print(f"[{'OK' if r['ok'] else 'FAIL'}] {r['name']}: {r['detail']}")
        if not r["ok"] and not r["name"].startswith(("optional", "Hibernate")):
            bad += 1
    print("\nAll required checks passed." if not bad else f"\n{bad} required check(s) failed - see TROUBLESHOOTING.md")
    return 1 if bad else 0
