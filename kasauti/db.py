"""SQLite storage."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS scripts(
  id TEXT PRIMARY KEY, grp TEXT, lang TEXT, text TEXT, entities_json TEXT, keyterms_json TEXT);
CREATE TABLE IF NOT EXISTS variants(
  id TEXT PRIMARY KEY, script_id TEXT, source TEXT, voice TEXT, tts_variant TEXT,
  condition TEXT, parent_id TEXT, path TEXT, sample_rate INTEGER, mock INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, variant_id TEXT, config TEXT, status TEXT,
  transcript TEXT, detected_language TEXT, latency_ms INTEGER, request_id TEXT, error TEXT,
  mock INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(variant_id, config));
CREATE TABLE IF NOT EXISTS scores(
  run_id INTEGER PRIMARY KEY, wer REAL, cer REAL, digit_exact REAL, digit_characc REAL,
  amount_exact REAL, name_match REAL, lang_match REAL, entity_recall REAL);
CREATE TABLE IF NOT EXISTS api_calls(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ok INTEGER, ms INTEGER,
  mock INTEGER DEFAULT 0, ts TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


class DB:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()   # workers read while the main thread writes
        self.conn.executescript(SCHEMA)

    def execute(self, sql, params=()):
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def query(self, sql, params=()):
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        with self._lock:
            r = self.conn.execute(sql, params).fetchone()
            return dict(r) if r else None

    def close(self):
        self.conn.close()
