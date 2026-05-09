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

# ──────────────────────────────────────────────
# Storage channel
# ──────────────────────────────────────────────
CHANNEL_NAME: str = os.getenv("CHANNEL_NAME", "TelegramDriveStorage")

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
# Project root = parent of config/
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# APP_DIR stores session, DB, salt, and temp files.
# On Render: set APP_DATA_DIR=/var/data (persistent disk mount).
# Locally:   defaults to the project root.
APP_DIR: Path = Path(os.getenv("APP_DATA_DIR", str(_PROJECT_ROOT)))
APP_DIR.mkdir(parents=True, exist_ok=True)

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
# JWT Authentication
# ──────────────────────────────────────────────
import secrets as _secrets

JWT_SECRET: str = os.getenv("JWT_SECRET", "")
if not JWT_SECRET:
    # Auto-generate a secret for local dev (persisted per-process only)
    _secret_file = APP_DIR / ".jwt_secret"
    if _secret_file.exists():
        JWT_SECRET = _secret_file.read_text().strip()
    else:
        JWT_SECRET = _secrets.token_hex(32)
        _secret_file.write_text(JWT_SECRET)

JWT_EXPIRY_DAYS: int = int(os.getenv("JWT_EXPIRY_DAYS", "7"))
