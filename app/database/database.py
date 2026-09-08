"""
SQLite persistence layer.

Stores ONLY: sessions, crossing events (timestamp, camera, track_id,
event type). Per spec section 14 / 29, this NEVER stores faces, face
embeddings, or any biometric data — track_id is an ephemeral integer
assigned by ByteTrack for the lifetime of the process only.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    ended_at REAL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS crossing_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    camera_id TEXT NOT NULL,
    track_id INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('ENTRY', 'EXIT')),
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_events_session ON crossing_events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_camera ON crossing_events(camera_id);
"""


@dataclass
class SessionRecord:
    id: int
    started_at: float
    ended_at: Optional[float]
    notes: Optional[str]


@dataclass
class EventRecord:
    id: int
    session_id: int
    timestamp: float
    camera_id: str
    track_id: int
    event_type: str


class Database:
    """Thread-safe wrapper (one lock; SQLite + multi-camera threads)."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    @contextmanager
    def _cursor(self):
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    # ---- sessions ----

    def start_session(self, notes: Optional[str] = None) -> int:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (started_at, ended_at, notes) VALUES (?, NULL, ?)",
                (time.time(), notes),
            )
            return cur.lastrowid

    def end_session(self, session_id: int):
        with self._cursor() as cur:
            cur.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?", (time.time(), session_id)
            )

    def get_session(self, session_id: int) -> Optional[SessionRecord]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cur.fetchone()
            return SessionRecord(**dict(row)) if row else None

    def latest_session(self) -> Optional[SessionRecord]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            return SessionRecord(**dict(row)) if row else None

    # ---- events ----

    def record_event(
        self, session_id: int, camera_id: str, track_id: int, event_type: str, timestamp: Optional[float] = None
    ) -> int:
        if event_type not in ("ENTRY", "EXIT"):
            raise ValueError("event_type must be 'ENTRY' or 'EXIT'")
        ts = timestamp if timestamp is not None else time.time()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO crossing_events (session_id, timestamp, camera_id, track_id, event_type) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, ts, camera_id, track_id, event_type),
            )
            return cur.lastrowid

    def get_events(
        self, session_id: Optional[int] = None, camera_id: Optional[str] = None, limit: int = 200
    ) -> List[EventRecord]:
        query = "SELECT * FROM crossing_events WHERE 1=1"
        params: list = []
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        if camera_id is not None:
            query += " AND camera_id = ?"
            params.append(camera_id)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._cursor() as cur:
            cur.execute(query, params)
            return [EventRecord(**dict(row)) for row in cur.fetchall()]

    def count_events(self, session_id: int, camera_id: str, event_type: str) -> int:
        with self._cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) as c FROM crossing_events "
                "WHERE session_id = ? AND camera_id = ? AND event_type = ?",
                (session_id, camera_id, event_type),
            )
            return cur.fetchone()["c"]

    def close(self):
        with self._lock:
            self._conn.close()
