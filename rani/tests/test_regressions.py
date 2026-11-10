"""Regression tests: one test per real bug found during the full debug pass."""
import ast
import os
import threading
import time
from pathlib import Path

import pytest

from rani import phrases
from rani.actions import ALLOWED_HOTKEYS, CONFIRM_KEYS
from rani.brain import _extract_json, normalize_reply
from rani.intents import detect_lang, parse
from rani.store import Store
from rani.winapi import WindowsBackend

from .conftest import ScriptedProvider, drain

WAKE = ["rani"]


# ------------------------------------------------------------------ intents
@pytest.mark.parametrize("text,url", [
    ("open example.com", "https://example.com"),
    ("open wikipedia.org", "https://wikipedia.org"),
    ("open https://example.com/a?b=1", "https://example.com/a?b=1"),
    ("visit www.python.org/downloads.", "https://www.python.org/downloads"),
])
def test_urls_survive_normalisation(text, url):
    i = parse(text, WAKE)
    assert i.action == "open_url" and i.args["url"] == url


@pytest.mark.parametrize("text", [
    "PowerPoint slide kholo", "open the slide deck", "this is valid",
])
def test_word_lid_is_a_whole_word(text):
    i = parse(text, WAKE)
    assert i is None or i.action != "set_lid_action"


@pytest.mark.parametrize("text", [
    "chrome restart karo", "I can't sleep, show me sleep tips", "also jao",
    "show me the weather in karachi", "write me a poem about the sea",
    "music chalao", "what do I do to save this", "homework folder ka matlab batao",
])
def test_ambiguous_sentences_do_not_trigger_actions(text):
    i = parse(text, WAKE)
    assert i is None or i.action not in ("restart", "sleep", "open_app", "type_text", "open_path", "hotkey")


def test_show_desktop_is_a_hotkey_not_a_folder():
    assert parse("show desktop", WAKE).args == {"keys": "win+d"}
    assert parse("desktop dikhao", WAKE).action == "hotkey"
    assert parse("desktop folder kholo", WAKE).action == "open_path"


def test_typing_keeps_case_and_drops_the_command_word():
    assert parse("Type Hello World", WAKE).args["text"] == "Hello World"


def test_reminder_time_ignores_stray_numbers():
    i = parse("task 2 remind me at 5 pm call mom", WAKE)
    assert i.action == "set_reminder" and "call mom" in i.args["text"]


def test_task_and_memory_keep_the_users_words():
    assert parse("add task buy a gift for mom", WAKE).args["text"] == "buy a gift for mom"
    assert parse("Yaad rakho meri car Honda hai", WAKE).args["text"] == "meri car Honda hai"


def test_english_do_is_not_urdu():
    assert detect_lang("do you know what time it is") == "en"


# ------------------------------------------------------------------ actions
def _confirmed(reg, name, args):
    r = reg.execute(name, args)
    assert r.needs_confirmation
    return reg.confirm(r.token)


def test_open_path_never_launches_programs(reg, backend, home):
    exe = backend.root / "Downloads" / "evil.exe"
    exe.write_bytes(b"MZ")
    r = reg.execute("open_path", {"name": str(exe)})
    assert r.key == "path_blocked" and not any(c[0] == "open_path" for c in backend.calls)
    doc = backend.root / "Downloads" / "ok.txt"
    doc.write_text("hi")
    assert reg.execute("open_path", {"name": str(doc)}).ok


def test_main_user_folders_cannot_be_renamed_or_moved(reg, backend):
    docs = backend.root / "Documents"
    assert _confirmed(reg, "rename_path", {"path": str(docs), "new_name": "x"}).key == "path_blocked"
    assert _confirmed(reg, "move_path", {"path": str(docs), "dest_folder": "Desktop"}).key == "path_blocked"
    assert docs.exists()


def test_reserved_windows_names_rejected(reg):
    assert not reg.execute("create_folder", {"name": "con"}).ok
    assert not reg.execute("create_folder", {"name": "NUL.txt"}).ok


def test_infinity_is_bad_args_not_a_crash(reg):
    assert reg.execute("set_volume", {"level": float("inf")}).key == "bad_args"
    assert reg.execute("set_volume", {"level": float("nan")}).key == "bad_args"


def test_mistyped_permission_means_ask_not_allow(reg, settings):
    settings.data["permissions"]["system"] = "alow"
    assert reg.execute("set_volume", {"level": 10}).needs_confirmation


def test_bad_lid_power_and_window_op_are_rejected(reg, backend):
    assert _confirmed(reg, "set_lid_action", {"mode": "nothing", "power": "bogus"}).key == "bad_args"
    assert reg.execute("window_control", {"op": "close"}).key == "bad_args"


def test_never_minimise_rani_itself(reg, backend, monkeypatch):
    monkeypatch.setattr(backend, "window_pid", lambda h: os.getpid())
    assert reg.execute("window_control", {"op": "minimize"}).key == "window_none"


def test_timer_wording(reg):
    r = reg.execute("set_timer", {"seconds": 30})
    assert "30 sec" in phrases.render(r.key, "ur", **r.args)[0] and "minute" not in phrases.render(r.key, "ur", **r.args)[0]
    r = reg.execute("set_timer", {"seconds": 300})
    assert r.args["dur"] == "5 min" and "5 منٹ" in phrases.render(r.key, "ur", **r.args)[1]


def test_reminder_in_the_far_past_or_future_rejected(reg):
    assert reg.execute("set_reminder", {"text": "x", "due": 1000.0}).key == "bad_args"
    assert reg.execute("set_reminder", {"text": "x", "due": time.time() + 9e8}).key == "bad_args"


def test_shutdown_grace_is_clamped(reg, backend, settings):
    settings.data["shutdown_grace_sec"] = 0
    _confirmed(reg, "shutdown", {})
    assert backend.power_scheduled[0] >= 10


def test_every_phrase_key_used_by_actions_exists():
    tree = ast.parse((Path(__file__).parents[1] / "actions.py").read_text(encoding="utf-8"))
    keys = set(CONFIRM_KEYS.values())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Result" and len(node.args) >= 2:
            keys |= {n.value for n in ast.walk(node.args[1]) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    missing = sorted(k for k in keys if k not in phrases.P["ur"] and k not in ("unknown_action",))
    assert not missing, missing


# ------------------------------------------------------------------ backend (pure logic, runs on any OS)
def test_every_allowed_hotkey_can_be_sent():
    for combo in ALLOWED_HOTKEYS:
        for part in combo.split("+"):
            assert part in WindowsBackend._VK or (len(part) == 1 and part.isalnum()), combo


def test_brightness_uses_invoke_cimmethod(monkeypatch):
    from rani import winapi
    seen = []
    monkeypatch.setattr(winapi, "_ps", lambda s, timeout=20: seen.append(s) or "")
    monkeypatch.setattr(winapi, "IS_WIN", True)
    WindowsBackend().set_brightness(50)
    assert "Invoke-CimMethod" in seen[0] and "Brightness=[byte]50" in seen[0]


# ------------------------------------------------------------------ brain
def test_non_dict_and_cut_off_ai_replies():
    assert normalize_reply(_extract_json('["a","b"]'))["tool"] is None
    assert normalize_reply(_extract_json('"hello"'))["display"] == "hello"
    cut = _extract_json('{"display": "Jee Wali, abhi karti hoon", "speech": "جی ولی، ابھی کر')
    assert cut["display"] == "Jee Wali, abhi karti hoon" and "{" not in cut["speech"]


def test_gemini_flash_thinking_disabled(settings, monkeypatch):
    import requests
    from rani.brain import GeminiProvider
    seen = {}

    class R:
        status_code = 200
        def json(self): return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

    monkeypatch.setattr(requests, "post", lambda url, **kw: seen.update(kw) or R())
    monkeypatch.setenv("GEMINI_API_KEY", "K")
    GeminiProvider().chat(settings, "s", [], "hi")
    gen = seen["json"]["generationConfig"]
    assert gen["thinkingConfig"] == {"thinkingBudget": 0} and gen["maxOutputTokens"] >= 1000


# ------------------------------------------------------------------ app / voice / store / config
def test_settings_bool_is_not_an_int(settings):
    settings.update({"autostart": 1, "greeting_enabled": 0})
    assert settings.get("autostart") is False and settings.get("greeting_enabled") is True


def test_env_file_with_bom(home, monkeypatch):
    from rani import config
    (config.app_dir() / ".env").write_bytes("\ufeffRANI_TEST_KEY=abc\n".encode("utf-8"))
    monkeypatch.delenv("RANI_TEST_KEY", raising=False)
    config._load_env_files()
    assert os.environ.get("RANI_TEST_KEY") == "abc"
    monkeypatch.delenv("RANI_TEST_KEY", raising=False)


def test_store_prune(home):
    s = Store(home / "p.db")
    for i in range(30):
        s.add_chat("user", str(i))
    s.prune(keep_chat=10)
    assert len(s._run("SELECT * FROM chat", fetch=True)) == 10


def test_hud_state_stays_speaking_while_voice_is_loading(make_app):
    app = make_app()
    app.speaker.busy = True
    app.set_state("speaking")
    assert app.snapshot()["state"] == "speaking"
    app.speaker.busy = False
    assert app.snapshot()["state"] == "idle"


def test_ai_history_never_starts_with_assistant(make_app):
    seen = {}
    p = ScriptedProvider("fake", reply=lambda u: '{"display":"ok","speech":"ok","tool":null}')
    app = make_app([p])
    app.store.add_chat("assistant", "old greeting")
    orig = app.brain.ask
    app.brain.ask = lambda system, history, user: seen.update(h=history) or orig(system, history, user)
    app.submit("tell me a story about dragons")
    drain(app)
    assert not seen["h"] or seen["h"][0]["role"] == "user"


def test_speaker_stop_releases_waiting_callers(settings, monkeypatch):
    from rani.voice import Speaker
    gate = threading.Event()
    sp = Speaker(settings)
    monkeypatch.setattr(sp, "_speak_one", lambda *a, **k: gate.wait(5) and False)
    sp.say("one", wait=False)
    time.sleep(0.2)
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", sp.say("two", wait=True)))
    t.start()
    time.sleep(0.2)
    assert sp.busy
    sp.stop()
    t.join(2)
    assert not t.is_alive() and out["r"] is False
    gate.set()
    time.sleep(0.4)
    assert not sp.busy


# ------------------------------------------------------------------ AI chain: limits, offline, Ollama last
OK = '{"display":"ok","speech":"ok","tool":null}'


def _brain(settings, *providers, order=None):
    from rani.brain import Brain
    settings.data["providers_order"] = order or [p.name for p in providers]
    return Brain(settings, list(providers))


def test_limit_moves_to_next_provider_and_remembers(settings):
    from rani.brain import ProviderError
    gem = ScriptedProvider("gemini", fail=ProviderError("429 quota", "limit"))
    grok = ScriptedProvider("grok", reply=OK)
    b = _brain(settings, gem, grok)
    assert b.ask("s", [], "hi")["display"] == "ok" and b.last_provider == "grok"
    assert gem.calls == 1
    b.ask("s", [], "again")                                  # Gemini is cooling down: not even tried
    assert "cooling down" in b.last_errors[0] and gem.calls == 1
    b.reset()
    b.ask("s", [], "after reset")
    assert gem.calls == 2


def test_no_internet_skips_all_cloud_and_uses_ollama(settings):
    import requests
    class Local(ScriptedProvider):
        cloud = False
    gem = ScriptedProvider("gemini", fail=requests.ConnectionError("offline"))
    grok = ScriptedProvider("grok", reply=OK)
    oll = Local("ollama", reply=OK)
    b = _brain(settings, gem, grok, oll, order=["gemini", "grok", "ollama"])
    assert b.ask("s", [], "hi")["display"] == "ok"
    assert b.last_provider == "ollama"
    assert any("no internet" in e for e in b.last_errors)     # grok was skipped instantly, not waited for


def test_ollama_is_always_the_last_resort(settings):
    from rani.brain import Brain
    settings.data["providers_order"] = ["ollama", "gemini"]
    assert [p.name for p in Brain(settings).order()] == ["gemini", "ollama"]


def test_default_order_and_old_settings_are_upgraded(home):
    from rani.config import Settings, DEFAULTS
    assert DEFAULTS["providers_order"] == ["gemini", "grok", "groq", "openrouter", "openai_compat", "ollama"]
    p = home / "old.json"
    p.write_text('{"providers_order": ["gemini", "ollama", "openai_compat"]}')
    assert Settings(p).data["providers_order"] == DEFAULTS["providers_order"]


def test_http_errors_are_classified():
    from rani.brain import classify_http
    assert classify_http(429, "") == "limit"
    assert classify_http(400, "RESOURCE_EXHAUSTED: You exceeded your current quota") == "limit"
    assert classify_http(400, "API key not valid. Please pass a valid API key.") == "auth"
    assert classify_http(401, "") == "auth" and classify_http(500, "boom") == "other"


def test_grok_groq_openrouter_use_their_own_keys_and_urls(settings, monkeypatch):
    import requests
    from rani.brain import GrokProvider, GroqProvider, OpenRouterProvider
    seen = []

    class R:
        status_code = 200
        def json(self): return {"choices": [{"message": {"content": "{}"}}]}
    monkeypatch.setattr(requests, "post", lambda url, **kw: seen.append((url, kw["headers"]["Authorization"], kw["json"]["model"])) or R())
    for cls, env in ((GrokProvider, "XAI_API_KEY"), (GroqProvider, "GROQ_API_KEY"), (OpenRouterProvider, "OPENROUTER_API_KEY")):
        monkeypatch.setenv(env, "KEY-" + env)
        p = cls()
        assert p.available(settings)
        p.chat(settings, "s", [], "hi")
    assert seen[0][0] == "https://api.x.ai/v1/chat/completions" and seen[0][1] == "Bearer KEY-XAI_API_KEY"
    assert seen[1][0].startswith("https://api.groq.com/openai/v1/") and seen[2][0].startswith("https://openrouter.ai/api/v1/")
    assert all(m for _, _, m in seen)


def test_localai_model_matching_and_setup_without_windows(monkeypatch, settings):
    from rani import localai
    assert localai.model_in(["qwen2.5:3b"], "qwen2.5:3b") and localai.model_in(["llama3:latest"], "llama3")
    assert not localai.model_in(["qwen2.5:3b"], "qwen2.5:7b")
    monkeypatch.setattr(localai, "find_ollama", lambda: None)
    monkeypatch.setattr(localai, "IS_WIN", False)
    msgs = []
    assert localai.setup(settings, msgs.append) is False and any("NOT ready" in m for m in msgs)


def test_all_secret_names_have_a_provider_or_are_known():
    from rani.config import SECRET_NAMES
    assert {"GEMINI_API_KEY", "XAI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"} <= set(SECRET_NAMES)


def test_jarvis_is_gone():
    root = Path(__file__).parents[2]
    for name in ("jarviscli", "installer", "setup.bat", "README_JARVIS_ORIGINAL.md"):
        assert not (root / name).exists(), name


def test_ollama_gui_autostart_is_removed(tmp_path, monkeypatch):
    from rani import localai
    startup = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup.mkdir(parents=True)
    (startup / "Ollama.lnk").write_text("x")
    (startup / "Other.lnk").write_text("x")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(localai, "IS_WIN", True)
    assert localai.remove_gui_autostart() >= 1
    assert not (startup / "Ollama.lnk").exists() and (startup / "Other.lnk").exists()


def test_close_gui_never_touches_the_server_process(monkeypatch):
    import psutil
    from rani import localai
    killed = []

    class P:
        def __init__(self, name): self.info = {"name": name}; self.name = name
        def terminate(self): killed.append(self.name)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [P("ollama.exe"), P("ollama app.exe"), P("chrome.exe")])
    assert localai.close_gui() is True and killed == ["ollama app.exe"]
