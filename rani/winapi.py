"""Thin Windows backend.  Every method does ONE real OS operation and returns real results.

Only fixed, validated argument lists are passed to external programs (never a shell string
built from user/AI text).  On non-Windows systems methods raise NotSupported - the unit tests
swap in a FakeBackend (see tests/), and `tests/live_windows_check.py` exercises this real
backend on the actual laptop.
"""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

IS_WIN = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0


class NotSupported(RuntimeError):
    pass


def _need_win():
    if not IS_WIN:
        raise NotSupported("This operation needs Windows")


def _run(args: list[str], timeout=20) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          creationflags=CREATE_NO_WINDOW, errors="replace")


def _ps(script: str, timeout=20) -> str:
    cp = _run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
               "-Command", script], timeout)
    if cp.returncode != 0:
        raise RuntimeError((cp.stderr or cp.stdout).strip()[:200] or f"powershell exit {cp.returncode}")
    return cp.stdout.strip()


class Backend:
    """Interface + shared pure-python helpers."""

    # ---------- launching / processes
    def launch(self, candidate: str) -> None: raise NotSupported
    def pids_for(self, proc_names: list[str]) -> set[int]: raise NotSupported
    def window_count_for(self, proc_names: list[str]) -> int: raise NotSupported
    def close_gracefully(self, proc_names: list[str]) -> None: raise NotSupported
    def start_menu_search(self, query: str) -> list[tuple[str, str]]: raise NotSupported
    def open_path(self, path: str) -> None: raise NotSupported
    def open_url(self, url: str) -> bool: raise NotSupported
    def known_folder(self, name: str) -> Path: raise NotSupported
    # ---------- windows
    def find_windows(self, proc_names: list[str]) -> list[int]: raise NotSupported
    def foreground_window(self) -> int: raise NotSupported
    def window_op(self, hwnd: int, op: str) -> None: raise NotSupported
    def window_pid(self, hwnd: int) -> int: return 0          # owner process of a window (0 = unknown)
    # ---------- audio / display
    def get_volume(self) -> int: raise NotSupported
    def set_volume(self, level: int) -> None: raise NotSupported
    def get_mute(self) -> bool: raise NotSupported
    def set_mute(self, muted: bool) -> None: raise NotSupported
    def get_brightness(self) -> int | None: raise NotSupported
    def set_brightness(self, level: int) -> None: raise NotSupported
    # ---------- system
    def battery(self): raise NotSupported
    def cpu_ram(self) -> tuple[float, float]: raise NotSupported
    def gpu(self) -> str | None: raise NotSupported
    def wifi_status(self) -> str: raise NotSupported
    def screenshot(self, path: str) -> None: raise NotSupported
    # ---------- power
    def lock(self) -> bool: raise NotSupported
    def sleep(self) -> bool: raise NotSupported
    def schedule_power(self, seconds: int, restart: bool) -> None: raise NotSupported
    def abort_power(self) -> bool: raise NotSupported
    def lid_get(self) -> tuple[int, int]: raise NotSupported
    def lid_set(self, ac: int, dc: int) -> None: raise NotSupported
    # ---------- input
    def send_text(self, text: str, stop=None) -> None: raise NotSupported
    def send_hotkey(self, combo: str) -> None: raise NotSupported
    def click(self, x: int, y: int) -> None: raise NotSupported


class WindowsBackend(Backend):
    # ------------------------------------------------------------ launching
    def launch(self, candidate: str) -> None:
        _need_win()
        os.startfile(candidate)  # ShellExecute: App Paths, URIs (ms-settings:), exes on PATH, .lnk

    def pids_for(self, proc_names):
        import psutil
        want = {n.lower() for n in proc_names}
        return {p.pid for p in psutil.process_iter(["name"])
                if (p.info.get("name") or "").lower() in want}

    def window_count_for(self, proc_names):
        return len(self.find_windows(proc_names))

    def close_gracefully(self, proc_names):
        _need_win()
        for n in proc_names:
            if re.fullmatch(r"[A-Za-z0-9_.\-]+\.exe", n):
                _run(["taskkill", "/IM", n])   # no /F: asks apps to close politely (WM_CLOSE)

    def start_menu_search(self, query):
        roots = [Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
                 Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"]
        toks = [t for t in re.split(r"\W+", query.lower()) if t]
        found = []
        for root in roots:
            if not root.exists():
                continue
            for lnk in root.rglob("*.lnk"):
                stem = lnk.stem.lower()
                if toks and all(t in stem for t in toks):
                    found.append((lnk.stem, str(lnk)))
        found.sort(key=lambda x: len(x[0]))
        return found

    def open_path(self, path):
        _need_win()
        os.startfile(path)

    def open_url(self, url):
        return bool(webbrowser.open(url, new=2))

    def known_folder(self, name):
        home = Path.home()
        if name in ("", "home"):
            return home
        if not IS_WIN:
            return home / name
        from ctypes import wintypes
        ids = {  # FOLDERID_* GUIDs (works even when OneDrive redirects Desktop/Documents)
            "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
            "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
            "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
            "Pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
            "Videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
            "Music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
        }
        guid_s = ids.get(name)
        if not guid_s:
            return home / name

        class GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD),
                        ("d", ctypes.c_ubyte * 8)]
        g = GUID()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(guid_s), ctypes.byref(g))
        out = ctypes.c_wchar_p()
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out))
        if hr == 0 and out.value:
            p = Path(out.value)
            ctypes.windll.ole32.CoTaskMemFree(out)
            return p
        return home / name

    # ------------------------------------------------------------ windows
    def _enum(self):
        _need_win()
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        res = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n > 0:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    res.append((int(hwnd), pid.value))
            return True
        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return res

    def find_windows(self, proc_names):
        import psutil
        want = {n.lower() for n in proc_names}
        out = []
        for hwnd, pid in self._enum():
            try:
                if psutil.Process(pid).name().lower() in want:
                    out.append(hwnd)
            except Exception:
                pass
        return out

    def foreground_window(self):
        _need_win()
        return int(ctypes.windll.user32.GetForegroundWindow())

    def window_op(self, hwnd, op):
        _need_win()
        u = ctypes.windll.user32
        if op == "minimize":
            u.ShowWindow(hwnd, 6)
        elif op == "maximize":
            u.ShowWindow(hwnd, 3)
        elif op == "focus":
            if u.IsIconic(hwnd):
                u.ShowWindow(hwnd, 9)
            u.keybd_event(0x12, 0, 0, 0)          # tap ALT so Windows allows foreground change
            u.keybd_event(0x12, 0, 2, 0)
            u.SetForegroundWindow(hwnd)
        else:
            raise ValueError(op)

    def window_pid(self, hwnd) -> int:
        _need_win()
        from ctypes import wintypes
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def is_minimized(self, hwnd) -> bool:
        return bool(ctypes.windll.user32.IsIconic(hwnd))

    def is_maximized(self, hwnd) -> bool:
        return bool(ctypes.windll.user32.IsZoomed(hwnd))

    # ------------------------------------------------------------ audio
    def _endpoint(self):
        _need_win()
        import comtypes
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from comtypes import CLSCTX_ALL
        dev = AudioUtilities.GetSpeakers()
        if hasattr(dev, "EndpointVolume"):           # newer pycaw
            return dev.EndpointVolume
        iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return ctypes.cast(iface, ctypes.POINTER(IAudioEndpointVolume))

    def get_volume(self):
        return int(round(self._endpoint().GetMasterVolumeLevelScalar() * 100))

    def set_volume(self, level):
        self._endpoint().SetMasterVolumeLevelScalar(max(0, min(100, int(level))) / 100.0, None)

    def get_mute(self):
        return bool(self._endpoint().GetMute())

    def set_mute(self, muted):
        self._endpoint().SetMute(1 if muted else 0, None)

    def audio_ready(self) -> bool:
        try:
            self._endpoint().GetMasterVolumeLevelScalar()
            return True
        except Exception:
            return False

    def get_brightness(self):
        out = _ps("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness "
                  "-ErrorAction Stop | Select-Object -First 1).CurrentBrightness")
        return int(out) if out.strip().isdigit() else None

    def set_brightness(self, level):
        level = int(level)
        if not 0 <= level <= 100:
            raise ValueError("level")
        _ps("Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop | "
            "ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName WmiSetBrightness "
            f"-Arguments @{{Timeout=[uint32]1; Brightness=[byte]{level}}} | Out-Null }}")

    # ------------------------------------------------------------ system
    def battery(self):
        import psutil
        b = psutil.sensors_battery()
        return None if b is None else (int(round(b.percent)), bool(b.power_plugged))

    def cpu_ram(self):
        import psutil
        return psutil.cpu_percent(interval=0.4), psutil.virtual_memory().percent

    def gpu(self):
        exe = shutil.which("nvidia-smi")
        if not exe:
            return None
        cp = _run([exe, "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total",
                   "--format=csv,noheader,nounits"], 8)
        if cp.returncode != 0 or not cp.stdout.strip():
            return None
        u, t, mu, mt = [x.strip() for x in cp.stdout.splitlines()[0].split(",")]
        return f"GPU {u}% ({t}C, {mu}/{mt} MB)"

    def wifi_status(self):
        cp = _run(["netsh", "wlan", "show", "interfaces"], 8)
        state = re.search(r"^\s*State\s*:\s*(.+)$", cp.stdout, re.M)
        ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", cp.stdout, re.M)
        if not state:
            return "no Wi-Fi adapter found"
        s = state.group(1).strip()
        return f"{s} ({ssid.group(1).strip()})" if ssid and s.lower() == "connected" else s

    def screenshot(self, path):
        from PIL import ImageGrab
        ImageGrab.grab(all_screens=True).save(path)

    # ------------------------------------------------------------ power
    def lock(self):
        _need_win()
        return bool(ctypes.windll.user32.LockWorkStation())

    def sleep(self):
        _need_win()
        # SetSuspendState(Hibernate=False, ForceCritical=False, DisableWakeEvent=False) blocks until the PC wakes
        # up again, so run it a moment later: RANI can say goodbye first instead of after you come back.
        def _go():
            time.sleep(3.0)
            ctypes.windll.powrprof.SetSuspendState(0, 0, 0)
        threading.Thread(target=_go, daemon=True, name="rani-sleep").start()
        return True

    def schedule_power(self, seconds, restart):
        _need_win()
        seconds = int(seconds)
        if not 5 <= seconds <= 600:
            raise ValueError("seconds")
        cp = _run(["shutdown", "/r" if restart else "/s", "/t", str(seconds), "/c",
                   "RANI AI: " + ("restart" if restart else "shutdown") + " requested by Wali. "
                   "Say 'cancel' or run: shutdown /a"])
        if cp.returncode != 0:
            raise RuntimeError((cp.stderr or cp.stdout).strip() or f"exit {cp.returncode}")

    def abort_power(self):
        _need_win()
        return _run(["shutdown", "/a"]).returncode == 0

    _LID = ["SCHEME_CURRENT", "SUB_BUTTONS", "LIDACTION"]

    def lid_get(self):
        _need_win()
        cp = _run(["powercfg", "/query"] + self._LID)
        vals = re.findall(r"0x[0-9a-fA-F]{8}", cp.stdout)
        if len(vals) < 2:
            raise RuntimeError("could not read lid action")
        return int(vals[-2], 16), int(vals[-1], 16)   # (AC, DC)

    def lid_set(self, ac, dc):
        _need_win()
        for v in (ac, dc):
            if v not in (0, 1, 2, 3):
                raise ValueError("lid value")
        for cmd, v in (("/setacvalueindex", ac), ("/setdcvalueindex", dc)):
            cp = _run(["powercfg", cmd] + self._LID + [str(v)])
            if cp.returncode != 0:
                raise RuntimeError((cp.stderr or cp.stdout).strip())
        _run(["powercfg", "/setactive", "SCHEME_CURRENT"])

    # ------------------------------------------------------------ input
    _VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "tab": 0x09, "enter": 0x0D, "esc": 0x1B,
           "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "f5": 0x74, "plus": 0xBB, "minus": 0xBD}
    _EXTENDED = {0x25, 0x26, 0x27, 0x28, 0x5B}                # arrow keys and the Windows key need this flag

    def send_text(self, text, stop=None):
        _need_win()
        from ctypes import wintypes
        PUL = ctypes.POINTER(ctypes.c_ulong)

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", PUL)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", PUL)]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        def key(code_unit, up):
            flags = 0x0004 | (0x0002 if up else 0)          # KEYEVENTF_UNICODE | KEYUP
            i = INPUT(type=1)
            i.u.ki = KEYBDINPUT(0, code_unit, flags, 0, None)
            return i

        def vk_key(vk, up):                                   # real Enter / Tab key presses
            i = INPUT(type=1)
            i.u.ki = KEYBDINPUT(vk, 0, 0x0002 if up else 0, 0, None)
            return i

        data = text.encode("utf-16-le")
        units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
        for u in units:
            if stop is not None and stop():                   # Ctrl+Alt+X / "stop" interrupts typing
                break
            if u == 0x0D:                                     # CR: LF (below) is the Enter press
                continue
            if u in (0x0A, 0x09):
                vk = 0x0D if u == 0x0A else 0x09
                arr = (INPUT * 2)(vk_key(vk, False), vk_key(vk, True))
            else:
                arr = (INPUT * 2)(key(u, False), key(u, True))
            ctypes.windll.user32.SendInput(2, arr, ctypes.sizeof(INPUT))
            time.sleep(0.004)

    def send_hotkey(self, combo):
        _need_win()
        u = ctypes.windll.user32
        codes = []
        for part in combo.lower().split("+"):
            part = part.strip()
            if part in self._VK:
                codes.append(self._VK[part])
            elif len(part) == 1 and part.isalnum():
                codes.append(ord(part.upper()))
            else:
                raise ValueError(f"bad key {part}")
        for c in codes:
            u.keybd_event(c, 0, 1 if c in self._EXTENDED else 0, 0)
        for c in reversed(codes):
            u.keybd_event(c, 0, 2 | (1 if c in self._EXTENDED else 0), 0)

    def click(self, x, y):
        _need_win()
        u = ctypes.windll.user32
        u.SetCursorPos(int(x), int(y))
        u.mouse_event(0x0002, 0, 0, 0, 0)
        u.mouse_event(0x0004, 0, 0, 0, 0)

    def foreground_pid(self):
        from ctypes import wintypes
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(self.foreground_window(), ctypes.byref(pid))
        return pid.value


def make_backend() -> Backend:
    return WindowsBackend() if IS_WIN else Backend()
