"""Entry point:  python -m rani [options]"""
from __future__ import annotations

import argparse
import sys


def build_app(with_voice=True):
    from .app import RaniApp
    from .config import Settings
    s = Settings()
    if not with_voice:
        return RaniApp(settings=s)
    from .voice import Listener, Speaker
    holder = {}
    speaker = Speaker(s)
    listener = Listener(s, on_level=lambda v: holder["app"].__setattr__("mic_level", v))
    app = RaniApp(settings=s, speaker=speaker, listener=listener)
    holder["app"] = app
    return app


def cli_loop():
    """Text-only REPL (no window, no audio): handy to test commands on the real laptop."""
    app = build_app(with_voice=False)
    print("RANI AI text mode. Type a command (e.g. 'chrome kholo', 'battery batao'). Ctrl+C to quit.")
    while True:
        try:
            line = input("Wali> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        before = len(app.speaker.said)
        app.submit(line)
        import time
        time.sleep(0.3)
        while app._st["state"] in ("thinking", "executing") or not app._cmds.empty():
            time.sleep(0.1)
        time.sleep(0.5)
        for speech, lang in app.speaker.said[before:]:
            print("RANI>", app.snapshot()["reply"] or speech)
    app.shutdown()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rani", description="RANI AI - Wali Hasan's personal assistant")
    ap.add_argument("--startup", action="store_true", help="launched by Windows at login")
    ap.add_argument("--no-delay", action="store_true", help="skip the startup delay")
    ap.add_argument("--greet", action="store_true", help="force the welcome greeting now")
    ap.add_argument("--cli", action="store_true", help="text-only mode (no HUD, no audio)")
    ap.add_argument("--doctor", action="store_true", help="check the installation")
    ap.add_argument("--offline-doctor", action="store_true", help="doctor without network tests")
    ap.add_argument("--setup-ai", action="store_true", help="install Ollama + download the offline AI model")
    ap.add_argument("--stop", action="store_true", help="ask a running RANI to quit")
    ap.add_argument("--autostart", choices=["on", "off", "status"], help="manage start-with-Windows")
    a = ap.parse_args(argv)

    from . import startup
    if a.stop:
        r = startup.send_control("quit")
        print("RANI is stopping." if r == "ok" else "RANI is not running.")
        return 0
    if a.autostart:
        if a.autostart == "status":
            print("enabled" if startup.is_autostart_enabled() else "disabled")
            return 0
        ok = startup.set_autostart(a.autostart == "on")
        print(f"Autostart {a.autostart}: {'done' if ok else 'FAILED (Windows only)'}")
        if ok:
            from .config import Settings
            Settings().update({"autostart": a.autostart == "on"})
        return 0 if ok else 1
    if a.setup_ai:
        from . import localai
        from .config import Settings
        return 0 if localai.setup(Settings(), print) else 1
    if a.doctor or a.offline_doctor:
        from .doctor import print_report
        return print_report(online=not a.offline_doctor)
    if a.cli:
        cli_loop()
        return 0
    if startup.send_control("ping") == "ok":
        startup.send_control("show")
        print("RANI is already running.")
        return 0
    try:
        from .hud_window import run
    except ImportError as e:
        print("The HUD needs PySide6:", e, "\nRun install.bat first.")
        return 2
    app = build_app()
    return run(app, force_greet=a.greet, no_startup=a.no_delay or not a.startup)


if __name__ == "__main__":
    sys.exit(main())
