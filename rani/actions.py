"""Safe action registry.

* Only actions registered here can ever run - no shell, no eval, no free-form commands.
* Every action validates its arguments, performs a real OS operation through the backend,
  then VERIFIES the result (read-back) where Windows allows it.
* Confirmation can only be granted by the app's confirmation flow (a separate spoken/typed
  "haan/yes" from Wali) through `Registry.confirm(token)`.  An AI response can request an
  action but can never confirm one.
* Permissions per category: allow | ask | deny.  `risk="confirm"` is a floor that no setting
  can lower (shutdown, restart, lid-close change, ...).
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import apps as appcat
from .config import Settings
from .store import Store
from .winapi import Backend, NotSupported

CONFIRM_TTL_SEC = 30
# What a "open this file/folder" request may NEVER launch: programs and scripts. A prompt-injected AI reply
# must not be able to start something that was merely downloaded into Downloads.
BLOCKED_OPEN_EXT = {
    ".exe", ".bat", ".cmd", ".com", ".scr", ".msi", ".msp", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".lnk", ".url", ".reg", ".hta", ".jar", ".cpl", ".dll", ".msc", ".pif", ".gadget",
    ".appx", ".msix", ".inf", ".application", ".sh", ".py", ".pyw",
}
RESERVED_NAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
CONFIRM_KEYS = {"shutdown": "confirm_shutdown", "restart": "confirm_restart", "sleep": "confirm_sleep",
                "memory_add": "confirm_memory_add", "set_lid_action": "confirm_lid"}
ALLOWED_HOTKEYS = {
    "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+s", "ctrl+a", "ctrl+f", "ctrl+t", "ctrl+w",
    "ctrl+shift+t", "ctrl+n", "ctrl+p", "ctrl+l", "alt+tab", "win+d", "win+e", "win+tab", "alt+left",
    "alt+right", "f5", "ctrl+r", "ctrl+plus", "ctrl+minus",
}


@dataclass
class Result:
    ok: bool
    key: str
    args: dict = field(default_factory=dict)
    verified: bool | None = None
    detail: str = ""
    needs_confirmation: bool = False
    token: str = ""
    data: Any = None


@dataclass
class ActionSpec:
    name: str
    handler: Callable
    category: str
    description: str
    params: dict                    # name -> "int" | "int:0-100" | "str" | "bool" | "float"  ("?" suffix = optional)
    risk: str = "low"               # low | confirm
    confirm_if_ai: bool = False
    ai_callable: bool = True


@dataclass
class Ctx:
    backend: Backend
    settings: Settings
    store: Store
    cancel: threading.Event = field(default_factory=threading.Event)

    def cancelled(self) -> bool:
        return self.cancel.is_set()


class Registry:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self._specs: dict[str, ActionSpec] = {}
        self._pending: dict[str, tuple[str, dict, str, float]] = {}
        self._lock = threading.Lock()
        _register_all(self)

    # ---------------------------------------------------------------- registration
    def register(self, spec: ActionSpec):
        self._specs[spec.name] = spec

    def names(self):
        return sorted(self._specs)

    def spec(self, name):
        return self._specs.get(name)

    def describe_for_ai(self) -> str:
        lines = []
        for s in sorted(self._specs.values(), key=lambda s: s.name):
            if not s.ai_callable:
                continue
            ps = ", ".join(f"{k}:{v}" for k, v in s.params.items()) or "-"
            lines.append(f"- {s.name}({ps}): {s.description}")
        return "\n".join(lines)

    # ---------------------------------------------------------------- argument validation
    @staticmethod
    def _coerce(schema: dict, args: dict) -> dict:
        out = {}
        unknown = set(args) - set(schema)
        if unknown:
            raise ValueError("unexpected argument(s): " + ", ".join(sorted(unknown)))
        for k, t in schema.items():
            optional = t.endswith("?")
            t = t.rstrip("?")
            if k not in args or args[k] in (None, ""):
                if optional:
                    continue
                raise ValueError(f"missing argument '{k}'")
            v = args[k]
            base, _, rng = t.partition(":")
            if base == "int":
                v = int(float(v))
                if rng:
                    lo, hi = (int(x) for x in rng.split("-"))
                    if not lo <= v <= hi:
                        raise ValueError(f"'{k}' must be between {lo} and {hi}")
            elif base == "float":
                v = float(v)
            elif base == "bool":
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "haan")
            elif base == "str":
                v = str(v)
                if len(v) > 4000:
                    raise ValueError(f"'{k}' too long")
            out[k] = v
        return out

    # ---------------------------------------------------------------- execution
    def _needs_confirm(self, spec: ActionSpec, source: str) -> bool:
        if spec.risk == "confirm":
            return True
        if spec.confirm_if_ai and source == "ai":
            return True
        if spec.name == "sleep" and self.ctx.settings.get("confirm_sleep"):
            return True
        return self.ctx.settings.permission(spec.category) == "ask"

    def execute(self, name: str, args: dict | None = None, source: str = "rules") -> Result:
        args = dict(args or {})
        spec = self._specs.get(name)
        if spec is None:
            r = Result(False, "unknown_action", {}, detail=name)
            self.ctx.store.log_action(name, args, source, False, None, "unknown action")
            return r
        if self.ctx.settings.permission(spec.category) == "deny":
            r = Result(False, "denied", {})
            self.ctx.store.log_action(name, args, source, False, None, "denied by permission")
            return r
        try:
            clean = self._coerce(spec.params, args)
        except (ValueError, TypeError, OverflowError) as e:
            self.ctx.store.log_action(name, args, source, False, None, f"bad args: {e}")
            return Result(False, "bad_args", {"detail": str(e)}, detail=str(e))
        if self._needs_confirm(spec, source):
            token = uuid.uuid4().hex[:10]
            with self._lock:
                self._prune()
                self._pending[token] = (name, clean, source, time.time())
            self.ctx.store.log_action(name, clean, source, True, None, "awaiting confirmation")
            ckey = CONFIRM_KEYS.get(name)          # every key here MUST exist in phrases.py (tests check this)
            what = f"{name} {clean}" if clean else name
            return Result(True, ckey or "confirm_generic", {"what": what, **{k: v for k, v in clean.items()
                                                                              if isinstance(v, (str, int))}},
                          needs_confirmation=True, token=token)
        return self._run(spec, clean, source)

    def _prune(self):
        now = time.time()
        for t in [t for t, v in self._pending.items() if now - v[3] > CONFIRM_TTL_SEC]:
            del self._pending[t]

    def has_pending(self) -> bool:
        with self._lock:
            self._prune()
            return bool(self._pending)

    def latest_pending_token(self) -> str | None:
        with self._lock:
            self._prune()
            if not self._pending:
                return None
            return max(self._pending, key=lambda t: self._pending[t][3])

    def confirm(self, token: str) -> Result:
        """Called ONLY by the app after Wali himself said yes (never from AI output)."""
        with self._lock:
            self._prune()
            item = self._pending.pop(token, None)
        if item is None:
            return Result(False, "confirm_expired", {})
        name, args, source, _ = item
        return self._run(self._specs[name], args, source + "+confirmed")

    def cancel(self, token: str | None = None) -> Result:
        with self._lock:
            if token:
                self._pending.pop(token, None)
            else:
                self._pending.clear()
        return Result(True, "cancelled", {})

    def emergency_stop(self) -> Result:
        """Cancel pending confirmations, flag running work, abort any scheduled shutdown."""
        self.ctx.cancel.set()
        self.cancel()
        try:
            self.ctx.backend.abort_power()
        except Exception:
            pass
        self.ctx.store.log_action("emergency_stop", {}, "user", True, None, "")
        return Result(True, "emergency_stop", {})

    def _run(self, spec: ActionSpec, args: dict, source: str) -> Result:
        self.ctx.cancel.clear()
        try:
            res = spec.handler(self.ctx, **args)
        except NotSupported as e:
            res = Result(False, "error", {"detail": str(e)}, detail=str(e))
        except Exception as e:  # noqa: BLE001 - report every failure to the user
            res = Result(False, "error", {"detail": f"{type(e).__name__}: {e}"[:160]},
                         detail=f"{type(e).__name__}: {e}")
        self.ctx.store.log_action(spec.name, args, source, res.ok, res.verified, res.detail or res.key)
        return res


# ====================================================================== helpers
def _wait(cond: Callable[[], bool], timeout=6.0, step=0.3) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def _allowed_roots(ctx: Ctx) -> list[Path]:
    roots = []
    for n in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"):
        try:
            roots.append(ctx.backend.known_folder(n).resolve())
        except Exception:
            pass
    return roots


def _safe_path(ctx: Ctx, p: str | Path, must_exist=False) -> Path:
    """Resolve and require the path to be inside Wali's own folders (never system folders)."""
    path = Path(p).expanduser().resolve()
    if not any(path == r or r in path.parents for r in _allowed_roots(ctx)):
        raise PermissionError("path outside allowed folders")
    if must_exist and not path.exists():
        raise FileNotFoundError(str(path))
    return path


def _safe_name(name: str) -> str:
    name = name.strip().strip(".").strip()
    if not name or re.search(r'[\\/:*?"<>|\x00-\x1f]', name) or name in (".", ".."):
        raise ValueError("invalid file or folder name")
    if name.split(".")[0].strip().lower() in RESERVED_NAMES:      # CON, NUL, COM1 ... break Windows
        raise ValueError("reserved Windows name")
    return name[:120]


# ====================================================================== handlers
def h_open_app(ctx, name):
    key = appcat.resolve_app(name)
    spec = appcat.APPS.get(key) if key else None
    display = spec["display"] if spec else name
    procs = spec["proc"] if spec else []
    cands = list(spec["launch"]) if spec else []
    b = ctx.backend
    base_pids = b.pids_for(procs) if procs else set()
    base_wins = b.window_count_for(procs) if procs else 0
    launched = False
    last_err = ""
    for c in cands:
        try:
            b.launch(c); launched = True; break
        except NotSupported:
            raise
        except OSError as e:
            last_err = str(e)
    if not launched:                                    # fall back to Start-Menu shortcut search
        query = (spec["lnk"] if spec and spec["lnk"] else name)
        hits = b.start_menu_search(query) if query else []
        if hits:
            try:
                b.launch(hits[0][1]); launched = True
                display = display if spec else hits[0][0]
            except OSError as e:
                last_err = str(e)
    if not launched:
        return Result(False, "app_not_found", {"app": display}, detail=last_err or "no launcher/shortcut found")
    if not procs:
        return Result(True, "open_app_unverified", {"app": display}, verified=None, detail="no process info")
    def up():
        pids = b.pids_for(procs)
        return bool(pids - base_pids) or (bool(pids) and b.window_count_for(procs) > base_wins)
    if _wait(up, 7.0):
        return Result(True, "open_app_done", {"app": display}, verified=True)
    still = bool(b.pids_for(procs))
    return Result(True, "open_app_unverified", {"app": display}, verified=None if still else False,
                  detail="process present but no change observed" if still else "process did not appear")


def h_close_app(ctx, name):
    key = appcat.resolve_app(name)
    if not key:
        return Result(False, "app_not_found", {"app": name})
    spec = appcat.APPS[key]
    if spec.get("protected") or any(p.lower() in appcat.PROTECTED_PROCESSES for p in spec["proc"]):
        return Result(False, "denied", {}, detail="protected process")
    if not ctx.backend.pids_for(spec["proc"]):
        return Result(True, "close_app_not_running", {"app": spec["display"]}, verified=True)
    had_windows = ctx.backend.window_count_for(spec["proc"]) > 0
    ctx.backend.close_gracefully(spec["proc"])

    def gone():
        if not ctx.backend.pids_for(spec["proc"]):
            return True
        # background processes can stay alive after the last window is closed - that still counts as closed
        return had_windows and ctx.backend.window_count_for(spec["proc"]) == 0
    if _wait(gone, 6.0):
        return Result(True, "close_app_done", {"app": spec["display"]}, verified=True)
    return Result(False, "close_app_failed", {"app": spec["display"]}, verified=False,
                  detail="still running (app may be asking to save work)")


def h_find_app(ctx, query):
    hits = ctx.backend.start_menu_search(query)
    return Result(bool(hits), "files_found" if hits else "files_none",
                  {"count": len(hits), "first": hits[0][0] if hits else ""}, data=[h[0] for h in hits[:10]])


def h_window_control(ctx, op, app=""):
    b = ctx.backend
    if op not in ("minimize", "maximize", "focus"):
        return Result(False, "bad_args", {"detail": "op must be minimize, maximize or focus"}, detail="bad op")
    if app:
        key = appcat.resolve_app(app)
        if not key:
            return Result(False, "app_not_found", {"app": app})
        wins = b.find_windows(appcat.APPS[key]["proc"])
        if not wins:
            return Result(False, "window_none", {"app": appcat.APPS[key]["display"]})
        hwnd = wins[0]
    else:
        hwnd = b.foreground_window()
        if b.window_pid(hwnd) == os.getpid():                   # that is RANI's own HUD/settings window
            return Result(False, "window_none", {"app": "current"}, detail="foreground window is RANI itself")
    b.window_op(hwnd, op)
    time.sleep(0.4)
    ok = {"minimize": lambda: b.is_minimized(hwnd), "maximize": lambda: b.is_maximized(hwnd),
          "focus": lambda: b.foreground_window() == hwnd}[op]() if hasattr(b, "is_minimized") else None
    return Result(bool(ok) if ok is not None else True, "window_done" if ok in (True, None) else "error",
                  {"detail": "window did not change"}, verified=ok)


def h_set_volume(ctx, level):
    ctx.backend.set_volume(level)
    got = ctx.backend.get_volume()
    ok = abs(got - level) <= 2
    return Result(ok, "volume_set" if ok else "volume_failed", {"level": got, "detail": f"read back {got}"},
                  verified=ok)


def h_change_volume(ctx, delta):
    cur = ctx.backend.get_volume()
    new = max(0, min(100, cur + delta))
    ctx.backend.set_volume(new)
    got = ctx.backend.get_volume()
    ok = abs(got - new) <= 2
    return Result(ok, "volume_changed" if ok else "volume_failed", {"level": got, "detail": f"read back {got}"},
                  verified=ok)


def h_get_volume(ctx):
    return Result(True, "volume_changed", {"level": ctx.backend.get_volume()}, verified=True)


def h_set_mute(ctx, muted):
    ctx.backend.set_mute(muted)
    ok = ctx.backend.get_mute() == muted
    return Result(ok, ("muted" if muted else "unmuted") if ok else "volume_failed",
                  {"detail": "mute state did not change"}, verified=ok)


def h_set_brightness(ctx, level):
    try:
        ctx.backend.set_brightness(level)
        got = ctx.backend.get_brightness()
    except NotSupported:
        raise
    except Exception as e:
        return Result(False, "brightness_unsupported", {}, detail=str(e))
    ok = got is not None and abs(got - level) <= 3
    return Result(ok, "brightness_set" if ok else "brightness_unsupported", {"level": got if got is not None else level},
                  verified=ok)


def h_change_brightness(ctx, delta):
    try:
        cur = ctx.backend.get_brightness()
    except NotSupported:
        raise
    except Exception as e:
        return Result(False, "brightness_unsupported", {}, detail=str(e))
    if cur is None:
        return Result(False, "brightness_unsupported", {})
    return h_set_brightness(ctx, max(0, min(100, cur + delta)))


def h_battery(ctx):
    b = ctx.backend.battery()
    if b is None:
        return Result(False, "battery_none", {})
    pct, plugged = b
    return Result(True, "battery", {"percent": pct, "plug": "", "plugged": plugged}, verified=True,
                  data={"percent": pct, "plugged": plugged})


def h_system_stats(ctx):
    cpu, ram = ctx.backend.cpu_ram()
    gpu = None
    try:
        gpu = ctx.backend.gpu()
    except Exception:
        pass
    extra = f", {gpu}" if gpu else ""
    return Result(True, "stats", {"cpu": round(cpu), "ram": round(ram), "gpu": extra}, verified=True,
                  data={"cpu": cpu, "ram": ram, "gpu": gpu})


def h_wifi_status(ctx):
    return Result(True, "wifi_status", {"state": ctx.backend.wifi_status()}, verified=True)


def h_screenshot(ctx):
    folder = ctx.backend.known_folder("Pictures") / "RANI Screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rani_{datetime.now():%Y%m%d_%H%M%S}.png"
    ctx.backend.screenshot(str(path))
    ok = path.exists() and path.stat().st_size > 1000
    return Result(ok, "screenshot_done" if ok else "error", {"detail": "file not written"}, verified=ok,
                  data=str(path))


def h_lock(ctx):
    ok = ctx.backend.lock()
    return Result(ok, "locked" if ok else "lock_failed", {}, verified=None,
                  detail="LockWorkStation returned %s" % ok)


def h_sleep(ctx):
    ok = ctx.backend.sleep()
    return Result(ok, "sleeping" if ok else "sleep_failed", {}, verified=None)


def _power(ctx, restart):
    try:
        sec = max(10, min(600, int(ctx.settings.get("shutdown_grace_sec"))))   # always leave time to say "cancel"
    except (TypeError, ValueError):
        sec = 30
    try:
        ctx.backend.schedule_power(sec, restart)
    except NotSupported:
        raise
    except Exception as e:
        return Result(False, "power_failed", {"detail": str(e)}, detail=str(e))
    return Result(True, "restart_scheduled" if restart else "shutdown_scheduled", {"sec": sec}, verified=None)


def h_shutdown(ctx):
    return _power(ctx, False)


def h_restart(ctx):
    return _power(ctx, True)


def h_cancel_power(ctx):
    ok = ctx.backend.abort_power()
    return Result(True, "power_cancelled" if ok else "power_nothing_to_cancel", {}, verified=ok)


LID_MODES = {"nothing": 0, "sleep": 1, "hibernate": 2, "shutdown": 3}


def h_set_lid_action(ctx, mode, power="both"):
    if mode not in ("nothing", "sleep"):
        return Result(False, "bad_args", {"detail": "mode must be 'nothing' or 'sleep'"})
    if power not in ("both", "ac", "dc"):
        return Result(False, "bad_args", {"detail": "power must be 'both', 'ac' or 'dc'"})
    try:
        ac, dc = ctx.backend.lid_get()
        backup = Path(ctx.settings.path).with_name("lid_backup.json")
        if not backup.exists():                       # keep the ORIGINAL values for restore
            import json
            backup.write_text(json.dumps({"ac": ac, "dc": dc}), encoding="utf-8")
        v = LID_MODES[mode]
        new_ac = v if power in ("both", "ac") else ac
        new_dc = v if power in ("both", "dc") else dc
        ctx.backend.lid_set(new_ac, new_dc)
        got = ctx.backend.lid_get()
    except NotSupported:
        raise
    except Exception as e:
        return Result(False, "lid_failed", {"detail": str(e)}, detail=str(e))
    ok = got == (new_ac, new_dc)
    return Result(ok, "lid_set" if ok else "lid_failed", {"detail": f"read back {got}"}, verified=ok)


def h_restore_lid_action(ctx):
    import json
    backup = Path(ctx.settings.path).with_name("lid_backup.json")
    if not backup.exists():
        return Result(False, "lid_failed", {"detail": "no saved original setting"})
    saved = json.loads(backup.read_text(encoding="utf-8"))
    ctx.backend.lid_set(int(saved["ac"]), int(saved["dc"]))
    ok = ctx.backend.lid_get() == (int(saved["ac"]), int(saved["dc"]))
    if ok:
        backup.unlink(missing_ok=True)
    return Result(ok, "lid_restored" if ok else "lid_failed", {"detail": "read-back mismatch"}, verified=ok)


# ---- files
def h_open_path(ctx, name):
    key = name.strip()
    folder = appcat.KNOWN_FOLDERS.get(key.lower(), None)
    if folder is None and key in ("Downloads", "Documents", "Desktop", "Pictures", "Videos", "Music", "home"):
        folder = "" if key == "home" else key
    if folder is not None:
        path = ctx.backend.known_folder(folder)
    else:
        path = _safe_path(ctx, key)
    if not path.exists():
        return Result(False, "path_missing", {"name": name})
    if folder is None:
        path = _safe_path(ctx, path)
    if path.is_file() and path.suffix.lower() in BLOCKED_OPEN_EXT:
        return Result(False, "path_blocked", {}, detail=f"{path.suffix} files can contain programs - not opened")
    ctx.backend.open_path(str(path))
    return Result(True, "path_opened", {"name": path.name or "Home"}, verified=None, data=str(path))


def h_search_files(ctx, query, folder=""):
    toks = [t for t in re.split(r"[\s._\-]+", query.lower()) if t]
    if not toks:
        return Result(False, "files_none", {})
    roots = [_safe_path(ctx, ctx.backend.known_folder(folder))] if folder else _allowed_roots(ctx)
    skip = {"node_modules", ".git", "__pycache__", ".venv", "venv", "appdata"}
    hits: list[tuple[float, str]] = []
    deadline = time.time() + 8
    for root in roots:
        if time.time() > deadline or ctx.cancelled() or len(hits) >= 300:
            break
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d.lower() not in skip and not d.startswith(".")]
            for f in files:
                low = f.lower()
                if all(t in low for t in toks):
                    p = os.path.join(dirpath, f)
                    try:
                        hits.append((os.path.getmtime(p), p))
                    except OSError:
                        pass
            if time.time() > deadline or ctx.cancelled() or len(hits) >= 300:
                break
    hits.sort(reverse=True)
    paths = [p for _, p in hits[:10]]
    if not paths:
        return Result(False, "files_none", {})
    return Result(True, "files_found", {"count": len(hits), "first": os.path.basename(paths[0])},
                  verified=True, data=paths)


def h_create_folder(ctx, name, parent="desktop"):
    nm = _safe_name(name)
    base = ctx.backend.known_folder(appcat.KNOWN_FOLDERS.get(parent.lower(), parent.title()))
    path = _safe_path(ctx, base / nm)
    path.mkdir(parents=True, exist_ok=True)
    return Result(path.is_dir(), "folder_created", {"name": nm}, verified=path.is_dir(), data=str(path))


def h_rename_path(ctx, path, new_name):
    src = _safe_path(ctx, path, must_exist=True)
    if src in _allowed_roots(ctx):
        return Result(False, "path_blocked", {}, detail="main user folders cannot be renamed")
    dst = _safe_path(ctx, src.with_name(_safe_name(new_name)))
    if dst.exists():
        return Result(False, "target_exists", {})
    src.rename(dst)
    ok = dst.exists() and not src.exists()
    return Result(ok, "file_renamed", {}, verified=ok, data=str(dst))


def h_move_path(ctx, path, dest_folder):
    src = _safe_path(ctx, path, must_exist=True)
    if src in _allowed_roots(ctx):
        return Result(False, "path_blocked", {}, detail="main user folders cannot be moved")
    d = appcat.KNOWN_FOLDERS.get(dest_folder.lower())
    dest_dir = _safe_path(ctx, ctx.backend.known_folder(d) if d is not None else dest_folder)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / src.name
    if dst.exists():
        return Result(False, "target_exists", {})
    shutil.move(str(src), str(dst))
    ok = dst.exists() and not src.exists()
    return Result(ok, "file_moved", {}, verified=ok, data=str(dst))


def h_copy_path(ctx, path, dest_folder):
    src = _safe_path(ctx, path, must_exist=True)
    d = appcat.KNOWN_FOLDERS.get(dest_folder.lower())
    dest_dir = _safe_path(ctx, ctx.backend.known_folder(d) if d is not None else dest_folder)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / src.name
    if dst.exists():
        return Result(False, "target_exists", {})
    shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
    return Result(dst.exists(), "file_copied", {}, verified=dst.exists(), data=str(dst))


TEXT_EXT = {".txt", ".md", ".csv", ".log", ".json", ".py", ".js", ".html", ".css", ".ini", ".yaml", ".yml"}


def h_read_document(ctx, path):
    p = _safe_path(ctx, path, must_exist=True)
    ext = p.suffix.lower()
    if ext in TEXT_EXT:
        text = p.read_bytes()[:400_000].decode("utf-8", errors="replace")
    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return Result(False, "error", {"detail": "install pypdf to read PDFs"})
        text = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages[:30])
    elif ext == ".docx":
        try:
            import docx
        except ImportError:
            return Result(False, "error", {"detail": "install python-docx to read Word files"})
        text = "\n".join(par.text for par in docx.Document(str(p)).paragraphs)
    else:
        return Result(False, "error", {"detail": f"unsupported file type {ext}"})
    text = text.strip()
    if not text:
        return Result(False, "error", {"detail": "no readable text found"})
    return Result(True, "doc_summary", {"text": text[:300]}, verified=True, data=text[:12000])


def h_create_document(ctx, title, content="", fmt="txt"):
    nm = _safe_name(title)
    folder = ctx.backend.known_folder("Documents") / "RANI"
    folder.mkdir(parents=True, exist_ok=True)
    fmt = fmt.lower().lstrip(".")
    if fmt not in ("txt", "md", "docx"):
        return Result(False, "bad_args", {"detail": "fmt must be txt, md or docx"})
    path = folder / f"{nm}.{fmt}"
    n = 1
    while path.exists():
        n += 1
        path = folder / f"{nm}_{n}.{fmt}"
    if fmt == "docx":
        try:
            import docx
        except ImportError:
            return Result(False, "error", {"detail": "install python-docx for .docx"})
        d = docx.Document()
        d.add_heading(title, 1)
        for para in content.split("\n"):
            d.add_paragraph(para)
        d.save(str(path))
    else:
        path.write_text((f"# {title}\n\n" if fmt == "md" else "") + content, encoding="utf-8")
    return Result(path.exists(), "doc_created", {"name": path.name}, verified=path.exists(), data=str(path))


def h_create_python_project(ctx, name):
    nm = re.sub(r"[^A-Za-z0-9_\-]", "_", name).strip("_")[:50] or "rani_project"
    base = ctx.backend.known_folder("Documents") / "RANI Projects"
    path = base / nm
    n = 1
    while path.exists():
        n += 1
        path = base / f"{nm}_{n}"
    path.mkdir(parents=True)
    (path / "main.py").write_text(
        '"""%s - created by RANI AI for Wali Hasan."""\n\n\ndef main():\n    print("Hello from %s!")\n\n\n'
        'if __name__ == "__main__":\n    main()\n' % (nm, nm), encoding="utf-8")
    (path / "requirements.txt").write_text("", encoding="utf-8")
    (path / "README.md").write_text(f"# {nm}\n\nRun: `python main.py`\n", encoding="utf-8")
    (path / ".gitignore").write_text(".venv/\n__pycache__/\n*.pyc\n.env\n", encoding="utf-8")
    ok = (path / "main.py").exists()
    return Result(ok, "project_created", {"name": path.name, "path": str(path)}, verified=ok, data=str(path))


# ---- input
def h_type_text(ctx, text):
    ctx.backend.send_text(text, stop=ctx.cancelled)
    return Result(True, "typed", {}, verified=None, detail=f"{len(text)} chars sent")


def h_hotkey(ctx, keys):
    k = keys.lower().replace(" ", "")
    if k not in ALLOWED_HOTKEYS:
        return Result(False, "hotkey_blocked", {})
    ctx.backend.send_hotkey(k)
    return Result(True, "hotkey_done", {}, verified=None)


def h_mouse_click(ctx, x, y):
    ctx.backend.click(x, y)
    return Result(True, "clicked", {}, verified=None)


# ---- browser
def h_open_url(ctx, url):
    if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", url, re.I):
        return Result(False, "url_blocked", {})
    ok = ctx.backend.open_url(url)
    return Result(ok, "url_opened" if ok else "error", {"detail": "no browser opened"}, verified=None)


def h_web_search(ctx, query, engine="google"):
    from urllib.parse import quote_plus
    base = {"google": "https://www.google.com/search?q=", "youtube": "https://www.youtube.com/results?search_query="}
    if engine not in base:
        return Result(False, "bad_args", {"detail": "engine must be google or youtube"})
    ok = ctx.backend.open_url(base[engine] + quote_plus(query))
    return Result(ok, "search_done" if ok else "error", {"engine": engine.title(), "query": query,
                                                           "detail": "no browser opened"}, verified=None)


# ---- productivity
def h_set_timer(ctx, seconds):
    if seconds < 1 or seconds > 86400:
        return Result(False, "bad_args", {"detail": "timer must be 1 second to 24 hours"})
    rid = ctx.store.add_reminder(time.time() + seconds, "timer", "timer")
    if seconds >= 3600 and seconds % 3600 == 0:
        dur, dur_u = f"{seconds // 3600} hr", f"{seconds // 3600} گھنٹے"
    elif seconds >= 60:
        mins = round(seconds / 60, 1)
        mins = int(mins) if mins == int(mins) else mins
        dur, dur_u = f"{mins} min", f"{mins} منٹ"
    else:
        dur, dur_u = f"{seconds} sec", f"{seconds} سیکنڈ"
    return Result(rid > 0, "timer_set", {"dur": dur, "dur_u": dur_u}, verified=True)


def h_set_reminder(ctx, text, due, label=""):
    due = float(due)
    now = time.time()
    if not (now - 60 <= due <= now + 366 * 86400):
        return Result(False, "bad_args", {"detail": "reminder time must be within the next year"}, detail="bad time")
    rid = ctx.store.add_reminder(due, text, "reminder")
    return Result(rid > 0, "reminder_set", {"text": text, "when": label or datetime.fromtimestamp(float(due)).strftime("%H:%M")},
                  verified=True)


def h_add_task(ctx, text):
    tid = ctx.store.add_task(text)
    return Result(tid > 0, "task_added", {"text": text}, verified=True)


def h_list_tasks(ctx):
    tasks = ctx.store.list_tasks()
    if not tasks:
        return Result(True, "tasks_none", {})
    return Result(True, "tasks_list", {"count": len(tasks), "items": "; ".join(t["text"] for t in tasks[:8])},
                  verified=True, data=tasks)


# ---- memory
def h_memory_add(ctx, text):
    mid = ctx.store.add_memory(text)
    return Result(mid > 0, "memory_saved", {"text": text}, verified=True)


def h_memory_list(ctx):
    mems = ctx.store.list_memories()
    if not mems:
        return Result(True, "memory_empty", {})
    return Result(True, "memory_list", {"items": "; ".join(m["text"] for m in mems[:10])}, verified=True, data=mems)


def _register_all(reg: Registry):
    R = reg.register
    A = ActionSpec
    R(A("open_app", h_open_app, "apps", "Open an application by name (chrome, vscode, notepad, any installed app)", {"name": "str"}))
    R(A("close_app", h_close_app, "apps", "Politely close a known application", {"name": "str"}))
    R(A("find_app", h_find_app, "apps", "Search installed apps in the Start Menu", {"query": "str"}))
    R(A("window_control", h_window_control, "apps", "minimize/maximize/focus a window (op) of an app, or the current window", {"op": "str", "app": "str?"}))
    R(A("set_volume", h_set_volume, "system", "Set speaker volume 0-100", {"level": "int:0-100"}))
    R(A("change_volume", h_change_volume, "system", "Raise/lower volume by delta (-100..100)", {"delta": "int:-100-100"}))
    R(A("get_volume", h_get_volume, "system", "Read the current volume", {}))
    R(A("set_mute", h_set_mute, "system", "Mute (muted=true) or unmute", {"muted": "bool"}))
    R(A("set_brightness", h_set_brightness, "system", "Set screen brightness 0-100 (laptop display)", {"level": "int:0-100"}))
    R(A("change_brightness", h_change_brightness, "system", "Change brightness by delta", {"delta": "int:-100-100"}))
    R(A("battery", h_battery, "system", "Battery percentage and charging state", {}))
    R(A("system_stats", h_system_stats, "system", "CPU, RAM and NVIDIA GPU usage", {}))
    R(A("wifi_status", h_wifi_status, "network", "Wi-Fi connection status", {}))
    R(A("screenshot", h_screenshot, "system", "Take a screenshot into Pictures/RANI Screenshots", {}))
    R(A("lock", h_lock, "power", "Lock the Windows session", {}, risk="low"))
    R(A("sleep", h_sleep, "power", "Put the laptop to sleep", {}))
    R(A("shutdown", h_shutdown, "power", "Shut down Windows (needs confirmation, short cancel window)", {}, risk="confirm"))
    R(A("restart", h_restart, "power", "Restart Windows (needs confirmation, short cancel window)", {}, risk="confirm"))
    R(A("cancel_power", h_cancel_power, "power", "Cancel a scheduled shutdown/restart", {}))
    R(A("set_lid_action", h_set_lid_action, "power", "Change what closing the lid does (nothing|sleep); needs confirmation", {"mode": "str", "power": "str?"}, risk="confirm"))
    R(A("restore_lid_action", h_restore_lid_action, "power", "Restore the original lid-close setting", {}, risk="confirm"))
    R(A("open_path", h_open_path, "files", "Open a known folder (downloads, documents, desktop, pictures, videos, music) or a path inside them", {"name": "str"}))
    R(A("search_files", h_search_files, "files", "Search file names in Desktop/Documents/Downloads/Pictures/Videos/Music", {"query": "str", "folder": "str?"}))
    R(A("create_folder", h_create_folder, "files", "Create a folder in a known location", {"name": "str", "parent": "str?"}))
    R(A("rename_path", h_rename_path, "files", "Rename a file/folder inside allowed folders", {"path": "str", "new_name": "str"}, risk="confirm"))
    R(A("move_path", h_move_path, "files", "Move a file/folder into another allowed folder", {"path": "str", "dest_folder": "str"}, risk="confirm"))
    R(A("copy_path", h_copy_path, "files", "Copy a file/folder into another allowed folder", {"path": "str", "dest_folder": "str"}))
    R(A("read_document", h_read_document, "files", "Read text from a txt/md/pdf/docx file so it can be summarised", {"path": "str"}))
    R(A("create_document", h_create_document, "files", "Create a document (fmt txt|md|docx) in Documents/RANI", {"title": "str", "content": "str?", "fmt": "str?"}))
    R(A("create_python_project", h_create_python_project, "files", "Scaffold a starter Python project in Documents/RANI Projects", {"name": "str"}))
    R(A("type_text", h_type_text, "input", "Type text into the focused window", {"text": "str"}))
    R(A("hotkey", h_hotkey, "keys", "Press an allow-listed keyboard shortcut (e.g. ctrl+c, alt+tab, win+d)", {"keys": "str"}))
    R(A("mouse_click", h_mouse_click, "input", "Left-click at screen coordinates", {"x": "int:0-20000", "y": "int:0-20000"}))
    R(A("open_url", h_open_url, "browser", "Open an http(s) URL in the default browser", {"url": "str"}))
    R(A("web_search", h_web_search, "browser", "Search google or youtube (engine) for query", {"query": "str", "engine": "str?"}))
    R(A("set_timer", h_set_timer, "productivity", "Start a timer (seconds)", {"seconds": "int:1-86400"}))
    R(A("set_reminder", h_set_reminder, "productivity", "Reminder text at epoch time 'due'", {"text": "str", "due": "float", "label": "str?"}))
    R(A("add_task", h_add_task, "productivity", "Add a to-do task", {"text": "str"}))
    R(A("list_tasks", h_list_tasks, "productivity", "List pending tasks", {}))
    R(A("memory_add", h_memory_add, "memory", "Save a preference/fact about Wali (asks Wali to approve when proposed by AI)", {"text": "str"}, confirm_if_ai=True))
    R(A("memory_list", h_memory_list, "memory", "List saved memories", {}))
