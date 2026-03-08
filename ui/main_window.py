"""
main_window.py – Primary PyQt application window for Telegram Drive.
"""

import shutil
from pathlib import Path
from typing import List

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QFont, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QDesktopServices

from config.settings import DEFAULT_SYNC_FOLDER
from core.sync_manager import SyncManager
from core.telegram_client import TelegramDriveClient
from storage.database import Database
from ui.styles import DROP_BORDER, DROP_BORDER_ACTIVE, SURFACE, TEXT_DIM


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


class DropZone(QFrame):
    """
    A visual drag-and-drop area. When files or folders are dropped
    onto it, the parent MainWindow receives the list of paths and
    forwards them to the SyncManager for manual upload.
    """

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self._main = parent
        self.setAcceptDrops(True)
        self.setMinimumHeight(90)
        self._set_idle_style()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel("📂")
        icon_label.setFont(QFont("Inter", 28))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(icon_label)

        text_label = QLabel("Drag files or folders here to upload")
        text_label.setFont(QFont("Inter", 13, QFont.Weight.Medium))
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_label.setStyleSheet(
            f"color: {TEXT_DIM}; border: none; background: transparent;"
        )
        layout.addWidget(text_label)

    def _set_idle_style(self) -> None:
        self.setStyleSheet(
            f"DropZone {{ background-color: {SURFACE}; "
            f"border: 2px dashed {DROP_BORDER}; border-radius: 10px; }}"
        )

    def _set_active_style(self) -> None:
        self.setStyleSheet(
            f"DropZone {{ background-color: #2d2d50; "
            f"border: 2px solid {DROP_BORDER_ACTIVE}; border-radius: 10px; }}"
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_active_style()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_idle_style()

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_idle_style()
        if not event.mimeData() or not event.mimeData().hasUrls():
            return
        paths: List[Path] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(Path(local))
        if paths:
            self._main.handle_manual_upload(paths)


class MainWindow(QMainWindow):
    """
    Primary application window.

    Supports three workflows:
        A) Folder sync  – pick a folder, watchdog auto-syncs changes.
        B) Manual upload – pick files via dialog OR drag-and-drop.
        C) Selective download – click Download on any file row → Save-As.
    """

    def __init__(
        self,
        tg_client: TelegramDriveClient,
        db: Database,
        sync_manager: SyncManager,
    ) -> None:
        super().__init__()
        self._tg = tg_client
        self._db = db
        self._sync = sync_manager

        self.setWindowTitle("Telegram Drive")
        self.setMinimumSize(780, 660)
        self.setAcceptDrops(True)

        self._build_ui()
        self._connect_signals()
        self._refresh_file_list()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(14)
        root.setContentsMargins(28, 28, 28, 28)

        header = QLabel("☁️  Telegram Drive")
        header.setFont(QFont("Inter", 22, QFont.Weight.Bold))
        root.addWidget(header)

        folder_row = QHBoxLayout()
        self._folder_label = QLabel(f"Sync Folder: {DEFAULT_SYNC_FOLDER}")
        self._folder_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 13px;")
        folder_row.addWidget(self._folder_label, 1)

        browse_folder_btn = QPushButton("Sync Folder")
        browse_folder_btn.setObjectName("secondaryBtn")
        browse_folder_btn.setFixedWidth(110)
        browse_folder_btn.setToolTip("Select a folder for automatic sync (Workflow A)")
        browse_folder_btn.clicked.connect(self._pick_folder)
        folder_row.addWidget(browse_folder_btn)

        upload_files_btn = QPushButton("Upload Files")
        upload_files_btn.setFixedWidth(110)
        upload_files_btn.setToolTip("Pick individual files to upload now (Workflow B)")
        upload_files_btn.clicked.connect(self._pick_files)
        folder_row.addWidget(upload_files_btn)

        root.addLayout(folder_row)

        self._drop_zone = DropZone(self)
        root.addWidget(self._drop_zone)

        self._status_label = QLabel("Status: Idle")
        self._status_label.setStyleSheet("font-size: 14px; font-weight: 500;")
        root.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setValue(0)
        root.addWidget(self._progress)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["File", "Size", "Chunks", "Hash", "", ""])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        root.addWidget(self._table, 1)

        bottom = QHBoxLayout()
        self._storage_label = QLabel("Storage: 0 B")
        self._storage_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")
        bottom.addWidget(self._storage_label)
        bottom.addStretch()

        start_btn = QPushButton("Start Sync")
        start_btn.setFixedWidth(120)
        start_btn.clicked.connect(self._on_start_sync)
        bottom.addWidget(start_btn)
        root.addLayout(bottom)

    def _connect_signals(self) -> None:
        self._sync.status_update.connect(self._set_status)
        self._sync.progress_update.connect(self._progress.setValue)
        self._sync.file_list_changed.connect(self._refresh_file_list)
        self._sync.error_occurred.connect(
            lambda msg: QMessageBox.warning(self, "Error", msg)
        )
        self._sync.file_downloaded.connect(self._on_file_downloaded)
        self._sync.file_previewed.connect(self._on_file_previewed)

    def _set_status(self, text: str) -> None:
        self._status_label.setText(f"Status: {text}")

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Sync Folder")
        if folder:
            self._folder_label.setText(f"Sync Folder: {folder}")
            self._sync.set_sync_folder(Path(folder))

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Files to Upload",
            str(Path.home()),
            "All Files (*)",
        )
        if paths:
            self.handle_manual_upload([Path(p) for p in paths])

    def handle_manual_upload(self, paths: List[Path]) -> None:
        if not paths:
            return
        names = ", ".join(p.name for p in paths[:3])
        if len(paths) > 3:
            names += f" … (+{len(paths) - 3} more)"
        self._set_status(f"Queuing: {names}")

        if not self._sync.isRunning():
            self._sync.start()
            QTimer.singleShot(200, lambda: self._sync.request_manual_upload(paths))
        else:
            self._sync.request_manual_upload(paths)

    def _on_start_sync(self) -> None:
        if not self._sync._sync_folder:
            self._sync.set_sync_folder(DEFAULT_SYNC_FOLDER)
        if not self._sync.isRunning():
            self._sync.start()
            QTimer.singleShot(200, self._sync.start_watching)
        else:
            self._sync.start_watching()

    def _on_view_clicked(self, db_path: str) -> None:
        self._set_status(f"Preparing preview for {db_path}…")
        self._sync.request_preview_file(db_path)

    def _on_file_previewed(self, db_path: str, temp_path: str) -> None:
        url = QUrl.fromLocalFile(temp_path)
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(self, "Preview", f"Could not open {db_path}")
        else:
            self._set_status(f"Previewing {db_path} – save via Download if you want to keep it")

    def _on_download_clicked(self, db_path: str) -> None:
        self._set_status(f"Downloading {db_path}…")
        self._sync.request_download_file(db_path)

    def _on_file_downloaded(self, db_path: str, temp_path: str) -> None:
        src = Path(temp_path)
        if not src.exists():
            QMessageBox.warning(self, "Error", f"Temp file not found: {temp_path}")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Save {db_path}",
            str(Path.home() / Path(db_path).name),
            "All Files (*)",
        )
        if save_path:
            try:
                shutil.copy2(str(src), save_path)
                self._set_status(f"Saved {db_path} → {save_path}")
            except Exception as exc:
                QMessageBox.warning(self, "Save failed", str(exc))
        else:
            self._set_status(f"Download of {db_path} cancelled (not saved)")

        src.unlink(missing_ok=True)

    def _refresh_file_list(self) -> None:
        records = self._db.get_all_files()
        visible = [r for r in records if not r.path.startswith(".")]

        self._table.setRowCount(len(visible))
        for row, rec in enumerate(visible):
            self._table.setItem(row, 0, QTableWidgetItem(rec.path))
            self._table.setItem(row, 1, QTableWidgetItem(_fmt_size(rec.size)))
            self._table.setItem(row, 2, QTableWidgetItem(str(rec.chunks)))
            self._table.setItem(row, 3, QTableWidgetItem(rec.hash[:16] + "…"))

            view_btn = QPushButton("👁 View")
            view_btn.setObjectName("viewBtn")
            view_btn.clicked.connect(lambda _checked, p=rec.path: self._on_view_clicked(p))
            self._table.setCellWidget(row, 4, view_btn)

            dl_btn = QPushButton("⬇ Save")
            dl_btn.setObjectName("downloadBtn")
            dl_btn.clicked.connect(lambda _checked, p=rec.path: self._on_download_clicked(p))
            self._table.setCellWidget(row, 5, dl_btn)

        total = sum(r.size for r in visible)
        self._storage_label.setText(f"Storage used: {_fmt_size(total)}")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData() or not event.mimeData().hasUrls():
            return
        paths: List[Path] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(Path(local))
        if paths:
            self.handle_manual_upload(paths)

    def closeEvent(self, event) -> None:
        self._sync.stop()
        super().closeEvent(event)
