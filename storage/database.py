"""
database.py – SQLite persistence layer for Telegram Drive.

Stores the mapping between local files and their Telegram message IDs,
along with hash, size, and chunk metadata required for sync and restore.
Also stores user sessions for multi-user authentication.
"""

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from config.settings import DB_PATH


# ──────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────
@dataclass
class FileRecord:
    """Represents a single synced file."""

    path: str
    hash: str
    size: int
    chunks: int
    user_phone: str = ""
    msg_ids: List[int] = field(default_factory=list)
    timestamp: float = 0.0
    id: Optional[int] = None

    def msg_ids_json(self) -> str:
        return json.dumps(self.msg_ids)

    @staticmethod
    def from_row(row: sqlite3.Row) -> "FileRecord":
        return FileRecord(
            id=row["id"],
            path=row["path"],
            hash=row["hash"],
            size=row["size"],
            chunks=row["chunks"],
            user_phone=row["user_phone"],
            msg_ids=json.loads(row["msg_ids"]),
            timestamp=row["timestamp"],
        )


# ──────────────────────────────────────────────
# Database manager
# ──────────────────────────────────────────────
class Database:
    """Thread-safe SQLite wrapper (one connection per instance)."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    # --- lifecycle -----------------------------------------------------------
    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._migrate()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # --- schema --------------------------------------------------------------
    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                path       TEXT    NOT NULL,
                hash       TEXT    NOT NULL,
                size       INTEGER NOT NULL,
                chunks     INTEGER NOT NULL,
                msg_ids    TEXT    NOT NULL,
                user_phone TEXT    NOT NULL DEFAULT '',
                timestamp  REAL    NOT NULL,
                UNIQUE(path, user_phone)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                phone          TEXT    UNIQUE NOT NULL,
                session_string TEXT    NOT NULL,
                display_name   TEXT    NOT NULL DEFAULT '',
                created_at     REAL    NOT NULL,
                last_login     REAL    NOT NULL
            )
            """
        )
        self._conn.commit()

    def _migrate(self) -> None:
        """Handle schema migrations for existing databases."""
        assert self._conn is not None
        # Check if user_phone column exists in files table
        cur = self._conn.execute("PRAGMA table_info(files)")
        columns = [row["name"] for row in cur.fetchall()]
        if "user_phone" not in columns:
            self._conn.execute(
                "ALTER TABLE files ADD COLUMN user_phone TEXT NOT NULL DEFAULT ''"
            )
            self._conn.commit()

    # --- CRUD: Files ---------------------------------------------------------
    def upsert_file(self, record: FileRecord) -> None:
        """Insert or replace a file record."""
        assert self._conn is not None
        self._conn.execute(
            """
            INSERT INTO files (path, hash, size, chunks, msg_ids, user_phone, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path, user_phone) DO UPDATE SET
                hash      = excluded.hash,
                size      = excluded.size,
                chunks    = excluded.chunks,
                msg_ids   = excluded.msg_ids,
                timestamp = excluded.timestamp
            """,
            (
                record.path,
                record.hash,
                record.size,
                record.chunks,
                record.msg_ids_json(),
                record.user_phone,
                time.time(),
            ),
        )
        self._conn.commit()

    def get_file(self, path: str, user_phone: str = "") -> Optional[FileRecord]:
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT * FROM files WHERE path = ? AND user_phone = ?",
            (path, user_phone),
        )
        row = cur.fetchone()
        return FileRecord.from_row(row) if row else None

    def delete_file(self, path: str, user_phone: str = "") -> None:
        assert self._conn is not None
        self._conn.execute(
            "DELETE FROM files WHERE path = ? AND user_phone = ?",
            (path, user_phone),
        )
        self._conn.commit()

    def get_all_files(self, user_phone: str = "") -> List[FileRecord]:
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT * FROM files WHERE user_phone = ? ORDER BY path",
            (user_phone,),
        )
        return [FileRecord.from_row(r) for r in cur.fetchall()]

    def get_total_storage(self, user_phone: str = "") -> int:
        """Return the sum of all tracked file sizes in bytes."""
        assert self._conn is not None
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(size), 0) FROM files WHERE user_phone = ?",
            (user_phone,),
        )
        return int(cur.fetchone()[0])

    # --- CRUD: Users ---------------------------------------------------------
    def upsert_user(
        self, phone: str, session_string: str, display_name: str = ""
    ) -> None:
        """Insert or update a user record."""
        assert self._conn is not None
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO users (phone, session_string, display_name, created_at, last_login)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                session_string = excluded.session_string,
                display_name   = excluded.display_name,
                last_login     = excluded.last_login
            """,
            (phone, session_string, display_name, now, now),
        )
        self._conn.commit()

    def get_user(self, phone: str) -> Optional[Dict]:
        assert self._conn is not None
        cur = self._conn.execute("SELECT * FROM users WHERE phone = ?", (phone,))
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def delete_user(self, phone: str) -> None:
        assert self._conn is not None
        self._conn.execute("DELETE FROM users WHERE phone = ?", (phone,))
        self._conn.commit()
