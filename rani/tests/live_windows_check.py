"""REAL Windows checks - run this on Wali's laptop (run_tests.bat does it).

Safe by design: it never locks, sleeps, restarts or shuts down. It restores volume/mute afterwards,
opens and closes Notepad, takes one screenshot and toggles the autostart registry value back.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("RANI_HOME", str(Path(tempfile.gettempdir()) / "rani_live_test"))

if sys.platform != "win32":
    print("This test must run on Windows."); sys.exit(2)

from rani import startup                       # noqa: E402
from rani.actions import Ctx, Registry         # noqa: E402
from rani.config import Settings               # noqa: E402
from rani.store import Store                   # noqa: E402
from rani.winapi import WindowsBackend         # noqa: E402

results = []


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"{type(e).__name__}: {e}"
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


b = WindowsBackend()
reg = Registry(Ctx(b, Settings(), Store()))

check("known folders resolve (OneDrive-aware)", lambda: (all(b.known_folder(n).exists() for n in
      ("Desktop", "Documents", "Downloads", "Pictures")), str(b.known_folder("Downloads"))))
check("battery", lambda: (reg.execute("battery", {}).ok, str(reg.execute("battery", {}).args)))
check("cpu/ram/gpu", lambda: (reg.execute("system_stats", {}).ok, reg.execute("system_stats", {}).args.get("gpu", "") or "no NVIDIA GPU info"))
check("wifi status", lambda: (True, b.wifi_status()))

def vol():
    old, oldm = b.get_volume(), b.get_mute()
    try:
        r = reg.execute("set_volume", {"level": 23})
        ok1 = r.ok and r.verified
        r2 = reg.execute("set_mute", {"muted": True}); ok2 = r2.ok and b.get_mute() is True
        reg.execute("set_mute", {"muted": False})
        return ok1 and ok2, f"set 23 -> read {b.get_volume()}, mute verified={ok2}"
    finally:
        b.set_volume(old); b.set_mute(oldm)
check("volume + mute (verified by read-back, then restored)", vol)

def bright():
    cur = b.get_brightness()
    if cur is None:
        return True, "no controllable internal display (skipped)"
    r = reg.execute("set_brightness", {"level": cur}); return r.ok, f"{cur}% verified={r.verified}"
check("brightness read/write", bright)

def shot():
    r = reg.execute("screenshot", {}); return r.ok and r.verified, str(r.data)
check("screenshot", shot)

def notepad():
    r = reg.execute("open_app", {"name": "notepad"})
    if not (r.ok and r.verified):
        return False, f"{r.key} {r.detail}"
    time.sleep(1.0)
    w = reg.execute("window_control", {"op": "minimize", "app": "notepad"})
    c = reg.execute("close_app", {"name": "notepad"})
    return c.ok and c.verified, f"open verified, minimize ok={w.ok}, close verified={c.verified}"
check("open -> minimize -> close Notepad", notepad)

check("find Chrome in Start Menu", lambda: (True, str(b.start_menu_search("Chrome")[:2]) or "not installed"))
check("lid-close setting readable (powercfg)", lambda: (True, f"AC/DC action = {b.lid_get()}"))

def autostart():
    before = startup.is_autostart_enabled()
    ok = startup.set_autostart(True) and startup.is_autostart_enabled()
    startup.set_autostart(before)
    return ok and startup.is_autostart_enabled() == before, f"Run key written/verified/restored (was {before})"
check("autostart registry round-trip", autostart)

def lock_api():
    import ctypes
    return hasattr(ctypes.windll.user32, "LockWorkStation") and hasattr(ctypes.windll.powrprof, "SetSuspendState"), \
        "LockWorkStation + SetSuspendState available (NOT executed by this test)"
check("lock/sleep APIs present", lock_api)

def tts():
    from rani.voice import Speaker
    s = Speaker(Settings())
    ok = s.say("ٹیسٹ", "ur", 0.3, wait=True, allow_offline=False)
    return ok, "spoke via " + s.last_engine if ok else "edge-tts failed: " + s.last_error
check("Urdu neural voice (needs internet; plays a short test)", tts)

bad = [r for r in results if not r[1]]
print(f"\n{len(results) - len(bad)}/{len(results)} passed")
sys.exit(1 if bad else 0)
