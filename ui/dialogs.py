"""
dialogs.py – Login, passphrase, and related dialogs for Telegram Drive.
"""

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.telegram_client import TelegramDriveClient
from ui.styles import TEXT_DIM


class LoginDialog(QDialog):
    """
    Two-step Telegram login: phone → OTP code.
    All calls routed through SyncManager's background loop.
    """

    def __init__(self, tg_client: TelegramDriveClient, sync_manager, parent=None) -> None:
        super().__init__(parent)
        self._tg = tg_client
        self._sync = sync_manager
        self._phone_hash: Optional[str] = None
        self._phone: str = ""
        self.setWindowTitle("Telegram Drive – Login")
        self.setFixedSize(420, 300)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 32, 32, 32)

        title = QLabel("🔐  Telegram Login")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._phone_input = QLineEdit()
        self._phone_input.setPlaceholderText("Phone number (e.g. +91…)")
        layout.addWidget(self._phone_input)

        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("OTP code")
        self._code_input.setEnabled(False)
        layout.addWidget(self._code_input)

        self._btn_send = QPushButton("Send Code")
        self._btn_send.clicked.connect(self._send_code)
        layout.addWidget(self._btn_send)

        self._btn_verify = QPushButton("Verify & Login")
        self._btn_verify.setEnabled(False)
        self._btn_verify.clicked.connect(self._verify_code)
        layout.addWidget(self._btn_verify)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")
        layout.addWidget(self._status)

    def _send_code(self) -> None:
        self._phone = self._phone_input.text().strip()
        if not self._phone:
            return
        try:
            future = self._sync.schedule_send_code(self._phone)
            self._phone_hash = future.result(timeout=30)
            self._status.setText("Code sent! Check Telegram.")
            self._code_input.setEnabled(True)
            self._btn_verify.setEnabled(True)
            self._btn_send.setEnabled(False)
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _verify_code(self) -> None:
        code = self._code_input.text().strip()
        if not code or not self._phone_hash:
            return
        try:
            future = self._sync.schedule_sign_in(self._phone, code, self._phone_hash)
            future.result(timeout=30)
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Login Failed", str(exc))


class PassphraseDialog(QDialog):
    """Prompt the user for an encryption passphrase."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Encryption Passphrase")
        self.setFixedSize(420, 220)
        self.passphrase: str = ""
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(32, 32, 32, 32)

        title = QLabel("🔑  Set Encryption Passphrase")
        title.setFont(QFont("Inter", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("This passphrase encrypts your files with AES-256.\nRemember it – without it, files cannot be decrypted.")
        hint.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Enter passphrase…")
        self._input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._input)

        btn = QPushButton("Continue")
        btn.clicked.connect(self._on_submit)
        layout.addWidget(btn)

    def _on_submit(self) -> None:
        text = self._input.text().strip()
        if len(text) < 4:
            QMessageBox.warning(self, "Too short", "Passphrase must be at least 4 characters.")
            return
        self.passphrase = text
        self.accept()
