"""
settings.py – Central configuration constants for Telegram Drive.

All sensitive values are loaded from environment variables.
For local development, create a `.env` file in the project root
(see `.env.example` for the required keys).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# Telegram API credentials (REQUIRED)
# ──────────────────────────────────────────────
API_ID: int = int(os.getenv("API_ID", "0"))
API_HASH: str = os.getenv("API_HASH", "")
SESSION_NAME: str = os.getenv("SESSION_NAME", "telegram_drive_session")

# ──────────────────────────────────────────────
# Storage channel
# ──────────────────────────────────────────────
CHANNEL_NAME: str = os.getenv("CHANNEL_NAME", "TelegramDriveStorage")

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
# Project root = parent of config/
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

APP_DIR: Path = _PROJECT_ROOT

DB_PATH: Path = APP_DIR / "index.db"
DEFAULT_SYNC_FOLDER: Path = Path.home() / "TelegramDrive"
TEMP_DIR: Path = APP_DIR / "tmp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────
# Chunk settings
# ──────────────────────────────────────────────
CHUNK_SIZE: int = int(1.9 * 1024 * 1024 * 1024)  # 1.9 GB in bytes

# ──────────────────────────────────────────────
# Upload / download concurrency
# ──────────────────────────────────────────────
MAX_CONCURRENT_UPLOADS: int = 3
MAX_CONCURRENT_DOWNLOADS: int = 3

# ──────────────────────────────────────────────
# Encryption
# ──────────────────────────────────────────────
PBKDF2_ITERATIONS: int = 600_000
SALT_FILE: Path = APP_DIR / "salt.bin"
