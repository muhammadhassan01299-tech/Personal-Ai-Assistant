"""Windows startup registration, once-per-login greeting marker, single-instance control."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

from .config import IS_WIN, PROJECT_ROOT, app_dir

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "RANI AI"
CONTROL_PORT = 47652


def _pythonw() -> str:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def autostart_command() -> str:
    launcher = PROJECT_ROOT / "rani_launcher.pyw"
    return f'"{_pythonw()}" "{launcher}" --startup'


def is_autostart_enabled() -> bool:
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, RUN_NAME)
            return bool(val)
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    """Per-user (HKCU) - needs no administrator rights. Returns True when the registry matches `enabled`."""
    if not IS_WIN:
        return False
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_READ) as k:
        if enabled:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass
    return is_autostart_enabled() == enabled


# ---------------------------------------------------------------- greet once per login
def login_session_key() -> str:
    """Changes on every Windows reboot AND every new user login (explorer.exe restarts at login)."""
    import psutil
    boot = int(psutil.boot_time())
    me = None
    try:
        me = psutil.Process().username()
    except Exception:
        pass
    explorer = 0
    try:
        times = []
        for p in psutil.process_iter(["name", "create_time"]):      # username only for explorer.exe (it is slow)
            if (p.info.get("name") or "").lower() != "explorer.exe":
                continue
            try:
                if me is None or p.username() == me:
                    times.append(int(p.info["create_time"]))
            except Exception:
                pass
        explorer = min(times) if times else 0
    except Exception:
        pass
    return f"{boot}-{explorer}"


def _marker() -> Path:
    return app_dir() / "last_greeting.json"


def already_greeted(key: str | None = None) -> bool:
    try:
        return json.loads(_marker().read_text()).get("key") == (key or login_session_key())
    except (OSError, ValueError):
        return False


def mark_greeted(key: str | None = None) -> None:
    _marker().write_text(json.dumps({"key": key or login_session_key(), "at": time.time()}))


# ---------------------------------------------------------------- single instance / remote control
def send_control(cmd: str, timeout=1.5) -> str:
    try:
        with socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=timeout) as s:
            s.sendall((cmd + "\n").encode())
            s.settimeout(timeout)
            return s.recv(64).decode().strip()
    except OSError:
        return ""


class ControlServer:
    """Localhost-only. Understands exactly: ping, show, quit. Doubles as the single-instance lock."""

    def __init__(self, on_cmd):
        self.on_cmd = on_cmd
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1) if IS_WIN else None
        self.sock.bind(("127.0.0.1", CONTROL_PORT))      # raises OSError if RANI already runs
        self.sock.listen(2)
        threading.Thread(target=self._serve, daemon=True, name="rani-control").start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(1)
                    cmd = conn.recv(32).decode().strip().lower()
                    if cmd in ("ping", "show", "quit"):
                        conn.sendall(b"ok")
                        self.on_cmd(cmd)
                    else:
                        conn.sendall(b"?")
                except OSError:
                    pass
