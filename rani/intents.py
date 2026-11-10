"""Deterministic, offline intent parser for English, Roman Urdu and Urdu script.

Fast path that runs BEFORE any AI call: it is predictable, free, works offline and keeps
common commands snappy.  Anything it does not recognise returns None and goes to the AI brain.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import apps as appcat

EASTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

NUM_WORDS = {
    "ek": 1, "one": 1, "teen": 3, "three": 3, "char": 4, "four": 4, "panch": 5, "paanch": 5, "five": 5,
    "chhe": 6, "che": 6, "six": 6, "saat": 7, "seven": 7, "aath": 8, "eight": 8, "nau": 9, "nine": 9,
    "das": 10, "ten": 10, "bees": 20, "twenty": 20, "tees": 30, "thirty": 30, "chalis": 40, "forty": 40,
    "pachas": 50, "fifty": 50, "saath": 60, "sixty": 60, "sattar": 70, "seventy": 70, "assi": 80,
    "eighty": 80, "nabbe": 90, "ninety": 90, "sau": 100, "hundred": 100, "half": 50, "aadha": 50,
    "ایک": 1, "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "دس": 10, "بیس": 20, "تیس": 30, "چالیس": 40,
    "پچاس": 50, "ساٹھ": 60, "ستر": 70, "اسی": 80, "نوے": 90, "سو": 100,
}

ROMAN_HINTS = {
    "kholo", "khol", "karo", "kar", "band", "mujhe", "batao", "bata", "hai", "ka", "ki", "ko",
    "par", "pe", "se", "aur", "nahi", "haan", "han", "kya", "zara", "chalao", "dikhao", "lagao", "banao",
    "kitna", "kitni", "mera", "meri", "mere", "aaj", "abhi", "jao", "rakho", "dhundo", "likho", "kholiye",
    "baad", "mein", "awaaz", "awaz", "roshni", "kijiye", "dijiye", "chahiye", "kaisa", "kaise",
}


@dataclass
class Intent:
    action: str                       # registered action name, or "chat:<key>" / "control:<x>"
    args: dict = field(default_factory=dict)
    lang: str = "ur"


def normalize(text: str) -> str:
    t = text.translate(EASTERN_DIGITS).lower().strip()
    t = re.sub(r"[،۔!?؟,;:\"“”«»()\[\]{}]", " ", t)
    t = re.sub(r"(?<!\d)\.(?!\d)", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def detect_lang(text: str) -> str:
    if re.search(r"[\u0600-\u06FF]", text):
        return "ur"
    words = set(normalize(text).split())
    return "ur" if words & ROMAN_HINTS else "en"


def strip_wake(text: str, wake_words) -> tuple[bool, str]:
    """Remove a leading/embedded wake word. Returns (had_wake_word, remaining_text)."""
    t = normalize(text)
    words = t.split()
    ww = {w.lower() for w in wake_words}
    for i, w in enumerate(words):
        if w in ww and i <= 2:
            return True, " ".join(words[:i] + words[i + 1:]).strip()
    return False, t


YES = {"haan", "han", "haa", "ha", "ji", "jee", "yes", "yeah", "yep", "ok", "okay", "theek", "thik",
       "sure", "confirm", "kardo", "kar", "bilkul", "ہاں", "جی", "ٹھیک"}
NO = {"nahi", "nahin", "no", "nope", "cancel", "mat", "naa", "na", "rehne", "rahne", "nahi", "نہیں", "نا",
      "منع"}


def is_yes(text: str) -> bool:
    w = set(normalize(text).split())
    return bool(w & YES) and not (w & NO)


def is_no(text: str) -> bool:
    w = set(normalize(text).split())
    return bool(w & NO)


def extract_number(text: str):
    m = re.search(r"\d+(?:\.\d+)?", text)
    if m:
        v = float(m.group())
        return int(v) if v == int(v) else v
    for w in text.split():
        if w in NUM_WORDS:
            return NUM_WORDS[w]
    return None


def _has(words: set, *opts) -> bool:
    return any(o in words for o in opts)


def _contains(t: str, *opts) -> bool:
    return any(o in t for o in opts)


OPEN_V = {"kholo", "khol", "kholdo", "kholiye", "kholen", "open", "launch", "start", "chalao", "chala",
          "run", "کھولو", "کھول", "اوپن", "چلاؤ", "چلا", "show", "dikhao"}
# verbs that clearly mean "open this" (so "music chalao" is NOT "open the Music folder")
STRICT_OPEN = OPEN_V - {"chalao", "chala", "start", "run", "چلاؤ", "چلا", "show", "dikhao"}
CLOSE_V = {"close", "band", "exit", "quit", "بند", "terminate"}

URL_RE = re.compile(
    r"(?<![\w@.\-])((?:https?://)?(?:www\.)?[a-z0-9][a-z0-9\-]*(?:\.[a-z0-9][a-z0-9\-]*)*\."
    r"(?:com|org|net|pk|io|edu|gov|co|app|dev|ai|info|me|tv)(?![a-z0-9\-])(?:[/?#]\S*)?)", re.I)
LAPTOP_W = {"laptop", "pc", "computer", "system", "لیپ", "لیپ ٹاپ", "کمپیوٹر", "windows", "machine"}

FILLER = {"please", "zara", "ji", "jee", "yaar", "mujhe", "meri", "mera", "mere", "ko", "ka", "ki", "ke",
          "kar", "karo", "do", "dena", "dijiye", "kijiye", "de", "plz", "pls", "can", "you", "could", "the",
          "a", "to", "me", "for", "par", "pe", "per", "mein", "main", "ab", "abhi", "now"}


def _clean_phrase(t: str, drop: set) -> str:
    return " ".join(w for w in t.split() if w not in drop and w not in FILLER).strip()


def parse_when(t: str, now: float | None = None):
    """Parse 'in N minutes' / 'N minute baad' / 'at 5 pm' / '5 baje'. -> (due_ts, label) or None."""
    now = now or time.time()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(seconds|second|sec|minutes|minute|mins|mint|min|ghante|ghanta|ghanty|"
                  r"hours|hour|hr|منٹ|گھنٹے|گھنٹہ)\b", t)
    if m:
        n = float(m.group(1))
        unit = m.group(2)
        mult = 1 if unit.startswith("sec") else 3600 if unit in ("ghanta", "ghante", "ghanty", "hour", "hours", "hr", "گھنٹے", "گھنٹہ") else 60
        return now + n * mult, f"{m.group(1)} {unit} baad", m.group(0)
    for m in re.finditer(r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|baje|بجے)?", t):
        if not (m.group(3) or ":" in m.group(0)):
            continue                                   # a stray number like "task 2" - look at the next one
        hh, mm, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if ap == "pm" and hh < 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        if hh > 23 or mm > 59:
            continue
        base = datetime.fromtimestamp(now)
        due = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if due.timestamp() <= now:
            due += timedelta(days=1)
        return due.timestamp(), due.strftime("%I:%M %p"), m.group(0)
    return None


def parse(text: str, wake_words=("rani",)) -> Intent | None:
    lang = detect_lang(text)
    had_wake, t = strip_wake(text, wake_words)
    if not t:
        return Intent("control:wake", {}, lang) if had_wake else None
    words = set(t.split())
    num = extract_number(t)

    # 1. emergency stop ------------------------------------------------------------
    if len(t.split()) <= 4 and (_has(words, "stop", "ruko", "ruk", "bas", "رکو", "بس", "halt") or
                                 _contains(t, "emergency stop", "stop everything", "sab ruk")):
        if not _has(words, "shutdown", "restart", "timer", "music"):
            return Intent("control:emergency_stop", {}, lang)

    # 2. power --------------------------------------------------------------------
    is_power_target = bool(words & LAPTOP_W) or _contains(t, "shut down", "لیپ ٹاپ")
    # "chrome restart karo" is about Chrome, not the laptop
    app_only = bool(appcat.find_app_in_text(t)) and not is_power_target
    if _has(words, "cancel", "abort", "rok", "ruko", "روک") and _has(words, "shutdown", "restart", "reboot") \
            or _contains(t, "shutdown cancel", "restart cancel", "cancel shutdown", "cancel restart"):
        return Intent("cancel_power", {}, lang)
    if "lid" in words or _contains(t, "dhakkan", "ڈھکن"):          # whole word: "slide"/"valid" must not match
        if _has(words, "restore", "wapas", "purani", "revert", "reset", "default"):
            return Intent("restore_lid_action", {}, lang)
        return Intent("set_lid_action", {"mode": "nothing", "power": "both"}, lang)
    if not app_only and (_has(words, "shutdown") or _contains(t, "shut down", "شٹ ڈاؤن") or
                         (is_power_target and _has(words, "band") and not _has(words, "lock", "sleep", "restart"))):
        return Intent("shutdown", {}, lang)
    if not app_only and (_has(words, "restart", "reboot", "ری اسٹارٹ") or
                         _contains(t, "dobara start", "dobara chalao laptop")):
        return Intent("restart", {}, lang)
    # "sleep" must be about the laptop (or a very short command) - not "how can I sleep better?"
    if (_has(words, "sleep", "سلیپ") and (is_power_target or len(words) <= 4) and not app_only) or \
            re.search(r"\bso ja(?:o)?\b", t):
        return Intent("sleep", {}, lang)
    if _has(words, "lock", "لاک") and (is_power_target or len(words) <= 4):
        return Intent("lock", {}, lang)

    # 3. volume / brightness ------------------------------------------------------
    vol_word = _has(words, "volume", "awaaz", "awaz", "sound", "آواز") or _contains(t, "آواز")
    if _has(words, "unmute") or (_has(words, "mute", "میوٹ") and _has(words, "hatao", "off", "wapas", "on")) \
            or (vol_word and _has(words, "on") and not num):
        return Intent("set_mute", {"muted": False}, lang)
    if _has(words, "mute", "میوٹ") or (vol_word and _has(words, "band") and not num):
        return Intent("set_mute", {"muted": True}, lang)
    if vol_word or _has(words, "louder", "quieter"):
        if num is not None and not _has(words, "kam", "ghatao", "barhao", "badhao", "zyada", "up", "down"):
            return Intent("set_volume", {"level": max(0, min(100, int(num)))}, lang)
        if _has(words, "kam", "ghatao", "ghata", "down", "lower", "decrease", "quieter", "halka", "کم"):
            return Intent("change_volume", {"delta": -int(num or 10)}, lang)
        if _has(words, "zyada", "barhao", "badhao", "bara", "up", "raise", "increase", "louder", "tez", "زیادہ"):
            return Intent("change_volume", {"delta": int(num or 10)}, lang)
        if _has(words, "batao", "kitni", "kitna", "what", "level", "check"):
            return Intent("get_volume", {}, lang)
    if _has(words, "brightness", "roshni", "روشنی", "برائٹنس"):
        if num is not None and not _has(words, "kam", "barhao", "up", "down", "zyada"):
            return Intent("set_brightness", {"level": max(0, min(100, int(num)))}, lang)
        if _has(words, "kam", "ghatao", "down", "lower", "decrease", "کم"):
            return Intent("change_brightness", {"delta": -int(num or 10)}, lang)
        if _has(words, "zyada", "barhao", "badhao", "up", "increase", "raise", "زیادہ"):
            return Intent("change_brightness", {"delta": int(num or 10)}, lang)

    # 4. system info --------------------------------------------------------------
    if _has(words, "battery", "بیٹری") or _contains(t, "charge kitna", "charging"):
        return Intent("battery", {}, lang)
    if _has(words, "screenshot", "سکرین", "اسکرین") or _contains(t, "screen shot", "اسکرین شاٹ"):
        return Intent("screenshot", {}, lang)
    if _has(words, "cpu", "ram", "gpu", "performance") or _contains(t, "system status", "memory usage",
                                                                       "system info", "سی پی یو"):
        return Intent("system_stats", {}, lang)
    if _has(words, "wifi", "wi-fi", "وائی") or _contains(t, "wi fi"):
        return Intent("wifi_status", {}, lang)
    if _contains(t, "time kya", "kitne baje", "what time", "current time", "time batao", "وقت کیا"):
        return Intent("chat:time", {}, lang)
    if _contains(t, "date kya", "aaj ki date", "what date", "today's date", "tareekh", "what day", "aaj kya din"):
        return Intent("chat:date", {}, lang)
    if _contains(t, "tum kaun", "aap kaun", "who are you", "tumhara naam", "aapka naam", "your name"):
        return Intent("chat:who", {}, lang)

    # 5. timers / reminders / tasks / memory -------------------------------------
    if _has(words, "timer", "ٹائمر"):
        w = parse_when(t)
        if w:
            return Intent("set_timer", {"seconds": int(round(w[0] - time.time()))}, lang)
    if _contains(t, "remind", "yaad dila", "yaad dilana", "reminder", "یاد دلا"):
        w = parse_when(t)
        if w:
            drop = {"remind", "reminder", "yaad", "dila", "dilana", "dilao", "me", "set", "baad", "in", "at", "after"}
            what = _clean_phrase(t.replace(w[2], " "), drop | {"rani", "baje", "am", "pm"})
            return Intent("set_reminder", {"text": what or "reminder", "due": w[0], "label": w[1]}, lang)
    if _contains(t, "task add", "add task", "todo add", "task likho", "task banao", "ٹاسک"):
        what = " ".join(w for w in t.split() if w not in {"task", "add", "todo", "likho", "banao", "rani", "ٹاسک",
                                                          "karo", "kar", "do", "please"})
        if what:
            return Intent("add_task", {"text": what}, lang)
    if _contains(t, "meri tasks", "my tasks", "show tasks", "task list", "tasks batao", "pending tasks"):
        return Intent("list_tasks", {}, lang)
    m = re.match(r"^(?:yaad rakho|yaad rakhna|remember|remember that)\s+(.+)$", t)
    if m:
        keep = re.search(r"(?:yaad rakho|yaad rakhna|remember(?: that)?)[\s,:\-]+(.+?)[\s.!۔]*$", text, re.I | re.S)
        return Intent("memory_add", {"text": (keep.group(1).strip() if keep else m.group(1))}, lang)
    if _contains(t, "kya yaad hai", "what do you remember", "meri memories", "show memories", "tumhein kya yaad"):
        return Intent("memory_list", {}, lang)

    # 6. web ----------------------------------------------------------------------
    url = URL_RE.search(text)
    if url and (words & OPEN_V or _has(words, "website", "url", "site", "go", "visit")):
        u = url.group(1).rstrip(".,;:!?)\"'")
        return Intent("open_url", {"url": u if u.lower().startswith("http") else "https://" + u}, lang)
    for engine, keys in (("youtube", ("youtube", "یوٹیوب")), ("google", ("google", "گوگل"))):
        if any(k in words for k in keys) and _has(words, "search", "dhundo", "talash", "chalao", "play", "sunao",
                                                  "سرچ"):
            q = _clean_phrase(t, set(keys) | {"search", "dhundo", "talash", "chalao", "play", "sunao",
                                               "rani", "on", "in", "سرچ"})
            if q:
                return Intent("web_search", {"engine": engine, "query": q}, lang)
    if _has(words, "search", "سرچ") and len(words) > 1:
        q = _clean_phrase(t, {"search", "karo", "google", "rani", "for", "سرچ"})
        if q:
            return Intent("web_search", {"engine": "google", "query": q}, lang)
    for site, link in appcat.SITES.items():
        if f" {site} " in f" {t} " and (words & OPEN_V):
            return Intent("open_url", {"url": link}, lang)

    # 7. files / folders -----------------------------------------------------------
    if _contains(t, "show desktop", "desktop dikhao", "desktop dikha") and "folder" not in words:
        return Intent("hotkey", {"keys": "win+d"}, lang)
    for key, folder in appcat.KNOWN_FOLDERS.items():
        hit = (key in words) if key.isascii() else (key in t)
        if not hit:
            continue
        if key in ("home", "user") and "folder" not in words:
            continue
        if _has(words, "folder", "فولڈر") or words & STRICT_OPEN or (words & {"show", "dikhao"} and key not in ("home", "user")):
            return Intent("open_path", {"name": folder or "home"}, lang)
    if _contains(t, "folder banao", "create folder", "new folder", "make folder", "folder bana"):
        nm = _clean_phrase(t, {"folder", "banao", "create", "new", "make", "bana", "rani", "named", "naam"})
        if nm:
            return Intent("create_folder", {"name": nm, "parent": "desktop"}, lang)
    if _has(words, "dhundo", "dhoondo", "find", "ڈھونڈو") and not _has(words, "google", "youtube"):
        q = _clean_phrase(t, {"dhundo", "dhoondo", "find", "file", "files", "folder", "rani", "ڈھونڈو",
                              "search", "in", "downloads", "documents", "desktop", "mein", "main"})
        if q:
            return Intent("search_files", {"query": q}, lang)
    if _has(words, "python") and _has(words, "project") and _contains(t, "bana", "create", "make", "banao"):
        nm = re.search(r"(?:named|naam|name)\s+([a-z0-9_\-]+)", t)
        return Intent("create_python_project", {"name": nm.group(1) if nm else "rani_project"}, lang)

    # 8. keyboard shortcuts / typing / windows -----------------------------------
    m = re.match(r"^(?:type|likho)\s+(.+)$", t)
    if m:
        raw = re.sub(r"^\s*(?:rani\s+)?(?:type|likho)\s+", "", normalize_keep_case(text, wake_words), flags=re.I)
        return Intent("type_text", {"text": raw or m.group(1)}, lang)
    hk = {"copy": "ctrl+c", "paste": "ctrl+v", "undo": "ctrl+z", "save": "ctrl+s", "select all": "ctrl+a",
          "new tab": "ctrl+t", "next window": "alt+tab", "desktop dikhao": "win+d", "show desktop": "win+d"}
    for phrase, combo in hk.items():
        if len(words) <= 4 and phrase in t and (_has(words, "karo", "kar", "do", "please") or t == phrase or
                                                phrase in ("desktop dikhao", "show desktop", "next window", "new tab")):
            return Intent("hotkey", {"keys": combo}, lang)
    if _has(words, "minimize", "chhota", "minimise"):
        a = appcat.find_app_in_text(t)
        return Intent("window_control", {"op": "minimize", "app": a[0] if a else ""}, lang)
    if _has(words, "maximize", "maximise", "bara"):
        a = appcat.find_app_in_text(t)
        return Intent("window_control", {"op": "maximize", "app": a[0] if a else ""}, lang)
    if _has(words, "switch", "jao", "focus") or _contains(t, "par jao", "pe jao"):
        a = appcat.find_app_in_text(t)
        if a:
            return Intent("window_control", {"op": "focus", "app": a[0]}, lang)

    # 9. apps ----------------------------------------------------------------------
    found = appcat.find_app_in_text(t)
    if found and (words & CLOSE_V):
        return Intent("close_app", {"name": found[0]}, lang)
    if words & OPEN_V:
        if found:
            return Intent("open_app", {"name": found[0]}, lang)
        name = _clean_phrase(t, OPEN_V | {"app", "application", "rani", "software", "program"})
        if name and words & STRICT_OPEN and len(name.split()) <= 3:
            return Intent("open_app", {"name": name}, lang)
    if found and len(words) <= len(found[1].split()) + 1 and not words & CLOSE_V:
        return Intent("open_app", {"name": found[0]}, lang)
    return None


def normalize_keep_case(text: str, wake_words) -> str:
    """Remove wake word but keep original casing/Unicode (for dictation)."""
    words = text.strip().split()
    ww = {w.lower() for w in wake_words}
    out = [w for i, w in enumerate(words) if not (i <= 1 and re.sub(r"[^\w\u0600-\u06FF]", "", w.lower()) in ww)]
    return " ".join(out)
