"""Tiny SQLite store: verified users, chat history, notes, todos, reminders, price alerts."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, chat_id INTEGER, phone TEXT, name TEXT, verified_at REAL
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, role TEXT, content TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT, done INTEGER DEFAULT 0, ts REAL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, text TEXT, due_ts REAL, done INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, symbol TEXT, op TEXT, price REAL,
    active INTEGER DEFAULT 1, ts REAL
);
"""


class DB:
    def __init__(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # users
    def verify_user(self, user_id: int, chat_id: int, phone: str, name: str) -> None:
        self._exec(
            "INSERT OR REPLACE INTO users(user_id, chat_id, phone, name, verified_at) VALUES (?,?,?,?,?)",
            (user_id, chat_id, phone, name, time.time()),
        )

    def is_verified(self, user_id: int) -> bool:
        return bool(self._all("SELECT 1 FROM users WHERE user_id=?", (user_id,)))

    def owner_chat_ids(self) -> list[int]:
        return [r["chat_id"] for r in self._all("SELECT chat_id FROM users")]

    # chat history
    def add_history(self, chat_id: int, role: str, content: str) -> None:
        self._exec("INSERT INTO history(chat_id, role, content, ts) VALUES (?,?,?,?)",
                   (chat_id, role, content, time.time()))

    def get_history(self, chat_id: int, limit: int) -> list[dict]:
        rows = self._all(
            "SELECT role, content FROM history WHERE chat_id=? ORDER BY id DESC LIMIT ?", (chat_id, limit)
        )
        msgs = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
        while msgs and msgs[0]["role"] != "user":  # API needs the first message to be from the user
            msgs.pop(0)
        return msgs

    def clear_history(self, chat_id: int) -> None:
        self._exec("DELETE FROM history WHERE chat_id=?", (chat_id,))

    # notes
    def add_note(self, user_id: int, text: str) -> int:
        return self._exec("INSERT INTO notes(user_id, text, ts) VALUES (?,?,?)", (user_id, text, time.time())).lastrowid

    def list_notes(self, user_id: int) -> list[sqlite3.Row]:
        return self._all("SELECT id, text, ts FROM notes WHERE user_id=? ORDER BY id", (user_id,))

    def delete_note(self, user_id: int, note_id: int) -> bool:
        return self._exec("DELETE FROM notes WHERE user_id=? AND id=?", (user_id, note_id)).rowcount > 0

    # todos
    def add_todo(self, user_id: int, text: str) -> int:
        return self._exec("INSERT INTO todos(user_id, text, ts) VALUES (?,?,?)", (user_id, text, time.time())).lastrowid

    def list_todos(self, user_id: int) -> list[sqlite3.Row]:
        return self._all("SELECT id, text, done FROM todos WHERE user_id=? ORDER BY done, id", (user_id,))

    def complete_todo(self, user_id: int, todo_id: int) -> bool:
        return self._exec("UPDATE todos SET done=1 WHERE user_id=? AND id=?", (user_id, todo_id)).rowcount > 0

    # reminders
    def add_reminder(self, chat_id: int, text: str, due_ts: float) -> int:
        return self._exec("INSERT INTO reminders(chat_id, text, due_ts) VALUES (?,?,?)", (chat_id, text, due_ts)).lastrowid

    def pending_reminders(self, chat_id: int | None = None) -> list[sqlite3.Row]:
        if chat_id is None:
            return self._all("SELECT * FROM reminders WHERE done=0 ORDER BY due_ts")
        return self._all("SELECT * FROM reminders WHERE done=0 AND chat_id=? ORDER BY due_ts", (chat_id,))

    def finish_reminder(self, reminder_id: int, chat_id: int | None = None) -> bool:
        if chat_id is None:
            return self._exec("UPDATE reminders SET done=1 WHERE id=?", (reminder_id,)).rowcount > 0
        return self._exec("UPDATE reminders SET done=1 WHERE id=? AND chat_id=?", (reminder_id, chat_id)).rowcount > 0

    # price alerts
    def add_alert(self, chat_id: int, symbol: str, op: str, price: float) -> int:
        return self._exec("INSERT INTO alerts(chat_id, symbol, op, price, ts) VALUES (?,?,?,?,?)",
                          (chat_id, symbol, op, price, time.time())).lastrowid

    def active_alerts(self, chat_id: int | None = None) -> list[sqlite3.Row]:
        if chat_id is None:
            return self._all("SELECT * FROM alerts WHERE active=1")
        return self._all("SELECT * FROM alerts WHERE active=1 AND chat_id=?", (chat_id,))

    def deactivate_alert(self, alert_id: int, chat_id: int | None = None) -> bool:
        if chat_id is None:
            return self._exec("UPDATE alerts SET active=0 WHERE id=?", (alert_id,)).rowcount > 0
        return self._exec("UPDATE alerts SET active=0 WHERE id=? AND chat_id=?", (alert_id, chat_id)).rowcount > 0
