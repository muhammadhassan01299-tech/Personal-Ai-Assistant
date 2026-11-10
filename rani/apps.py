"""Catalog of well-known apps and web sites RANI can open by name."""
from __future__ import annotations

# key -> display, aliases (lowercase, spoken/typed), launch candidates (tried in order),
# lnk = Start-Menu shortcut name fragment, proc = process image names used for verification.
APPS: dict[str, dict] = {
    "chrome": dict(display="Chrome", aliases=["chrome", "google chrome", "crome", "krom", "کروم"],
                   launch=["chrome"], lnk="Google Chrome", proc=["chrome.exe"]),
    "edge": dict(display="Edge", aliases=["edge", "microsoft edge", "ایج"],
                 launch=["msedge"], lnk="Microsoft Edge", proc=["msedge.exe"]),
    "firefox": dict(display="Firefox", aliases=["firefox", "فائر فاکس"],
                    launch=["firefox"], lnk="Firefox", proc=["firefox.exe"]),
    "vscode": dict(display="VS Code", aliases=["vs code", "vscode", "visual studio code", "code editor",
                                                "وی ایس کوڈ"],
                   launch=["code"], lnk="Visual Studio Code", proc=["Code.exe"]),
    "notepad": dict(display="Notepad", aliases=["notepad", "note pad", "نوٹ پیڈ"],
                    launch=["notepad.exe"], lnk="Notepad", proc=["notepad.exe", "Notepad.exe"]),
    "calculator": dict(display="Calculator", aliases=["calculator", "calc", "کیلکولیٹر"],
                       launch=["calc.exe"], lnk="Calculator",
                       proc=["CalculatorApp.exe", "calc.exe", "Calculator.exe"]),
    "explorer": dict(display="File Explorer", aliases=["file explorer", "explorer", "my computer", "this pc"],
                     launch=["explorer.exe"], lnk="", proc=["explorer.exe"], protected=True),
    "settings": dict(display="Settings", aliases=["settings", "سیٹنگز"],
                     launch=["ms-settings:"], lnk="Settings", proc=["SystemSettings.exe"]),
    "taskmanager": dict(display="Task Manager", aliases=["task manager", "taskmanager", "ٹاسک مینیجر"],
                        launch=["taskmgr.exe"], lnk="Task Manager", proc=["Taskmgr.exe"]),
    "word": dict(display="Word", aliases=["word", "ms word", "microsoft word", "ورڈ"],
                 launch=["winword"], lnk="Word", proc=["WINWORD.EXE"]),
    "excel": dict(display="Excel", aliases=["excel", "ms excel", "ایکسل"],
                  launch=["excel"], lnk="Excel", proc=["EXCEL.EXE"]),
    "powerpoint": dict(display="PowerPoint", aliases=["powerpoint", "power point", "ppt", "پاور پوائنٹ"],
                       launch=["powerpnt"], lnk="PowerPoint", proc=["POWERPNT.EXE"]),
    "paint": dict(display="Paint", aliases=["paint", "ms paint", "پینٹ"],
                  launch=["mspaint.exe"], lnk="Paint", proc=["mspaint.exe"]),
    "spotify": dict(display="Spotify", aliases=["spotify", "سپوٹیفائی"],
                    launch=[], lnk="Spotify", proc=["Spotify.exe"]),
    "whatsapp": dict(display="WhatsApp", aliases=["whatsapp", "whats app", "واٹس ایپ"],
                     launch=[], lnk="WhatsApp", proc=["WhatsApp.exe", "WhatsApp.Root.exe"]),
    "terminal": dict(display="Terminal", aliases=["terminal", "windows terminal", "ٹرمنل"],
                     launch=["wt.exe"], lnk="Terminal", proc=["WindowsTerminal.exe"]),
    "vlc": dict(display="VLC", aliases=["vlc", "vlc player", "وی ایل سی"],
                launch=[], lnk="VLC", proc=["vlc.exe"]),
}

# Processes RANI must never terminate (would break Windows or itself).
PROTECTED_PROCESSES = {
    "explorer.exe", "winlogon.exe", "csrss.exe", "wininit.exe", "services.exe", "lsass.exe",
    "svchost.exe", "system", "smss.exe", "dwm.exe", "python.exe", "pythonw.exe",
}

SITES: dict[str, str] = {
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com",
    "github": "https://github.com", "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com", "linkedin": "https://www.linkedin.com",
    "google": "https://www.google.com", "whatsapp web": "https://web.whatsapp.com",
    "chatgpt": "https://chatgpt.com", "gemini": "https://gemini.google.com",
    "یوٹیوب": "https://www.youtube.com", "گوگل": "https://www.google.com",
}

KNOWN_FOLDERS = {
    "downloads": "Downloads", "download": "Downloads", "ڈاؤن لوڈ": "Downloads", "ڈاؤنلوڈ": "Downloads",
    "documents": "Documents", "document": "Documents", "ڈاکومنٹس": "Documents",
    "desktop": "Desktop", "ڈیسک ٹاپ": "Desktop",
    "pictures": "Pictures", "photos": "Pictures", "تصاویر": "Pictures",
    "videos": "Videos", "video": "Videos", "ویڈیوز": "Videos",
    "music": "Music", "گانے": "Music",
    "home": "", "user": "",
}


def resolve_app(name: str) -> str | None:
    n = " ".join(name.lower().split())
    for key, spec in APPS.items():
        if n == key or n in spec["aliases"]:
            return key
    return None


def find_app_in_text(text: str) -> tuple[str, str] | None:
    """Longest alias contained in the text -> (key, matched alias)."""
    t = f" {text.lower()} "
    best = None
    for key, spec in APPS.items():
        for a in spec["aliases"]:
            if f" {a} " in t or (not a.isascii() and a in t):
                if best is None or len(a) > len(best[1]):
                    best = (key, a)
    return best
