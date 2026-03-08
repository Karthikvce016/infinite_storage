"""
sync_manager.py – Orchestrator for Telegram Drive sync operations.

Coordinates:
    encrypt → split → upload → DB update        (file added / modified)
    Telegram delete → DB remove                  (file deleted)
    download → merge → decrypt → temp            (per-file download)
    download → merge → decrypt → write           (batch restore)

Runs an asyncio event loop inside a QThread so the UI stays responsive.

CRITICAL DESIGN NOTE:
    The Telethon TelegramClient MUST live on the same asyncio event loop
    it was created on.  Therefore the client is created & connected inside
    this thread's ``run()`` method, and all Telegram I/O is scheduled on
    that loop via ``run_coroutine_threadsafe()``.
"""

import asyncio
import concurrent.futures
import logging
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from core.chunk_manager import compute_hash, split_file, merge_chunks, cleanup_chunks
from config.settings import TEMP_DIR
from core.crypto_manager import derive_key, encrypt_file, decrypt_file
from storage.database import Database, FileRecord
from core.downloader import download_chunks
from core.file_watcher import FileWatcher
from core.telegram_client import TelegramDriveClient
from core.uploader import upload_chunks, delete_messages

log = logging.getLogger(__name__)


def _is_hidden(name: str) -> bool:
    """Return True if the filename starts with a dot."""
    return name.startswith(".")


class SyncManager(QThread):
    """
    Background thread that owns the asyncio event loop and processes
    sync tasks (upload / delete / restore) without blocking the GUI.

    The Telethon client is created **inside** this thread's loop so it
    never sees a loop change.
    """

    # Signals → UI
    status_update = pyqtSignal(str)             # human-readable status text
    progress_update = pyqtSignal(int)          # 0-100 percentage
    file_list_changed = pyqtSignal()           # tell UI to refresh the list
    error_occurred = pyqtSignal(str)           # error messages
    connected = pyqtSignal()                   # fired after TG connect succeeds
    login_required = pyqtSignal()              # fired when TG session is not authorised
    # Emitted when a single file has been downloaded to a temp path.
    # Args: (db_file_path: str, temp_file_path: str)
    file_downloaded = pyqtSignal(str, str)
    # Emitted when a file is ready for preview (opened with default app).
    file_previewed = pyqtSignal(str, str)

    def __init__(
        self,
        tg_client: TelegramDriveClient,
        db: Database,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._tg = tg_client
        self._db = db
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._sync_folder: Optional[Path] = None
        self._passphrase: str = ""
        self._key: Optional[bytes] = None
        self._ready = False

        # File watcher
        self.watcher = FileWatcher()
        self.watcher.signals.file_created.connect(self._on_file_created)
        self.watcher.signals.file_modified.connect(self._on_file_modified)
        self.watcher.signals.file_deleted.connect(self._on_file_deleted)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def set_sync_folder(self, folder: Path) -> None:
        self._sync_folder = folder
        folder.mkdir(parents=True, exist_ok=True)

    def set_passphrase(self, passphrase: str) -> None:
        self._passphrase = passphrase
        self._key = derive_key(passphrase)

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------
    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._tg.create_and_connect())
            log.info("Telegram client connected on background loop")
        except Exception as exc:
            log.exception("Failed to connect Telegram client")
            self.error_occurred.emit(f"Telegram connection failed: {exc}")
            return

        try:
            authorized = self._loop.run_until_complete(self._tg.is_authorized())
        except Exception:
            authorized = False

        if not authorized:
            self.login_required.emit()
            self._loop.run_forever()
        else:
            try:
                self._loop.run_until_complete(self._tg.ensure_channel())
                self._ready = True
                self.connected.emit()
            except Exception as exc:
                self.error_occurred.emit(f"Channel setup failed: {exc}")
            self._loop.run_forever()

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._tg.disconnect(), self._loop)
            try:
                future.result(timeout=5)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.watcher.stop()
        self.wait()

    # ------------------------------------------------------------------
    # Public API (called from the UI thread, thread-safe)
    # ------------------------------------------------------------------
    def schedule_send_code(self, phone: str) -> concurrent.futures.Future:
        return self._schedule_future(self._tg.send_code(phone))

    def schedule_sign_in(self, phone: str, code: str, phone_code_hash: str) -> concurrent.futures.Future:
        return self._schedule_future(self._tg.sign_in(phone, code, phone_code_hash))

    def schedule_ensure_channel(self) -> concurrent.futures.Future:
        async def _do():
            await self._tg.ensure_channel()
            self._ready = True
            self.connected.emit()

        return self._schedule_future(_do())

    def start_watching(self) -> None:
        if self._sync_folder:
            self.watcher.start(self._sync_folder)
            self._schedule(self._initial_scan())

    def request_restore_all(self) -> None:
        self._schedule(self._restore_all())

    def request_manual_upload(self, paths: list[Path]) -> None:
        """Upload drag-dropped or picked files. Folders are expanded. Hidden files are skipped."""
        self._schedule(self._manual_upload(paths))

    def request_download_file(self, db_path: str) -> None:
        """
        Download a single file by its DB path to a temporary location,
        then emit ``file_downloaded(db_path, temp_path)`` so the UI can
        prompt the user with a Save-As dialog.
        """
        self._schedule(self._download_single(db_path))

    def request_preview_file(self, db_path: str) -> None:
        """
        Download a single file to temp and emit ``file_previewed`` so the
        UI can open it with the system's default application.
        """
        self._schedule(self._preview_single(db_path))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _schedule(self, coro) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _schedule_future(self, coro) -> concurrent.futures.Future:
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ------------------------------------------------------------------
    # Download a single file to temp (user saves manually)
    # ------------------------------------------------------------------
    async def _download_single(self, db_path: str) -> None:
        """Download one file's chunks, merge, decrypt to TEMP_DIR, then signal the UI."""
        record = self._db.get_file(db_path)
        if record is None:
            self.error_occurred.emit(f"File not found in index: {db_path}")
            return
        if not self._key:
            self.error_occurred.emit("Encryption key not set.")
            return
        try:
            self.status_update.emit(f"Downloading {db_path}…")
            self.progress_update.emit(0)
            channel = await self._tg.ensure_channel()

            chunk_paths = await download_chunks(self._tg.client, channel, record.msg_ids)
            self.progress_update.emit(60)

            # Merge chunks
            merged_enc = TEMP_DIR / f"{Path(db_path).name}.enc"
            merge_chunks(chunk_paths, merged_enc)
            self.progress_update.emit(80)

            # Decrypt to temp
            decrypted = TEMP_DIR / Path(db_path).name
            decrypt_file(merged_enc, decrypted, self._key)
            self.progress_update.emit(100)

            # Cleanup intermediate files
            cleanup_chunks(chunk_paths)
            merged_enc.unlink(missing_ok=True)

            self.status_update.emit(f"Downloaded {db_path} ✓  (choose where to save)")
            # Tell the UI so it can show a Save-As dialog
            self.file_downloaded.emit(db_path, str(decrypted))

        except Exception as exc:
            log.exception("Download failed for %s", db_path)
            self.error_occurred.emit(f"Download failed for {db_path}: {exc}")

    # ------------------------------------------------------------------
    # Preview a file (download to temp, open with default app)
    # ------------------------------------------------------------------
    async def _preview_single(self, db_path: str) -> None:
        """Download, decrypt to temp, then signal the UI to open with default viewer."""
        record = self._db.get_file(db_path)
        if record is None:
            self.error_occurred.emit(f"File not found in index: {db_path}")
            return
        if not self._key:
            self.error_occurred.emit("Encryption key not set.")
            return
        try:
            self.status_update.emit(f"Downloading {db_path} for preview…")
            self.progress_update.emit(0)
            channel = await self._tg.ensure_channel()

            chunk_paths = await download_chunks(self._tg.client, channel, record.msg_ids)
            self.progress_update.emit(60)

            merged_enc = TEMP_DIR / f"{Path(db_path).name}.enc"
            merge_chunks(chunk_paths, merged_enc)
            self.progress_update.emit(80)

            decrypted = TEMP_DIR / Path(db_path).name
            decrypt_file(merged_enc, decrypted, self._key)
            self.progress_update.emit(100)

            cleanup_chunks(chunk_paths)
            merged_enc.unlink(missing_ok=True)

            self.status_update.emit(f"Opening {db_path} for preview…")
            self.file_previewed.emit(db_path, str(decrypted))

        except Exception as exc:
            log.exception("Preview failed for %s", db_path)
            self.error_occurred.emit(f"Preview failed for {db_path}: {exc}")

    # ------------------------------------------------------------------
    # Manual upload (drag-drop / file picker)
    # ------------------------------------------------------------------
    async def _manual_upload(self, paths: list[Path]) -> None:
        file_list: list[Path] = []
        for p in paths:
            if p.is_dir():
                file_list.extend(
                    f for f in p.rglob("*")
                    if f.is_file() and not _is_hidden(f.name)
                )
            elif p.is_file() and not _is_hidden(p.name):
                file_list.append(p)

        total = len(file_list)
        for idx, file_path in enumerate(file_list, 1):
            try:
                rel = file_path.name
                self.status_update.emit(f"Uploading {rel} ({idx}/{total})…")
                self.progress_update.emit(0)

                if not self._key:
                    self.error_occurred.emit("Encryption key not set.")
                    return

                new_hash = compute_hash(file_path)
                existing = self._db.get_file(rel)

                if existing and existing.hash == new_hash:
                    self.status_update.emit(f"Skipped {rel} (unchanged)")
                    continue

                if existing:
                    channel = await self._tg.ensure_channel()
                    await delete_messages(self._tg.client, channel, existing.msg_ids)

                self.status_update.emit(f"Encrypting {rel}…")
                enc_path = TEMP_DIR / f"{file_path.name}.enc"
                encrypt_file(file_path, enc_path, self._key)
                self.progress_update.emit(20)

                self.status_update.emit(f"Splitting {rel}…")
                chunk_paths = split_file(enc_path)
                self.progress_update.emit(30)

                self.status_update.emit(f"Uploading {rel} ({len(chunk_paths)} chunk(s))…")
                channel = await self._tg.ensure_channel()
                msg_ids = await upload_chunks(self._tg.client, channel, chunk_paths)
                self.progress_update.emit(90)

                record = FileRecord(
                    path=rel,
                    hash=new_hash,
                    size=file_path.stat().st_size,
                    chunks=len(chunk_paths),
                    msg_ids=msg_ids,
                )
                self._db.upsert_file(record)
                self.progress_update.emit(100)
                self.status_update.emit(f"Uploaded {rel} ✓")
                self.file_list_changed.emit()

                cleanup_chunks(chunk_paths)
                enc_path.unlink(missing_ok=True)

            except Exception as exc:
                log.exception("Manual upload failed for %s", file_path)
                self.error_occurred.emit(f"Upload failed for {file_path.name}: {exc}")

    # ------------------------------------------------------------------
    # Slot handlers (from watcher)
    # ------------------------------------------------------------------
    def _on_file_created(self, path_str: str) -> None:
        self._schedule(self._handle_upload(Path(path_str)))

    def _on_file_modified(self, path_str: str) -> None:
        self._schedule(self._handle_upload(Path(path_str)))

    def _on_file_deleted(self, path_str: str) -> None:
        self._schedule(self._handle_delete(path_str))

    # ------------------------------------------------------------------
    # Core async operations
    # ------------------------------------------------------------------
    async def _initial_scan(self) -> None:
        if not self._sync_folder:
            return
        self.status_update.emit("Scanning sync folder…")
        for item in self._sync_folder.rglob("*"):
            if item.is_file() and not _is_hidden(item.name):
                rel = str(item.relative_to(self._sync_folder))
                record = self._db.get_file(rel)
                current_hash = compute_hash(item)
                if record is None or record.hash != current_hash:
                    await self._handle_upload(item)
        self.status_update.emit("Initial scan complete")

    async def _handle_upload(self, file_path: Path) -> None:
        if not file_path.exists() or not self._sync_folder or not self._key:
            return
        # Skip hidden files
        if _is_hidden(file_path.name):
            return
        try:
            rel = str(file_path.relative_to(self._sync_folder))
        except ValueError:
            return
        try:
            self.status_update.emit(f"Processing {rel}…")
            self.progress_update.emit(0)

            new_hash = compute_hash(file_path)
            existing = self._db.get_file(rel)
            if existing and existing.hash == new_hash:
                return

            if existing:
                channel = await self._tg.ensure_channel()
                await delete_messages(self._tg.client, channel, existing.msg_ids)

            self.status_update.emit(f"Encrypting {rel}…")
            enc_path = TEMP_DIR / f"{file_path.name}.enc"
            encrypt_file(file_path, enc_path, self._key)
            self.progress_update.emit(20)

            self.status_update.emit(f"Splitting {rel}…")
            chunk_paths = split_file(enc_path)
            self.progress_update.emit(30)

            self.status_update.emit(f"Uploading {rel} ({len(chunk_paths)} chunk(s))…")
            channel = await self._tg.ensure_channel()
            msg_ids = await upload_chunks(self._tg.client, channel, chunk_paths)
            self.progress_update.emit(90)

            record = FileRecord(
                path=rel,
                hash=new_hash,
                size=file_path.stat().st_size,
                chunks=len(chunk_paths),
                msg_ids=msg_ids,
            )
            self._db.upsert_file(record)
            self.progress_update.emit(100)
            self.status_update.emit(f"Uploaded {rel} ✓")
            self.file_list_changed.emit()

            cleanup_chunks(chunk_paths)
            enc_path.unlink(missing_ok=True)

        except Exception as exc:
            log.exception("Upload failed for %s", file_path)
            self.error_occurred.emit(f"Upload failed: {exc}")

    async def _handle_delete(self, path_str: str) -> None:
        if not self._sync_folder:
            return
        try:
            rel = str(Path(path_str).relative_to(self._sync_folder))
        except ValueError:
            return
        record = self._db.get_file(rel)
        if record is None:
            return
        try:
            self.status_update.emit(f"Deleting {rel} from Telegram…")
            channel = await self._tg.ensure_channel()
            await delete_messages(self._tg.client, channel, record.msg_ids)
            self._db.delete_file(rel)
            self.status_update.emit(f"Deleted {rel} ✓")
            self.file_list_changed.emit()
        except Exception as exc:
            log.exception("Delete failed for %s", rel)
            self.error_occurred.emit(f"Delete failed: {exc}")

    async def _restore_all(self) -> None:
        if not self._sync_folder or not self._key:
            return
        records = self._db.get_all_files()
        total = len(records)
        for idx, rec in enumerate(records, 1):
            try:
                dest = self._sync_folder / rec.path
                if dest.exists():
                    if compute_hash(dest) == rec.hash:
                        continue

                self.status_update.emit(f"Restoring {rec.path} ({idx}/{total})…")
                channel = await self._tg.ensure_channel()

                chunk_paths = await download_chunks(self._tg.client, channel, rec.msg_ids)

                merged = TEMP_DIR / f"{Path(rec.path).name}.enc"
                merge_chunks(chunk_paths, merged)

                dest.parent.mkdir(parents=True, exist_ok=True)
                decrypt_file(merged, dest, self._key)

                self.progress_update.emit(int(idx / total * 100))
                self.status_update.emit(f"Restored {rec.path} ✓")

                cleanup_chunks(chunk_paths)
                merged.unlink(missing_ok=True)

            except Exception as exc:
                log.exception("Restore failed for %s", rec.path)
                self.error_occurred.emit(f"Restore failed for {rec.path}: {exc}")

        self.file_list_changed.emit()
        self.status_update.emit("Restore complete")

