# Double-click / Windows-startup launcher (no console window). Works from any working directory.
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
try:
    from rani.__main__ import main
    sys.exit(main())
except SystemExit:
    raise
except Exception:                                   # no console under pythonw: write a log instead
    import traceback
    log = os.path.join(os.environ.get("APPDATA", ROOT), "RANI", "crash.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        traceback.print_exc(file=f)
    raise
