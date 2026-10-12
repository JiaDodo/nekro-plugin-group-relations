"""Plugin-owned SQLite data. All operations use parameterized SQL."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Repository:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS channels (
                    chat_key TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    cleared_at INTEGER NOT NULL DEFAULT 0, cursor INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS messages (
                    chat_key TEXT NOT NULL, id TEXT NOT NULL, sender TEXT NOT NULL, name TEXT NOT NULL,
                    ts INTEGER NOT NULL, mentions TEXT NOT NULL, reply TEXT NOT NULL, reply_sender TEXT NOT NULL,
                    PRIMARY KEY(chat_key,id));
                CREATE INDEX IF NOT EXISTS messages_time ON messages(chat_key,ts);
                CREATE TABLE IF NOT EXISTS excluded (
                    chat_key TEXT NOT NULL, user_id TEXT NOT NULL, PRIMARY KEY(chat_key,user_id));
                CREATE TABLE IF NOT EXISTS sync_state (
                    chat_key TEXT PRIMARY KEY, covered_from INTEGER NOT NULL, synced_at INTEGER NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def ensure_channel(self, chat_key: str, name: str):
        with self.connect() as db:
            db.execute("INSERT INTO channels(chat_key,name) VALUES(?,?) ON CONFLICT(chat_key) DO UPDATE SET name=excluded.name", (chat_key, name or chat_key))

    def state(self, chat_key: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM channels WHERE chat_key=?", (chat_key,)).fetchone()
            return dict(row) if row else {"chat_key": chat_key, "name": chat_key, "enabled": 1, "cleared_at": 0, "cursor": 0}

    def excluded(self, chat_key: str) -> set[str]:
        with self.connect() as db:
            return {r[0] for r in db.execute("SELECT user_id FROM excluded WHERE chat_key=?", (chat_key,))}

    def insert(self, chat_key: str, name: str, rows: list[dict], cursor: int | None = None):
        self.ensure_channel(chat_key, name)
        with self.connect() as db:
            state = db.execute("SELECT * FROM channels WHERE chat_key=?", (chat_key,)).fetchone()
            blocked = {r[0] for r in db.execute("SELECT user_id FROM excluded WHERE chat_key=?", (chat_key,))}
            if state["enabled"]:
                accepted = [r for r in rows if r["ts"] > state["cleared_at"] and r["sender"] not in blocked]
                db.executemany("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(chat_key,id) DO UPDATE SET name=excluded.name,mentions=excluded.mentions,reply=excluded.reply,reply_sender=excluded.reply_sender", [
                    (chat_key, r["id"], r["sender"], r["name"], r["ts"],
                     json.dumps([t for t in r["mentions"] if t not in blocked]), r.get("reply", ""),
                     r.get("reply_sender", "") if r.get("reply_sender") not in blocked else "") for r in accepted])
            if cursor is not None:
                db.execute("UPDATE channels SET cursor=MAX(cursor,?) WHERE chat_key=?", (cursor, chat_key))

    def rows(self, chat_key: str, start: int, end: int) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM messages WHERE chat_key=? AND ts>=? AND ts<? ORDER BY ts,id", (chat_key, start, end)).fetchall()
        return [dict(r) | {"mentions": json.loads(r["mentions"])} for r in rows]

    def set_enabled(self, chat_key: str, enabled: bool):
        self.ensure_channel(chat_key, self.state(chat_key)["name"])
        with self.connect() as db:
            db.execute("UPDATE channels SET enabled=? WHERE chat_key=?", (int(enabled), chat_key))

    def opt_out(self, chat_key: str, uid: str, enabled: bool):
        with self.connect() as db:
            if enabled:
                db.execute("INSERT OR IGNORE INTO excluded VALUES(?,?)", (chat_key, uid))
                db.execute("DELETE FROM messages WHERE chat_key=? AND sender=?", (chat_key, uid))
                # Remove incoming mention and resolved reference identifiers as well.
                for r in db.execute("SELECT id,mentions,reply_sender FROM messages WHERE chat_key=?", (chat_key,)).fetchall():
                    mentions = [t for t in json.loads(r["mentions"]) if t != uid]
                    db.execute("UPDATE messages SET mentions=?,reply_sender=? WHERE chat_key=? AND id=?",
                               (json.dumps(mentions), "" if r["reply_sender"] == uid else r["reply_sender"], chat_key, r["id"]))
            else:
                db.execute("DELETE FROM excluded WHERE chat_key=? AND user_id=?", (chat_key, uid))

    def clear(self, chat_key: str):
        with self.connect() as db:
            db.execute("DELETE FROM messages WHERE chat_key=?", (chat_key,))
            db.execute("DELETE FROM sync_state WHERE chat_key=?", (chat_key,))
            db.execute("UPDATE channels SET cleared_at=? WHERE chat_key=?", (int(time.time()), chat_key))

    def sync_info(self, chat_key: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM sync_state WHERE chat_key=?", (chat_key,)).fetchone()
            return dict(row) if row else {}

    def mark_sync(self, chat_key: str, covered_from: int):
        with self.connect() as db:
            db.execute("INSERT INTO sync_state VALUES(?,?,?) ON CONFLICT(chat_key) DO UPDATE SET covered_from=MIN(covered_from,excluded.covered_from),synced_at=excluded.synced_at",
                       (chat_key, covered_from, int(time.time())))

    def prune(self, oldest: int):
        with self.connect() as db:
            db.execute("DELETE FROM messages WHERE ts<?", (oldest,))
