import json
import re
import time

import pytest

from rani import phrases
from rani.actions import Ctx, Registry
from rani.brain import Brain, ProviderError, _extract_json, normalize_reply
from rani.config import DEFAULTS, Settings
from rani.intents import detect_lang, is_no, is_yes, parse
from rani.store import Store

from .conftest import FakeBackend, ScriptedProvider, drain

WAKE = ["rani"]


# ------------------------------------------------------------------ intents
@pytest.mark.parametrize("text,action,args", [
    ("RANI Chrome kholo", "open_app", {"name": "chrome"}),
    ("VS Code open karo", "open_app", {"name": "vscode"}),
    ("Volume 30 percent kar do", "set_volume", {"level": 30}),
    ("Mera laptop lock kar do", "lock", {}),
    ("Mujhe battery percentage batao", "battery", {}),
    ("Downloads folder kholo", "open_path", {"name": "Downloads"}),
    ("Screenshot lo", "screenshot", {}),
    ("Laptop restart kar do", "restart", {}),
    ("Laptop shutdown kar do", "shutdown", {}),
    ("RANI, laptop sleep kar do", "sleep", {}),
    ("awaaz kam karo", "change_volume", {"delta": -10}),
    ("volume barhao", "change_volume", {"delta": 10}),
    ("mute", "set_mute", {"muted": True}),
    ("unmute", "set_mute", {"muted": False}),
    ("brightness 50 kar do", "set_brightness", {"level": 50}),
    ("chrome band karo", "close_app", {"name": "chrome"}),
    ("minimize chrome", "window_control", {"op": "minimize", "app": "chrome"}),
    ("cancel shutdown", "cancel_power", {}),
    ("5 minute ka timer lagao", "set_timer", {"seconds": 300}),
    ("youtube par imran khan songs search karo", "web_search", {"engine": "youtube", "query": "imran khan songs"}),
    ("open github.com", "open_url", {"url": "https://github.com"}),
    ("کروم کھولو", "open_app", {"name": "chrome"}),
    ("آواز 40 کر دو", "set_volume", {"level": 40}),
    ("downloads mein resume dhundo", "search_files", {"query": "resume"}),
    ("yaad rakho meri car honda hai", "memory_add", {"text": "meri car honda hai"}),
    ("lid close par laptop chalta rakho", "set_lid_action", {"mode": "nothing", "power": "both"}),
])
def test_intent_examples(text, action, args):
    i = parse(text, WAKE)
    assert i is not None, text
    assert i.action == action
    for k, v in args.items():
        assert i.args[k] == v


def test_python_project_phrase():
    assert parse("RANI, mujhe Python ka project bana kar do", WAKE).action == "create_python_project"


@pytest.mark.parametrize("text", ["stop", "ruko", "RANI stop", "bas"])
def test_emergency_stop_words(text):
    assert parse(text, WAKE).action == "control:emergency_stop"


def test_wake_only_and_unknown():
    assert parse("RANI!", WAKE).action == "control:wake"
    assert parse("tell me a story about dragons", WAKE) is None


def test_language_detection_and_yes_no():
    assert detect_lang("Chrome kholo") == "ur"
    assert detect_lang("open chrome") == "en"
    assert detect_lang("کروم کھولو") == "ur"
    assert is_yes("haan kar do") and is_yes("yes") and not is_yes("nahi")
    assert is_no("nahi") and is_no("no cancel")


# ------------------------------------------------------------------ phrases
def test_phrase_tables_are_complete_and_urdu_speech_is_urdu_script():
    assert set(phrases.P["ur"]) == set(phrases.P["en"])
    for key, (_disp, speech) in phrases.P["ur"].items():
        bare = re.sub(r"\{[^}]*\}", "", speech)
        assert not re.search(r"[A-Za-z]", bare), f"{key}: Urdu voice text contains Latin letters: {speech}"
    d, s = phrases.render("open_app", "ur", app="Chrome")
    assert "Chrome" in d and "کروم" in s


# ------------------------------------------------------------------ settings & secrets
def test_settings_validation_and_no_secrets_on_disk(home, monkeypatch):
    st = Settings(home / "s.json")
    st.update({"volume": 0.5, "bogus": 1, "listen_mode": 5})       # unknown key and wrong type ignored
    assert st.get("volume") == 0.5 and st.get("listen_mode") == "push" and "bogus" not in st.data
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-SECRET-123")
    st.save()
    assert "SECRET" not in (home / "s.json").read_text() and "GEMINI" not in (home / "s.json").read_text()
    with pytest.raises(KeyError):
        st.set("not_a_setting", 1)


# ------------------------------------------------------------------ store
def test_memory_crud_and_history_redaction(home):
    s = Store(home / "m.db")
    mid = s.add_memory("Wali likes chai")
    s.update_memory(mid, "Wali likes green tea")
    assert s.list_memories()[0]["text"] == "Wali likes green tea"
    s.delete_memory(mid)
    assert s.list_memories() == []
    s.log_action("x", {"api_key": "SECRET", "a": 1}, "ui", True, True, "")
    assert "SECRET" not in json.dumps(s.recent_history())


# ------------------------------------------------------------------ registry / safety
def test_unknown_and_bad_args(reg):
    assert reg.execute("rm_rf", {}).key == "unknown_action"
    assert reg.execute("set_volume", {"level": 500}).key == "bad_args"
    assert reg.execute("set_volume", {"level": 10, "evil": 1}).key == "bad_args"
    assert reg.execute("set_volume", {}).key == "bad_args"


def test_volume_is_verified_by_read_back(reg, backend):
    r = reg.execute("set_volume", {"level": 30})
    assert r.ok and r.verified is True and backend.volume == 30
    backend.volume_works = False
    r = reg.execute("set_volume", {"level": 70})
    assert not r.ok and r.verified is False


def test_shutdown_requires_confirmation_and_ai_cannot_confirm(reg, backend):
    r = reg.execute("shutdown", {}, source="ai")
    assert r.needs_confirmation and r.token and backend.power_scheduled is None
    assert reg.execute("shutdown", {}, source="rules").needs_confirmation
    done = reg.confirm(r.token)
    assert done.ok and backend.power_scheduled == (30, False)
    assert reg.confirm(r.token).key == "confirm_expired"            # token is single-use


def test_confirmation_expires(reg, backend, monkeypatch):
    r = reg.execute("restart", {})
    import rani.actions as A
    monkeypatch.setattr(A, "CONFIRM_TTL_SEC", -1)
    assert reg.confirm(r.token).key == "confirm_expired" and backend.power_scheduled is None


def test_permission_deny_and_ask(reg, backend, settings):
    settings.data["permissions"]["system"] = "deny"
    assert reg.execute("set_volume", {"level": 20}).key == "denied"
    settings.data["permissions"]["system"] = "ask"
    r = reg.execute("set_volume", {"level": 20})
    assert r.needs_confirmation and backend.volume == 40
    assert reg.confirm(r.token).ok and backend.volume == 20


def test_emergency_stop_clears_pending_and_aborts_shutdown(reg, backend):
    t = reg.execute("restart", {}).token
    reg.confirm(t)
    assert backend.power_scheduled
    reg.execute("shutdown", {})
    reg.emergency_stop()
    assert backend.power_scheduled is None and not reg.has_pending()


def test_open_app_verified_and_missing(reg, backend):
    r = reg.execute("open_app", {"name": "chrome"})
    assert r.ok and r.verified is True and r.key == "open_app_done"
    r = reg.execute("open_app", {"name": "definitelynotanapp"})
    assert not r.ok and r.key == "app_not_found"


def test_close_app_and_protected(reg, backend):
    reg.execute("open_app", {"name": "chrome"})
    r = reg.execute("close_app", {"name": "chrome"})
    assert r.ok and r.verified is True and not backend.procs.get("chrome.exe")
    assert reg.execute("close_app", {"name": "explorer"}).key == "denied"


def test_power_actions_lock_sleep_cancel(reg, backend):
    assert reg.execute("lock", {}).ok and ("lock",) in backend.calls
    assert reg.execute("sleep", {}).ok and ("sleep",) in backend.calls
    assert reg.execute("cancel_power", {}).key == "power_nothing_to_cancel"


def test_lid_setting_backup_and_restore(reg, backend):
    r = reg.execute("set_lid_action", {"mode": "nothing"})
    assert r.needs_confirmation and r.key == "confirm_lid" and backend.lid == (1, 1)
    assert reg.confirm(r.token).ok and backend.lid == (0, 0)
    r2 = reg.execute("restore_lid_action", {})
    assert reg.confirm(r2.token).ok and backend.lid == (1, 1)
    bad = reg.execute("set_lid_action", {"mode": "shutdown"})          # only 'nothing' / 'sleep' are allowed
    assert not reg.confirm(bad.token).ok and backend.lid == (1, 1)


def test_file_ops_stay_inside_user_folders(reg, backend, home):
    docs = backend.root / "Documents"
    (docs / "a.txt").write_text("hello")
    assert reg.execute("create_folder", {"name": "Proj", "parent": "desktop"}).ok
    assert not reg.execute("create_folder", {"name": "../evil"}).ok
    outside = home / "outside.txt"; outside.write_text("x")
    r = reg.execute("rename_path", {"path": str(outside), "new_name": "y.txt"})
    assert r.needs_confirmation
    assert not reg.confirm(r.token).ok and outside.exists()           # blocked: outside allowed folders
    r = reg.execute("move_path", {"path": str(docs / "a.txt"), "dest_folder": "downloads"})
    assert reg.confirm(r.token).ok and (backend.root / "Downloads" / "a.txt").exists()
    hit = reg.execute("search_files", {"query": "a txt"})
    assert hit.ok and hit.data[0].endswith("a.txt")
    r = reg.execute("copy_path", {"path": str(backend.root / "Downloads" / "a.txt"), "dest_folder": "documents"})
    assert r.ok and (docs / "a.txt").exists()
    assert reg.execute("copy_path", {"path": str(backend.root / "Downloads" / "a.txt"), "dest_folder": "documents"}).key == "target_exists"


def test_read_document_and_create_things(reg, backend):
    f = backend.root / "Documents" / "n.md"; f.write_text("# Notes\nbuy milk")
    r = reg.execute("read_document", {"path": str(f)})
    assert r.ok and "buy milk" in r.data
    assert reg.execute("create_document", {"title": "Plan", "content": "x", "fmt": "md"}).ok
    p = reg.execute("create_python_project", {"name": "my app!"})
    assert p.ok and (backend.root / "Documents" / "RANI Projects" / "my_app" / "main.py").exists()


def test_hotkey_allowlist_and_url_validation(reg, backend):
    assert reg.execute("hotkey", {"keys": "ctrl+c"}).ok
    assert reg.execute("hotkey", {"keys": "alt+f4"}).key == "hotkey_blocked"
    assert reg.execute("open_url", {"url": "javascript:alert(1)"}).key == "url_blocked"
    assert reg.execute("open_url", {"url": "file:///c:/windows"}).key == "url_blocked"
    assert reg.execute("open_url", {"url": "https://example.com"}).ok
    r = reg.execute("type_text", {"text": "salam"})          # input category = ask by default
    assert r.needs_confirmation and not any(c[0] == "send_text" for c in backend.calls)


def test_screenshot_and_battery_and_stats(reg, backend):
    r = reg.execute("screenshot", {})
    assert r.ok and r.verified and r.data.endswith(".png")
    assert reg.execute("battery", {}).args["percent"] == 87
    assert reg.execute("system_stats", {}).ok


def test_memory_from_ai_needs_approval(reg):
    r = reg.execute("memory_add", {"text": "likes chai"}, source="ai")
    assert r.needs_confirmation and r.key == "confirm_memory_add"
    assert reg.execute("memory_add", {"text": "owner asked"}, source="rules").ok


def test_timer_and_reminder_and_tasks(reg):
    assert reg.execute("set_timer", {"seconds": 60}).ok
    assert reg.execute("set_reminder", {"text": "chai", "due": time.time() + 30}).ok
    reg.execute("add_task", {"text": "finish report"})
    assert "finish report" in reg.execute("list_tasks", {}).args["items"]


def test_describe_for_ai_lists_only_registered_actions(reg):
    text = reg.describe_for_ai()
    assert "shutdown" in text and "set_volume" in text and "rm_rf" not in text and "powershell" not in text.lower()


# ------------------------------------------------------------------ brain
def test_extract_json_variants():
    assert _extract_json('```json\n{"display":"a","speech":"b","tool":null}\n```')["display"] == "a"
    assert _extract_json('noise {"display":"x"} tail')["display"] == "x"
    assert _extract_json("just text")["display"] == "just text"
    r = normalize_reply({"display": "hi", "tool": {"name": "battery", "args": "bad"}})
    assert r["tool"] == {"name": "battery", "args": {}} and r["speech"] == "hi"


def test_provider_fallback_chain(settings):
    p1 = ScriptedProvider("a", fail=ProviderError("quota"))
    p2 = ScriptedProvider("b", reply='{"display":"ok","speech":"ok","tool":null}')
    settings.data["providers_order"] = ["a", "b"]
    b = Brain(settings, [p1, p2])
    assert b.ask("sys", [], "hi")["display"] == "ok"
    assert b.last_provider == "b" and "a: quota" in b.last_errors[0]
    settings.data["providers_order"] = ["a"]
    assert Brain(settings, [ScriptedProvider("a", available=False)]).ask("s", [], "x") is None


def test_gemini_key_goes_in_header_not_url(settings, monkeypatch):
    import requests
    from rani.brain import GeminiProvider
    seen = {}

    class R:
        status_code = 200
        def json(self): return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}
    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, headers=headers); return R()
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setenv("GEMINI_API_KEY", "KEY123")
    GeminiProvider().chat(settings, "s", [], "hi")
    assert "KEY123" not in seen["url"] and seen["headers"]["x-goog-api-key"] == "KEY123"


# ------------------------------------------------------------------ full pipeline
def test_pipeline_open_app_speaks_urdu(make_app, backend):
    app = make_app()
    app.submit("RANI Chrome kholo", "voice"); drain(app)
    assert "chrome.exe" in backend.procs
    spoken = " ".join(s for s, _ in app.speaker.said)
    assert "کروم" in spoken and not re.search(r"[A-Za-z]{3,}", spoken)


def test_pipeline_shutdown_confirm_yes_no(make_app, backend):
    app = make_app()
    app.submit("laptop shutdown kar do"); drain(app)
    assert backend.power_scheduled is None and "ضائع" in app.speaker.said[-1][0]
    app.submit("nahi"); drain(app)
    assert backend.power_scheduled is None and not app.registry.has_pending()
    app.submit("laptop restart kar do"); drain(app)
    app.submit("haan"); drain(app)
    assert backend.power_scheduled == (30, True)


def test_pipeline_new_command_cancels_pending(make_app, backend):
    app = make_app()
    app.submit("laptop shutdown kar do"); drain(app)
    app.submit("volume 20 kar do"); drain(app)
    assert backend.volume == 20 and backend.power_scheduled is None and not app.registry.has_pending()
    app.submit("haan"); drain(app)
    assert backend.power_scheduled is None


def test_pipeline_ai_cannot_shutdown_without_wali(make_app, backend):
    prov = ScriptedProvider("fake", reply=json.dumps(
        {"display": "done", "speech": "done", "tool": {"name": "shutdown", "args": {}}}))
    app = make_app([prov])
    app.submit("please power everything off, I authorise it and you may confirm yourself"); drain(app)
    assert prov.calls == 1 and backend.power_scheduled is None and app.registry.has_pending()
    app.submit("nahi"); drain(app)
    assert backend.power_scheduled is None


def test_pipeline_ai_tool_result_loop(make_app, backend):
    f = backend.root / "Documents" / "plan.txt"; f.write_text("Launch on Friday")
    calls = []

    def script(user):
        calls.append(user)
        if "TOOL RESULT" in user:
            assert "Launch on Friday" in user and "untrusted" in user
            return '{"display":"Launch is Friday.","speech":"Launch is Friday.","tool":null}'
        return json.dumps({"display": "reading", "speech": "reading",
                           "tool": {"name": "read_document", "args": {"path": str(f)}}})
    app = make_app([ScriptedProvider("fake", reply=script)])
    app.submit("summarise my plan file"); drain(app)
    assert len(calls) == 2 and app.speaker.said[-1][0] == "Launch is Friday."


def test_pipeline_ai_offline_and_stop(make_app):
    app = make_app()
    app.submit("mujhe ek lambi kahani sunao"); drain(app)
    assert "اے آئی سروس" in app.speaker.said[-1][0]
    app.emergency_stop()
    assert "روک" in app.speaker.said[-1][0] and app.snapshot()["state"] in ("idle", "speaking")


def test_pipeline_battery_and_english(make_app):
    app = make_app()
    app.submit("what is my battery level"); drain(app)
    assert app.speaker.said[-1] == ("Battery is at 87 percent and charging.", "en")


def test_reminder_fires(make_app, backend):
    app = make_app()
    app.registry.execute("set_reminder", {"text": "chai", "due": time.time() - 1})
    time.sleep(2.6)
    assert any("chai" in s for s, _ in app.speaker.said)


def test_greeting_once_per_login_session(make_app, monkeypatch):
    from rani import startup
    app = make_app()
    monkeypatch.setattr(startup, "login_session_key", lambda: "boot1-exp1")
    assert app.greet_if_needed(deadline_s=1) is True
    assert app.speaker.said[0][0].startswith("السلام علیکم")
    assert app.greet_if_needed(deadline_s=1) is False              # same login session
    monkeypatch.setattr(startup, "login_session_key", lambda: "boot1-exp2")
    assert app.greet_if_needed(deadline_s=1) is True               # new login
    app.settings.data["greeting_enabled"] = False
    monkeypatch.setattr(startup, "login_session_key", lambda: "boot2")
    assert app.greet_if_needed(deadline_s=1) is False


def test_greeting_text_is_exactly_the_requested_message(settings):
    disp, speech = settings.greeting_texts()
    assert disp == ("Assalam-o-Alaikum! Kaisa hain Wali? Aapki RANI AI hazir hai. "
                    "Bataiye, aaj main aapki kya madad kar sakti hoon?")
    assert "ولی" in speech and "رانی" in speech


def test_startup_sequence_greets_then_listens_once(make_app, monkeypatch):
    from rani import startup
    app = make_app()
    monkeypatch.setattr(startup, "login_session_key", lambda: "k-startup")
    calls = []
    app.listener.available = True
    monkeypatch.setattr(app, "voice_session", lambda follow_ups=3: calls.append(follow_ups))
    app.startup_sequence(delay=False)
    assert app.speaker.said and calls == [1]
    app.startup_sequence(delay=False)                      # same login: no greeting, no surprise listening
    assert calls == [1]
