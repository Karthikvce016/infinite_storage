"""
database.py – SQLAlchemy persistence layer for Telegram Drive.

Supports both PostgreSQL (via DATABASE_URL) and SQLite (fallback for local dev).

Tables:
    files    – maps files to Telegram message IDs (folder-scoped)
    folders  – maps user folders to Telegram channel IDs
    users    – web app users (simple password auth)
"""

import json
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    Float,
    String,
    Text,
    UniqueConstraint,
    MetaData,
    Table,
    select,
    delete,
    update,
    func,
)
from sqlalchemy.orm import Session, sessionmaker, declarative_base

from config.settings import DATABASE_URL, DB_PATH

log = logging.getLogger(__name__)

Base = declarative_base()


# ──────────────────────────────────────────────
# SQLAlchemy Models
# ──────────────────────────────────────────────
class FileModel(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String, nullable=False)
    hash = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    chunks = Column(Integer, nullable=False)
    folder = Column(String, nullable=False)
    owner = Column(String, nullable=False, default="default")
    msg_ids = Column(Text, nullable=False)  # JSON array
    timestamp = Column(Float, nullable=False)
    __table_args__ = (
        UniqueConstraint("path", "folder", "owner", name="uq_file_path_folder_owner"),
    )


class FolderModel(Base):
    __tablename__ = "folders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    channel_id = Column(Integer, nullable=False)
    owner = Column(String, nullable=False, default="default")
    parent_id = Column(Integer, nullable=True, default=None)
    created_at = Column(Float, nullable=False)
    __table_args__ = (
        UniqueConstraint("name", "parent_id", "owner", name="uq_folder_name_parent_owner"),
    )


class UserModel(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(Float, nullable=False)


# ──────────────────────────────────────────────
# Data transfer objects (kept for backward compat)
# ──────────────────────────────────────────────
@dataclass
class FileRecord:
    """Represents a single synced file."""
    path: str
    hash: str
    size: int
    chunks: int
    folder: str
    owner: str = "default"
    msg_ids: List[int] = field(default_factory=list)
    timestamp: float = 0.0
    id: Optional[int] = None

    def msg_ids_json(self) -> str:
        return json.dumps(self.msg_ids)

    @staticmethod
    def from_model(m: FileModel) -> "FileRecord":
        return FileRecord(
            id=m.id,
            path=m.path,
            hash=m.hash,
            size=m.size,
            chunks=m.chunks,
            folder=m.folder,
            owner=m.owner,
            msg_ids=json.loads(m.msg_ids),
            timestamp=m.timestamp,
        )


@dataclass
class FolderRecord:
    """Represents a storage folder (Telegram channel)."""
    name: str
    channel_id: int
    owner: str = "default"
    parent_id: Optional[int] = None
    created_at: float = 0.0
    id: Optional[int] = None

    @staticmethod
    def from_model(m: FolderModel) -> "FolderRecord":
        return FolderRecord(
            id=m.id,
            name=m.name,
            channel_id=m.channel_id,
            owner=m.owner,
            parent_id=m.parent_id,
            created_at=m.created_at,
        )


# ──────────────────────────────────────────────
# Database manager
# ──────────────────────────────────────────────
class Database:
    """SQLAlchemy-based database wrapper. Uses Postgres if DATABASE_URL is set, else SQLite."""

    def __init__(self) -> None:
        self._engine = None
        self._SessionLocal = None

    def connect(self) -> None:
        if DATABASE_URL:
            url = DATABASE_URL
            # Railway sometimes provides postgres:// but SQLAlchemy needs postgresql://
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            log.info("SYSTEM: Connecting to PostgreSQL...")
            self._engine = create_engine(url, pool_pre_ping=True)
        else:
            log.info("SYSTEM: No DATABASE_URL found, falling back to SQLite at %s", DB_PATH)
            self._engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

        self._SessionLocal = sessionmaker(bind=self._engine)
        Base.metadata.create_all(self._engine)
        log.info("SYSTEM: Database tables created/verified.")

    def close(self) -> None:
        if self._engine:
            self._engine.dispose()
            self._engine = None

    def _session(self) -> Session:
        assert self._SessionLocal is not None
        return self._SessionLocal()

    # --- Files CRUD ----------------------------------------------------------
    def upsert_file(self, record: FileRecord) -> None:
        with self._session() as session:
            existing = session.query(FileModel).filter_by(
                path=record.path, folder=record.folder, owner=record.owner
            ).first()
            if existing:
                existing.hash = record.hash
                existing.size = record.size
                existing.chunks = record.chunks
                existing.msg_ids = record.msg_ids_json()
                existing.timestamp = time.time()
            else:
                session.add(FileModel(
                    path=record.path,
                    hash=record.hash,
                    size=record.size,
                    chunks=record.chunks,
                    folder=record.folder,
                    owner=record.owner,
                    msg_ids=record.msg_ids_json(),
                    timestamp=time.time(),
                ))
            session.commit()

    def get_file(self, path: str, folder: str, owner: str) -> Optional[FileRecord]:
        with self._session() as session:
            m = session.query(FileModel).filter_by(
                path=path, folder=folder, owner=owner
            ).first()
            return FileRecord.from_model(m) if m else None

    def get_files_in_folder(self, folder: str, owner: str) -> List[FileRecord]:
        with self._session() as session:
            models = session.query(FileModel).filter_by(
                folder=folder, owner=owner
            ).order_by(FileModel.path).all()
            return [FileRecord.from_model(m) for m in models]

    def get_all_files(self, owner: str) -> List[FileRecord]:
        with self._session() as session:
            models = session.query(FileModel).filter_by(
                owner=owner
            ).order_by(FileModel.folder, FileModel.path).all()
            return [FileRecord.from_model(m) for m in models]

    def delete_file(self, path: str, folder: str, owner: str) -> None:
        with self._session() as session:
            session.query(FileModel).filter_by(
                path=path, folder=folder, owner=owner
            ).delete()
            session.commit()

    def delete_files_in_folder(self, folder: str, owner: str) -> None:
        with self._session() as session:
            session.query(FileModel).filter_by(
                folder=folder, owner=owner
            ).delete()
            session.commit()

    def get_total_storage(self, owner: str) -> int:
        with self._session() as session:
            result = session.query(func.coalesce(func.sum(FileModel.size), 0)).filter_by(
                owner=owner
            ).scalar()
            return int(result)

    # --- Folders CRUD --------------------------------------------------------
    def upsert_folder(self, record: FolderRecord) -> None:
        with self._session() as session:
            existing = session.query(FolderModel).filter_by(
                name=record.name, parent_id=record.parent_id, owner=record.owner
            ).first()
            if existing:
                existing.channel_id = record.channel_id
            else:
                session.add(FolderModel(
                    name=record.name,
                    channel_id=record.channel_id,
                    owner=record.owner,
                    parent_id=record.parent_id,
                    created_at=time.time(),
                ))
            session.commit()
            # Return the ID of the upserted folder
            if existing:
                return existing.id
            created = session.query(FolderModel).filter_by(
                name=record.name, parent_id=record.parent_id, owner=record.owner
            ).first()
            return created.id if created else None

    def get_folder(self, name: str, owner: str, parent_id: Optional[int] = None) -> Optional[FolderRecord]:
        with self._session() as session:
            m = session.query(FolderModel).filter_by(
                name=name, parent_id=parent_id, owner=owner
            ).first()
            return FolderRecord.from_model(m) if m else None

    def get_folder_by_id(self, folder_id: int, owner: str) -> Optional[FolderRecord]:
        with self._session() as session:
            m = session.query(FolderModel).filter_by(
                id=folder_id, owner=owner
            ).first()
            return FolderRecord.from_model(m) if m else None

    def get_child_folders(self, parent_id: Optional[int], owner: str) -> List[FolderRecord]:
        """Get all direct child folders of the given parent."""
        with self._session() as session:
            models = session.query(FolderModel).filter_by(
                parent_id=parent_id, owner=owner
            ).order_by(FolderModel.name).all()
            return [FolderRecord.from_model(m) for m in models]

    def get_folder_path(self, folder_id: int, owner: str) -> List[FolderRecord]:
        """Return the full path from root to the given folder (breadcrumb chain)."""
        path = []
        current_id = folder_id
        while current_id is not None:
            folder = self.get_folder_by_id(current_id, owner)
            if folder is None:
                break
            path.append(folder)
            current_id = folder.parent_id
        path.reverse()
        return path

    def get_all_folders(self, owner: str) -> List[FolderRecord]:
        with self._session() as session:
            models = session.query(FolderModel).filter_by(
                owner=owner
            ).order_by(FolderModel.name).all()
            return [FolderRecord.from_model(m) for m in models]

    def delete_folder(self, name: str, owner: str) -> None:
        with self._session() as session:
            session.query(FolderModel).filter_by(
                name=name, owner=owner
            ).delete()
            session.commit()

    def rename_folder(self, old_name: str, new_name: str, owner: str) -> None:
        with self._session() as session:
            session.query(FolderModel).filter_by(
                name=old_name, owner=owner
            ).update({"name": new_name})
            session.query(FileModel).filter_by(
                folder=old_name, owner=owner
            ).update({"folder": new_name})
            session.commit()

    # --- Users CRUD ----------------------------------------------------------
    def create_user(self, username: str, password_hash: str) -> None:
        with self._session() as session:
            existing = session.query(UserModel).filter_by(username=username).first()
            if existing:
                existing.password_hash = password_hash
            else:
                session.add(UserModel(
                    username=username,
                    password_hash=password_hash,
                    created_at=time.time(),
                ))
            session.commit()

    def get_user(self, username: str) -> Optional[UserModel]:
        with self._session() as session:
            return session.query(UserModel).filter_by(username=username).first()

    # --- Bulk operations (for DB rebuild) ------------------------------------
    def clear_owner_data(self, owner: str) -> None:
        """Clear all files and folders for an owner (before rebuild)."""
        with self._session() as session:
            session.query(FileModel).filter_by(owner=owner).delete()
            session.query(FolderModel).filter_by(owner=owner).delete()
            session.commit()
