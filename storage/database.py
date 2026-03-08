"""
database.py – SQLite persistence layer for Telegram Drive.

Stores the mapping between local files and their Telegram message IDs,
along with hash, size, and chunk metadata required for sync and restore.
"""

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

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
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                path      TEXT    UNIQUE NOT NULL,
                hash      TEXT    NOT NULL,
                size      INTEGER NOT NULL,
                chunks    INTEGER NOT NULL,
                msg_ids   TEXT    NOT NULL,
                timestamp REAL    NOT NULL
            )
            """
        )
        self._conn.commit()

    # --- CRUD ----------------------------------------------------------------
    def upsert_file(self, record: FileRecord) -> None:
        """Insert or replace a file record."""
        assert self._conn is not None
        self._conn.execute(
            """
            INSERT INTO files (path, hash, size, chunks, msg_ids, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
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
                time.time(),
            ),
        )
        self._conn.commit()

    def get_file(self, path: str) -> Optional[FileRecord]:
        assert self._conn is not None
        cur = self._conn.execute("SELECT * FROM files WHERE path = ?", (path,))
        row = cur.fetchone()
        return FileRecord.from_row(row) if row else None

    def delete_file(self, path: str) -> None:
        assert self._conn is not None
        self._conn.execute("DELETE FROM files WHERE path = ?", (path,))
        self._conn.commit()

    def get_all_files(self) -> List[FileRecord]:
        assert self._conn is not None
        cur = self._conn.execute("SELECT * FROM files ORDER BY path")
        return [FileRecord.from_row(r) for r in cur.fetchall()]

    def get_total_storage(self) -> int:
        """Return the sum of all tracked file sizes in bytes."""
        assert self._conn is not None
        cur = self._conn.execute("SELECT COALESCE(SUM(size), 0) FROM files")
        return int(cur.fetchone()[0])

