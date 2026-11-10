"""SQLite storage: approved memories, action history, reminders, tasks, chat log."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .config import app_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories(
  id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, action TEXT NOT NULL,
  args TEXT, source TEXT, ok INTEGER, verified INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS reminders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, due REAL NOT NULL, text TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'reminder', done INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
  created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS chat(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL);
"""

SENSITIVE_ARG_KEYS = {"api_key", "password", "token", "secret"}


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = str(path or (app_dir() / "rani.db"))
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()
        self.prune()

    def prune(self, keep_chat: int = 2000, keep_history: int = 3000) -> None:
        """Keep the chat log / action history bounded (they were never cleaned before)."""
        self._run("DELETE FROM chat WHERE id <= (SELECT MAX(id) FROM chat) - ?", (keep_chat,))
        self._run("DELETE FROM history WHERE id <= (SELECT MAX(id) FROM history) - ?", (keep_history,))
        self._run("DELETE FROM reminders WHERE done=1 AND due < ?", (time.time() - 30 * 86400,))

    def _run(self, sql, params=(), fetch=False):
        with self._lock:
            cur = self._db.execute(sql, params)
            self._db.commit()
            if fetch:
                return [dict(r) for r in cur.fetchall()]
            return cur.lastrowid

    # ---- memories (only saved after the owner approved them)
    def add_memory(self, text: str) -> int:
        text = text.strip()
        if not text:
            raise ValueError("empty memory")
        return self._run("INSERT INTO memories(text, created) VALUES(?,?)", (text[:500], time.time()))

    def list_memories(self):
        return self._run("SELECT id, text, created FROM memories ORDER BY id", fetch=True)

    def update_memory(self, mid: int, text: str) -> bool:
        self._run("UPDATE memories SET text=? WHERE id=?", (text.strip()[:500], int(mid)))
        return True

    def delete_memory(self, mid: int) -> bool:
        self._run("DELETE FROM memories WHERE id=?", (int(mid),))
        return True

    def clear_memories(self) -> None:
        self._run("DELETE FROM memories")

    # ---- action history
    def log_action(self, action, args, source, ok, verified, detail) -> int:
        clean = {k: ("***" if k in SENSITIVE_ARG_KEYS else v) for k, v in (args or {}).items()}
        return self._run(
            "INSERT INTO history(ts,action,args,source,ok,verified,detail) VALUES(?,?,?,?,?,?,?)",
            (time.time(), action, json.dumps(clean, ensure_ascii=False, default=str), source,
             int(bool(ok)), None if verified is None else int(bool(verified)), (detail or "")[:300]))

    def recent_history(self, limit=50):
        return self._run("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,), fetch=True)

    def clear_history(self):
        self._run("DELETE FROM history")

    # ---- reminders / timers
    def add_reminder(self, due: float, text: str, kind="reminder") -> int:
        return self._run("INSERT INTO reminders(due,text,kind) VALUES(?,?,?)", (due, text, kind))

    def due_reminders(self, now=None):
        return self._run("SELECT * FROM reminders WHERE done=0 AND due<=? ORDER BY due",
                         (now or time.time(),), fetch=True)

    def pending_reminders(self):
        return self._run("SELECT * FROM reminders WHERE done=0 ORDER BY due", fetch=True)

    def mark_reminder_done(self, rid: int):
        self._run("UPDATE reminders SET done=1 WHERE id=?", (rid,))

    # ---- tasks
    def add_task(self, text: str) -> int:
        return self._run("INSERT INTO tasks(text,created) VALUES(?,?)", (text.strip(), time.time()))

    def list_tasks(self, include_done=False):
        q = "SELECT * FROM tasks" + ("" if include_done else " WHERE done=0") + " ORDER BY id"
        return self._run(q, fetch=True)

    def complete_task(self, tid: int):
        self._run("UPDATE tasks SET done=1 WHERE id=?", (int(tid),))

    # ---- chat history
    def add_chat(self, role: str, text: str):
        self._run("INSERT INTO chat(ts,role,text) VALUES(?,?,?)", (time.time(), role, text[:2000]))

    def recent_chat(self, n: int):
        rows = self._run("SELECT role, text FROM chat ORDER BY id DESC LIMIT ?", (n * 2,), fetch=True)
        return list(reversed(rows))

    def close(self):
        with self._lock:
            self._db.close()
