"""
settings.py – Central configuration constants for Telegram Drive.

Replace API_ID and API_HASH with your own values from https://my.telegram.org.
"""

from pathlib import Path

# ──────────────────────────────────────────────
# Telegram API credentials (REQUIRED)
# ──────────────────────────────────────────────
API_ID: int = 32544391            # <-- replace with your api_id
API_HASH: str = "6d97d692d02fa60805dfac5cf39b8dc6"         # <-- replace with your api_hash
SESSION_NAME: str = "telegram_drive_session"

# ──────────────────────────────────────────────
# Storage channel
# ──────────────────────────────────────────────
CHANNEL_NAME: str = "TelegramDriveStorage"

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
APP_DIR: Path = Path.home() / ".telegram_drive"
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
# Encryption
# ──────────────────────────────────────────────
PBKDF2_ITERATIONS: int = 600_000
SALT_FILE: Path = APP_DIR / "salt.bin"
