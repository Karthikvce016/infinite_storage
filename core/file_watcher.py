"""
file_watcher.py – watchdog-based folder monitor for Telegram Drive.

Emits PyQt6 signals for file creation, modification, deletion, and moves
so that the SyncManager can react without polling.

Hidden files (names starting with '.') are silently ignored.
"""

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

log = logging.getLogger(__name__)


def _is_hidden(path_str: str) -> bool:
    """Return True if any component of the path starts with '.'."""
    for part in Path(path_str).parts:
        if part.startswith("."):
            return True
    return False


class _Handler(FileSystemEventHandler):
    """Translates watchdog events into Qt signals, skipping hidden files."""

    def __init__(self, signals: "FileWatcherSignals") -> None:
        super().__init__()
        self._sig = signals

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory or _is_hidden(event.src_path):
            return
        log.debug("File created: %s", event.src_path)
        self._sig.file_created.emit(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory or _is_hidden(event.src_path):
            return
        log.debug("File modified: %s", event.src_path)
        self._sig.file_modified.emit(event.src_path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory or _is_hidden(event.src_path):
            return
        log.debug("File deleted: %s", event.src_path)
        self._sig.file_deleted.emit(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if _is_hidden(event.src_path):
            # Old path was hidden; if new path is visible, treat as create
            if not _is_hidden(event.dest_path):
                self._sig.file_created.emit(event.dest_path)
            return
        log.debug("File moved: %s → %s", event.src_path, event.dest_path)
        self._sig.file_deleted.emit(event.src_path)
        if not _is_hidden(event.dest_path):
            self._sig.file_created.emit(event.dest_path)


class FileWatcherSignals(QObject):
    """Qt signals emitted by the file watcher."""

    file_created = pyqtSignal(str)
    file_modified = pyqtSignal(str)
    file_deleted = pyqtSignal(str)


class FileWatcher:
    """Watches a directory for file-level changes."""

    def __init__(self) -> None:
        self.signals = FileWatcherSignals()
        self._observer = Observer()
        self._handler = _Handler(self.signals)
        self._watching = False

    def start(self, folder: Path) -> None:
        if self._watching:
            self.stop()
        folder.mkdir(parents=True, exist_ok=True)
        self._observer = Observer()
        self._observer.schedule(self._handler, str(folder), recursive=True)
        self._observer.start()
        self._watching = True
        log.info("Watching folder: %s", folder)

    def stop(self) -> None:
        if self._watching:
            self._observer.stop()
            self._observer.join()
            self._watching = False
            log.info("Stopped file watcher")

