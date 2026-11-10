"""Qt (PySide6 + WebEngine) floating HUD: transparent, frameless, always-on-top, top-right corner.

Chromium's GPU compositing renders the canvas animation, so the GTX 1660 Ti does the drawing.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QSize, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QRadialGradient
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import startup
from .app import RaniApp
from .config import SECRET_NAMES, get_secret, has_secret, set_secret
from .intents import detect_lang

HUD_DIR = Path(__file__).parent / "hud"
COMPACT = QSize(170, 170)


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QRadialGradient(28, 24, 34)
    g.setColorAt(0, QColor(190, 250, 255))
    g.setColorAt(0.5, QColor(0, 200, 255))
    g.setColorAt(1, QColor(20, 70, 200))
    p.setBrush(g)
    p.setPen(QColor(120, 240, 255))
    p.drawEllipse(6, 6, 52, 52)
    p.end()
    return QIcon(pm)


class Bridge(QObject):
    """Everything the web UI may call. No secrets are ever returned, only written."""

    def __init__(self, app: RaniApp, hud: "HudWindow"):
        super().__init__()
        self.app, self.hud = app, hud

    # ---- HUD
    @Slot(result=str)
    def snapshot(self):
        return json.dumps(self.app.snapshot(), ensure_ascii=False)

    @Slot(str)
    def submit(self, text):
        self.app.submit(text, "text")

    @Slot()
    def ptt(self):
        self.app.push_to_talk()

    @Slot()
    def stop(self):
        self.app.emergency_stop()

    @Slot()
    def toggle_compact(self):
        self.hud.set_compact(not self.app.compact)

    @Slot()
    def open_settings(self):
        self.hud.open_settings()

    # ---- settings
    @Slot(result=str)
    def get_settings(self):
        s = self.app.settings
        return json.dumps({"settings": s.data, "autostart": startup.is_autostart_enabled(),
                           "has_keys": {n: has_secret(n) for n in SECRET_NAMES},
                           "has_gemini_key": has_secret("GEMINI_API_KEY"),
                           "has_openai_key": has_secret("OPENAI_COMPAT_API_KEY")}, ensure_ascii=False)

    @Slot(str, result=str)
    def save_settings(self, payload):
        try:
            values = json.loads(payload)
            self.app.settings.update(values)
            if "start_compact" in values:
                self.hud.set_compact(bool(values["start_compact"]))
            return json.dumps({"ok": True})
        except Exception as e:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(bool, result=str)
    def set_autostart(self, enabled):
        try:
            ok = startup.set_autostart(bool(enabled))
            self.app.settings.update({"autostart": bool(enabled)})
            return json.dumps({"ok": ok, "error": "" if ok else "registry did not match (Windows only)"})
        except Exception as e:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, str, result=str)
    def set_secret(self, name, value):
        if name not in SECRET_NAMES:
            return json.dumps({"ok": False, "error": "unknown secret"})
        ok = set_secret(name, value.strip())
        self.app.brain.reset()                       # new key -> forget any "cooling down" state
        return json.dumps({"ok": ok, "error": "" if ok else "keyring not available - put the key in .env instead"})

    @Slot(result=str)
    def list_voices(self):
        sp = self.app.speaker
        return json.dumps(sp.list_voices() if hasattr(sp, "list_voices") else [])

    @Slot(str)
    def test_voice(self, lang):
        if lang == "ur":
            self.app.speaker.say("السلام علیکم ولی! میں رانی اے آئی ہوں۔ یہ میری آواز کا ٹیسٹ ہے۔", "ur", wait=False)
        else:
            self.app.speaker.say("Hello Wali, this is a test of my English voice.", "en", wait=False)

    @Slot()
    def test_greeting(self):
        threading.Thread(target=lambda: self.app.greet_if_needed(force=True, deadline_s=10), daemon=True).start()

    # ---- memory / history
    @Slot(result=str)
    def memories(self):
        return json.dumps(self.app.store.list_memories(), ensure_ascii=False)

    @Slot(str, result=str)
    def add_memory(self, text):
        return json.dumps({"id": self.app.store.add_memory(text)})

    @Slot(int, str, result=str)
    def update_memory(self, mid, text):
        return json.dumps({"ok": self.app.store.update_memory(mid, text)})

    @Slot(int, result=str)
    def delete_memory(self, mid):
        return json.dumps({"ok": self.app.store.delete_memory(mid)})

    @Slot(result=str)
    def history(self):
        return json.dumps(self.app.store.recent_history(100), ensure_ascii=False)

    @Slot(result=str)
    def clear_history(self):
        self.app.store.clear_history()
        return "{}"

    @Slot(result=str)
    def test_ai(self):
        self.app.brain.reset()
        reply = self.app.brain.ask('Reply with JSON {"display":"ok","speech":"ok","tool":null}', [], "ping")
        if reply is None:
            return json.dumps({"ok": False, "error": "; ".join(self.app.brain.last_errors) or "no provider"})
        return json.dumps({"ok": True, "provider": self.app.brain.last_provider, "reply": reply["display"][:80]})

    @Slot(result=str)
    def diagnostics(self):
        from .doctor import run_checks
        return json.dumps(run_checks(self.app, online=True), ensure_ascii=False)


class HudWindow(QWebEngineView):
    def __init__(self, app: RaniApp):
        super().__init__()
        self.rani = app
        # WindowDoesNotAcceptFocus: the orb has no text box, so it must never steal the keyboard focus from the
        # window you are working in (and "minimize"/"type" must never hit RANI's own window).
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.NoDropShadowWindowHint |
                            Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setStyleSheet("background: transparent;")
        self.page().setBackgroundColor(Qt.transparent)
        self.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        self.bridge = Bridge(app, self)
        self.channel = QWebChannel(self.page())
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)
        self.load(QUrl.fromLocalFile(str(HUD_DIR / "index.html")))
        self._settings_view: QWebEngineView | None = None
        self.set_compact(app.compact, save=False)

    def place(self):
        geo = QApplication.primaryScreen().availableGeometry()
        m = max(0, min(200, int(self.rani.settings.get("hud_margin"))))
        self.move(QPoint(geo.right() - self.width() - m + 1, geo.top() + m))   # top-right corner

    def set_compact(self, compact: bool, save=True):
        self.rani.compact = compact
        if compact:
            self.setFixedSize(COMPACT)
        else:
            w = max(220, min(900, int(self.rani.settings.get("hud_width"))))
            h = max(220, min(900, int(self.rani.settings.get("hud_height"))))
            self.setFixedSize(w, h)
        self.place()
        if save:
            self.rani.settings.update({"start_compact": compact})

    def open_settings(self):
        if self._settings_view is None:
            v = QWebEngineView()
            v.setWindowTitle("RANI AI - Settings")
            v.setWindowIcon(make_icon())
            v.resize(1000, 700)
            v.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            ch = QWebChannel(v.page())
            ch.registerObject("bridge", self.bridge)
            v.page().setWebChannel(ch)
            v._ch = ch
            v.load(QUrl.fromLocalFile(str(HUD_DIR / "settings.html")))
            self._settings_view = v
        self._settings_view.show()
        self._settings_view.raise_()
        self._settings_view.activateWindow()


def run(app: RaniApp, speaker_ready_cb=None, force_greet=False, no_startup=False) -> int:
    from .startup import ControlServer
    qapp = QApplication.instance() or QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setApplicationName("RANI AI")

    holder: dict = {}

    def on_cmd(cmd):
        if cmd == "quit":
            QTimer.singleShot(0, lambda: (app.shutdown(), qapp.quit()))
        elif cmd == "show" and holder.get("hud") is not None:
            QTimer.singleShot(0, holder["hud"].show)
    try:                                   # claim the single-instance lock BEFORE any window appears
        ctl = ControlServer(on_cmd)
    except OSError:
        print("RANI is already running.")
        return 0
    hud = HudWindow(app)
    holder["hud"] = hud
    hud.show()

    tray = QSystemTrayIcon(make_icon(), qapp)
    tray.setToolTip("RANI AI")
    menu = QMenu()
    act = lambda text, fn: (lambda a: (a.triggered.connect(fn), menu.addAction(a)))(QAction(text, menu))  # noqa: E731
    act("Talk to RANI (Ctrl+Alt+Space)", app.push_to_talk)
    act("Emergency stop", app.emergency_stop)
    act("Show / hide HUD", lambda: hud.setVisible(not hud.isVisible()))
    act("Compact / full", lambda: hud.set_compact(not app.compact))
    act("Settings", hud.open_settings)
    menu.addSeparator()
    act("Quit RANI", lambda: (app.shutdown(), qapp.quit()))
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: hud.open_settings() if r == QSystemTrayIcon.DoubleClick else None)
    tray.show()

    def _warm_offline_ai():
        try:
            from . import localai
            if localai.find_ollama():
                localai.remove_gui_autostart()
                localai.ensure_running(str(app.settings.get("ollama_url")), wait=15)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_warm_offline_ai, daemon=True, name="rani-ollama-warm").start()

    _install_hotkeys(app)
    threading.Thread(target=app.wake_loop, daemon=True, name="rani-wake").start()
    threading.Thread(target=lambda: app.startup_sequence(delay=not no_startup, force_greet=force_greet),
                     daemon=True, name="rani-startup").start()
    return qapp.exec()


def _install_hotkeys(app: RaniApp):
    try:
        import keyboard
        s = app.settings
        keyboard.add_hotkey(s.get("hotkey_push_to_talk"), app.push_to_talk)
        keyboard.add_hotkey(s.get("hotkey_emergency_stop"), app.emergency_stop)
    except Exception as e:  # noqa: BLE001 - hotkeys are optional; HUD button/tray still work
        app.hotkey_error = str(e)
