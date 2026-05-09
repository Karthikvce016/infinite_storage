"""
PyQt6 user interface package for Telegram Drive.

Exposes main window, dialogs, and styles from submodules.
"""

from ui.dialogs import LoginDialog, PassphraseDialog
from ui.main_window import DropZone, MainWindow
from ui.styles import STYLESHEET

__all__ = [
    "LoginDialog",
    "PassphraseDialog",
    "MainWindow",
    "DropZone",
    "STYLESHEET",
]
