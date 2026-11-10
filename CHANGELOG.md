# Changelog

## 2.0.0 — RANI only (Jarvis removed) + multi-AI fallback + one-click install
- **Jarvis removed completely** (`jarviscli/`, its installer, docs, Makefile, CI files, icons). RANI is now 100% your own code; `LICENSE` is now MIT (c) Wali Hasan.
- **AI chain:** Gemini -> Grok (xAI) -> Groq -> OpenRouter -> your own OpenAI-compatible cloud -> **Ollama (offline, always last)**.
  - Limit reached (429 / quota) -> that provider is skipped for a while (backs off 5 min, 10 min, ... up to 1 h), next one is used.
  - No internet -> noticed after ONE failed try (4 s connect timeout); every other cloud provider is skipped instantly and Ollama answers.
  - Bad key -> skipped for 1 h; saving a new key or "Test AI connection" resets all cooldowns.
  - Old `settings.json` with the previous provider order is upgraded automatically.
- **Offline AI is automatic:** `rani/localai.py` installs Ollama (winget, else the official installer), starts it when needed, downloads the model once;
  `python -m rani --setup-ai`. Ollama keeps the model warm for 30 min (fast replies).
- **install.bat is one click:** installs Python 3.12 itself if missing and continues in the same window, installs packages, offline AI, autostart, and starts RANI (each question auto-answers Yes after 15 s).
- Settings -> AI Brain has key fields for Gemini, Grok, Groq, OpenRouter and custom cloud; `.env.example` updated.
- The Ollama desktop window that its installer opens is closed automatically, and Ollama's "start at login" entry is removed (RANI starts the headless server itself).
- 11 new tests (119 total). All commands, voice and HUD behaviour are unchanged.

## 1.1.0 — full debug pass
**Fixed (found by reading every module + running probes; 41 regression tests added in `rani/tests/test_regressions.py`)**
- `open example.com` / `open https://x.com/a?b=1`: URLs were destroyed by text normalisation → now opened correctly.
- Saying "slide", "valid"… triggered the *lid-close setting* (substring match on "lid") → whole-word match.
- "chrome restart karo" asked to restart the laptop; "I can't sleep…" put the laptop to sleep; "show me the weather…" tried to open an app named "weather";
  "write me a poem" typed into the focused window; "music chalao" opened the Music folder; "show desktop" opened the Desktop folder instead of Win+D.
- `Type Hello` typed the word "Type" too (case-sensitive prefix).
- Reminders with another number in the sentence ("task 2 … at 5 pm") were not understood; tasks lost small words; memory lost capitals.
- Allowed hotkeys `alt+left`, `alt+right`, `f5`, `ctrl+plus`, `ctrl+minus` **always failed** (missing key codes).
- Brightness could not be set (`Get-CimInstance` objects have no `WmiSetBrightness`; now `Invoke-CimMethod`).
- "Sleep" spoke its goodbye only *after* the PC woke up (call blocks until resume) → deferred 3 s.
- AI-proposed memory showed "Kuch masla aa gaya" (missing phrase `confirm_memory_add`).
- Timer said "30 sec minute ka timer".
- `.env` saved by Notepad (BOM) silently ignored the first key.
- Gemini 2.5-flash "thinking" ate the token budget → cut-off/empty Urdu answers; JSON replies that were a list/string crashed the command.
- HUD flickered to idle while the voice was downloading, and RANI could listen to her own voice → new `Speaker.busy`.
- `Speaker.stop()` left `wait=True` callers hanging up to 120 s.
- Microphone was never calibrated for room noise.
- Second RANI instance could crash with a traceback; HUD could steal keyboard focus and "minimize" could hit RANI itself.
- Crashed command left HUD stuck in "error"; reminders could overwrite the "thinking" state.
- Chat/history database grew forever; Windows login check scanned usernames of all processes (slow).
- `jarviscli/plugins/colorconverter.py`: stray `Ò` character = SyntaxError.

**Security hardening**
- `open_path` can no longer launch `.exe/.bat/.ps1/.lnk…`; main user folders cannot be renamed/moved; reserved Windows names (CON, NUL…) rejected.
- Mistyped permission value now means *ask* (was silently *allow*); `inf`/`NaN` arguments are rejected; shutdown grace is clamped to ≥10 s;
  emergency stop now also interrupts typing.

**Install**
- Removed the non-existent `PySide6-WebEngine` requirement (PySide6 already ships WebEngine); `edge-tts>=6.1.12` (needed for current Microsoft voice service); edge-tts 7.x word timing supported.
