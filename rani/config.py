"""Settings, paths and secret handling.

API keys are NEVER written to settings.json and are never sent to the HUD
(JavaScript) side.  They live in Windows Credential Manager (via `keyring`)
or in environment variables / a local .env file.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import threading
from pathlib import Path

IS_WIN = sys.platform == "win32"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    override = os.environ.get("RANI_HOME")
    if override:
        p = Path(override)
    elif IS_WIN:
        p = Path(os.environ.get("APPDATA", str(Path.home()))) / "RANI"
    else:
        p = Path.home() / ".rani"
    p.mkdir(parents=True, exist_ok=True)
    return p


DEFAULTS: dict = {
    "owner_name": "Wali Hasan",
    "owner_short": "Wali",
    "assistant_name": "RANI AI",
    # ---- startup / greeting
    "autostart": False,
    "greeting_enabled": True,
    "greeting_volume": 0.9,
    "greeting_id": "default",          # key of GREETINGS below, or "custom"
    "greeting_custom": "",
    "startup_delay_sec": 8,
    "start_compact": False,            # start as small floating orb only
    # ---- voice
    "voice_ur": "ur-PK-UzmaNeural",
    "voice_en": "en-IN-NeerjaNeural",
    "speech_rate": 0,                  # percent, -50 .. +50
    "volume": 0.9,                     # RANI's own speaking volume 0..1
    "listen_mode": "push",             # push (hotkey/click) | wake (background, online STT) | off
    "wake_words": ["rani", "ranee", "rany", "رانی"],
    "stt_languages": ["ur-PK", "en-US"],
    "hotkey_push_to_talk": "ctrl+alt+space",
    "hotkey_emergency_stop": "ctrl+alt+x",
    # ---- brain
    # best cloud first; when a limit finishes or the internet is off, RANI moves on; Ollama (offline) is the last resort
    "providers_order": ["gemini", "grok", "groq", "openrouter", "openai_compat", "ollama"],
    "gemini_model": "gemini-2.5-flash",
    "grok_model": "grok-3-mini",                 # xAI Grok  (key: XAI_API_KEY)
    "groq_model": "llama-3.3-70b-versatile",     # Groq Cloud (key: GROQ_API_KEY)
    "openrouter_model": "meta-llama/llama-3.3-70b-instruct:free",
    "ollama_model": "qwen2.5:3b",
    "ollama_url": "http://127.0.0.1:11434",
    "openai_base_url": "",
    "openai_model": "",
    "history_turns": 8,
    # ---- permissions: allow | ask | deny
    "permissions": {
        "apps": "allow", "system": "allow", "power": "allow", "files": "allow",
        "input": "ask", "keys": "allow", "browser": "allow", "productivity": "allow",
        "memory": "allow", "network": "ask",
    },
    "confirm_sleep": False,
    "shutdown_grace_sec": 30,
    # ---- HUD
    "hud_width": 380,
    "hud_height": 440,
    "hud_margin": 16,
}

# (roman text shown on HUD, urdu-script text that the Urdu voice reads)
GREETINGS: dict[str, tuple[str, str]] = {
    "default": (
        "Assalam-o-Alaikum! Kaisa hain Wali? Aapki RANI AI hazir hai. "
        "Bataiye, aaj main aapki kya madad kar sakti hoon?",
        "السلام علیکم! کیسے ہیں ولی؟ آپ کی رانی اے آئی حاضر ہے۔ "
        "بتائیے، آج میں آپ کی کیا مدد کر سکتی ہوں؟",
    ),
    "short": (
        "Assalam-o-Alaikum Wali! RANI hazir hai.",
        "السلام علیکم ولی! رانی حاضر ہے۔",
    ),
    "english": (
        "Hello Wali! RANI AI is ready. How can I help you today?",
        "Hello Wali! RANI AI is ready. How can I help you today?",
    ),
}

_lock = threading.RLock()


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or (app_dir() / "settings.json")
        self.data: dict = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        with _lock:
            if self.path.exists():
                try:
                    saved = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    saved = {}
                self._merge(self.data, saved)
            if self.data["providers_order"] in (["gemini", "ollama", "openai_compat"], ["gemini", "ollama"]):
                self.data["providers_order"] = list(DEFAULTS["providers_order"])     # upgrade from v1.0 / v1.1

    @staticmethod
    def _merge(base: dict, new: dict) -> None:
        for k, v in new.items():
            if k not in base:
                continue                      # ignore unknown keys
            if isinstance(base[k], dict) and isinstance(v, dict):
                Settings._merge(base[k], v)
            elif isinstance(base[k], bool):
                if isinstance(v, bool):
                    base[k] = v
            elif isinstance(base[k], type(v)) or (
                    isinstance(base[k], (int, float)) and isinstance(v, (int, float))
                    and not isinstance(v, bool)):
                base[k] = v

    def save(self) -> None:
        with _lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, self.path)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting: {key}")
        with _lock:
            self.data[key] = value
            self.save()

    def update(self, values: dict) -> None:
        with _lock:
            self._merge(self.data, values)
            self.save()

    def permission(self, category: str) -> str:
        value = str(self.data["permissions"].get(category, "ask")).strip().lower()
        return value if value in ("allow", "ask", "deny") else "ask"      # typo in settings.json -> safest option

    def greeting_texts(self) -> tuple[str, str]:
        gid = self.data["greeting_id"]
        if gid == "custom" and self.data["greeting_custom"].strip():
            t = self.data["greeting_custom"].strip()
            return t, t
        return GREETINGS.get(gid, GREETINGS["default"])


# ----------------------------------------------------------------- secrets
SECRET_NAMES = ("GEMINI_API_KEY", "XAI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "OPENAI_COMPAT_API_KEY")
_SERVICE = "RANI-AI"


def _load_env_files() -> None:
    for p in (PROJECT_ROOT / ".env", app_dir() / ".env"):
        try:
            for line in p.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except OSError:
            pass


_load_env_files()


def get_secret(name: str) -> str:
    try:
        import keyring
        v = keyring.get_password(_SERVICE, name)
        if v:
            return v
    except Exception:
        pass
    return os.environ.get(name, "")


def set_secret(name: str, value: str) -> bool:
    """Store in Windows Credential Manager. Returns False if keyring missing."""
    if name not in SECRET_NAMES:
        raise KeyError(name)
    try:
        import keyring
        if value:
            keyring.set_password(_SERVICE, name, value)
        else:
            try:
                keyring.delete_password(_SERVICE, name)
            except Exception:
                pass
        return True
    except Exception:
        return False


def has_secret(name: str) -> bool:
    return bool(get_secret(name))
