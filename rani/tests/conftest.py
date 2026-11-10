import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rani.actions import Ctx, Registry                        # noqa: E402
from rani.app import NullSpeaker, RaniApp                      # noqa: E402
from rani.brain import Brain, Provider                         # noqa: E402
from rani.config import Settings                               # noqa: E402
from rani.store import Store                                   # noqa: E402
from rani.winapi import Backend                                # noqa: E402


class FakeBackend(Backend):
    """In-memory Windows stand-in that records every call (used for logic tests on any OS)."""

    def __init__(self, root: Path):
        self.root = root
        self.calls: list[tuple] = []
        self.procs: dict[str, set[int]] = {}
        self.volume, self.muted, self.brightness = 40, False, 60
        self.volume_works = True
        self.lid = (1, 1)
        self.power_scheduled = None
        self.launchable = {"chrome": "chrome.exe", "notepad.exe": "notepad.exe", "code": "Code.exe"}
        self.battery_val = (87, True)
        self._next_pid = 1000
        for n in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"):
            (root / n).mkdir(parents=True, exist_ok=True)

    def launch(self, c):
        self.calls.append(("launch", c))
        if c not in self.launchable:
            raise OSError("not found")
        self._next_pid += 1
        self.procs.setdefault(self.launchable[c], set()).add(self._next_pid)

    def pids_for(self, names):
        return {p for n in names for p in self.procs.get(n, set())}

    def window_count_for(self, names):
        return len(self.pids_for(names))

    def close_gracefully(self, names):
        self.calls.append(("close", tuple(names)))
        for n in names:
            self.procs.pop(n, None)

    def start_menu_search(self, q):
        return []

    def open_path(self, p): self.calls.append(("open_path", p))
    def open_url(self, u): self.calls.append(("open_url", u)); return True

    def known_folder(self, name):
        return self.root if name in ("", "home") else self.root / name

    def get_volume(self): return self.volume
    def set_volume(self, l):
        self.calls.append(("set_volume", l))
        if self.volume_works:
            self.volume = l
    def get_mute(self): return self.muted
    def set_mute(self, m): self.muted = m
    def get_brightness(self): return self.brightness
    def set_brightness(self, l): self.brightness = l
    def battery(self): return self.battery_val
    def cpu_ram(self): return 12.0, 55.0
    def gpu(self): return "GPU 3%"
    def wifi_status(self): return "connected (Home)"

    def screenshot(self, path):
        from PIL import Image
        import random
        img = Image.effect_noise((200, 200), 80)
        img.save(path)

    def lock(self): self.calls.append(("lock",)); return True
    def sleep(self): self.calls.append(("sleep",)); return True
    def schedule_power(self, s, restart):
        self.calls.append(("schedule_power", s, restart)); self.power_scheduled = (s, restart)
    def abort_power(self):
        had = self.power_scheduled is not None
        self.power_scheduled = None
        self.calls.append(("abort_power",))
        return had
    def lid_get(self): return self.lid
    def lid_set(self, ac, dc): self.lid = (ac, dc)
    def send_text(self, t, stop=None): self.calls.append(("send_text", t))
    def send_hotkey(self, c): self.calls.append(("hotkey", c))
    def click(self, x, y): self.calls.append(("click", x, y))
    def find_windows(self, names): return []
    def foreground_window(self): return 1


class ScriptedProvider(Provider):
    def __init__(self, name="fake", reply=None, fail=None, available=True):
        self.name, self._reply, self._fail, self._avail = name, reply, fail, available
        self.calls = 0

    def available(self, settings): return self._avail

    def chat(self, settings, system, history, user):
        self.calls += 1
        if self._fail:
            raise self._fail
        return self._reply if isinstance(self._reply, str) else self._reply(user)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("RANI_HOME", str(tmp_path / "appdata"))
    return tmp_path


@pytest.fixture
def backend(home):
    return FakeBackend(home / "user")


@pytest.fixture
def settings(home):
    return Settings(home / "settings.json")


@pytest.fixture
def reg(home, backend, settings):
    return Registry(Ctx(backend, settings, Store(home / "r.db")))


@pytest.fixture
def make_app(home, backend, settings):
    def _make(providers=None):
        brain = Brain(settings, providers or [])
        settings.data["providers_order"] = [p.name for p in (providers or [])]
        app = RaniApp(settings=settings, store=Store(home / "t.db"), backend=backend, brain=brain,
                      speaker=NullSpeaker())
        return app
    return _make


def drain(app, timeout=3.0):
    """Wait until the command worker has processed everything."""
    import time
    end = time.time() + timeout
    time.sleep(0.05)
    while time.time() < end and (not app._cmds.empty() or app._st["state"] in ("thinking",)):
        time.sleep(0.02)
    time.sleep(0.15)
