"""SQLite-backed submission de-duplication.

Adapted from the reference Go agent: a flag is reserved atomically *before* it
is sent to the platform, and the resulting verdict is stored afterwards. Any
later attempt with the same (scope, challenge, flag) — from this run or a
future one — returns the stored verdict instead of spending another attempt.

The scope hashes platform kind + base URL + token, so switching accounts or
competition platforms starts from a clean slate.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "logs" / "submissions.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    challenge TEXT NOT NULL,
    flag TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(scope, challenge, flag)
);
"""

_lock = threading.Lock()


def normalize_flag(flag: str) -> str:
    """Whitespace-collapse so 'flag{ a }' and ' flag{ a } ' count as one."""
    return " ".join(str(flag or "").split())


def scope_for(kind: str, base_url: str, token: str) -> str:
    raw = f"{(kind or '').strip().lower()}|{(base_url or '').rstrip('/')}|{token or ''}"
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:32]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def previous(scope: str, challenge: str, flag: str) -> dict[str, Any] | None:
    """Return the stored row for this submission, if any."""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT status, message, created_at, updated_at FROM submissions "
            "WHERE scope=? AND challenge=? AND flag=?",
            (scope, challenge, normalize_flag(flag)),
        ).fetchone()
    if not row:
        return None
    return {"status": row[0], "message": row[1], "created_at": row[2], "updated_at": row[3]}


def reserve(scope: str, challenge: str, flag: str) -> bool:
    """Atomically claim this submission. False when it is already claimed."""
    now = time.time()
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO submissions "
            "(scope, challenge, flag, status, message, created_at, updated_at) "
            "VALUES (?, ?, ?, 'pending', NULL, ?, ?)",
            (scope, challenge, normalize_flag(flag), now, now),
        )
        return cur.rowcount > 0


def record(
    scope: str,
    challenge: str,
    flag: str,
    status: str,
    message: str = "",
) -> None:
    """Store the verdict for a reserved submission."""
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE submissions SET status=?, message=?, updated_at=? "
            "WHERE scope=? AND challenge=? AND flag=?",
            (status, message[:500], now, scope, challenge, normalize_flag(flag)),
        )


def stats(scope: str | None = None) -> dict[str, int]:
    sql = "SELECT status, COUNT(*) FROM submissions"
    args: tuple[Any, ...] = ()
    if scope:
        sql += " WHERE scope=?"
        args = (scope,)
    sql += " GROUP BY status"
    with _lock, _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}
