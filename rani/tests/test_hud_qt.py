"""Runs the REAL Qt HUD + QWebChannel bridge offscreen (skipped when PySide6/WebEngine is missing)."""
import json
import os
import sys
import time

import pytest

pytest.importorskip("PySide6.QtWebEngineWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")

from PySide6.QtWidgets import QApplication   # noqa: E402

from rani.app import RaniApp, NullSpeaker      # noqa: E402
from rani.config import Settings               # noqa: E402
from rani.store import Store                   # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def js(view, code, wait=0.6):
    box = {}
    view.page().runJavaScript(code, lambda v: box.setdefault("v", v))
    end = time.time() + 5
    while "v" not in box and time.time() < end:
        QApplication.processEvents(); time.sleep(0.02)
    return box.get("v")


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        QApplication.processEvents(); time.sleep(0.02)


@pytest.fixture
def hud(qapp, home, backend):
    from rani.hud_window import HudWindow
    app = RaniApp(settings=Settings(home / "s.json"), store=Store(home / "q.db"), backend=backend, speaker=NullSpeaker())
    w = HudWindow(app); w.show(); pump(2.5)
    yield app, w
    w.close()


def test_hud_follows_app_state_through_bridge(hud):
    app, w = hud
    for state, label in [("listening", "LISTENING"), ("thinking", "THINKING"), ("executing", "EXECUTING")]:
        app.set_state(state, user="Chrome kholo", reply="Jee Wali!")
        pump(0.5)
        assert js(w, "document.getElementById('label').textContent") == label
    assert js(w, "document.getElementById('reply').textContent") == "Jee Wali!"
    app.set_state("error", error="boom"); pump(0.5)
    assert js(w, "document.getElementById('task').textContent") == "boom"
    assert js(w, "document.body.classList.contains('err')") is True


def test_hud_is_frameless_topmost_top_right(hud):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app, w = hud
    assert w.windowFlags() & Qt.FramelessWindowHint and w.windowFlags() & Qt.WindowStaysOnTopHint
    geo = QApplication.primaryScreen().availableGeometry()
    assert abs((w.x() + w.width()) - (geo.right() + 1 - int(app.settings.get("hud_margin")))) <= 2
    assert w.y() <= geo.top() + int(app.settings.get("hud_margin")) + 2
    w.set_compact(True, save=False); pump(0.3)
    assert w.width() < 200 and abs((w.x() + w.width()) - (geo.right() + 1 - 16)) <= 2    # stays in the corner


def test_clicking_buttons_reach_python(hud):
    app, w = hud
    js(w, "document.getElementById('bStop').click()"); pump(0.3)
    assert any("روک" in s for s, _ in app.speaker.said)


def test_settings_page_roundtrip(hud):
    app, w = hud
    w.open_settings(); pump(3.0)
    v = w._settings_view
    assert js(v, "document.getElementById('greeting_id').value") == "default"
    js(v, "document.getElementById('startup_delay_sec').value=12; document.getElementById('saveGeneral').click(); 1")
    pump(1.5)
    assert app.settings.get("startup_delay_sec") == 12
    # keys can be written but are never exposed to the page
    page_settings = json.dumps(app.settings.data)
    assert "API_KEY" not in page_settings
    v.close()
