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
# Env helpers — a blank value ("KEY=" in .env) is treated as unset.
# Without this, an empty numeric key would raise at import time and the whole
# app would fail to boot.
# ──────────────────────────────────────────────
def env_str(name: str, default: str = "") -> str:
    """Read a string env var, falling back when it is missing or blank."""
    value = os.getenv(name)
    return value if value is not None and value.strip() else default


def env_int(name: str, default: int) -> int:
    """Read an int env var, falling back when it is missing, blank or invalid."""
    raw = env_str(name)
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    """Read a float env var, falling back when it is missing, blank or invalid."""
    raw = env_str(name)
    try:
        return float(raw)
    except ValueError:
        return default


# ──────────────────────────────────────────────
# Telegram API credentials (REQUIRED)
# ──────────────────────────────────────────────
API_ID: int = env_int("API_ID", 0)
API_HASH: str = env_str("API_HASH")

# Bot token from @BotFather (used for Bot API mode)
BOT_TOKEN: str = env_str("BOT_TOKEN")

# User session string (used for full API access — bots can't create channels)
# Generate via: python generate_session.py
SESSION_STRING: str = env_str("SESSION_STRING")

# The channel where the bot stores files.
# Can be a numeric ID (e.g. -1001234567890) or a username (e.g. @my_storage).
STORAGE_CHANNEL_ID: str = env_str("STORAGE_CHANNEL_ID")

# ──────────────────────────────────────────────
# Web auth – simple password for personal use
# ──────────────────────────────────────────────
APP_PASSWORD: str = env_str("APP_PASSWORD", "admin")

# ──────────────────────────────────────────────
# PostgreSQL (Railway / Supabase / local)
# ──────────────────────────────────────────────
DATABASE_URL: str = env_str("DATABASE_URL")

# ──────────────────────────────────────────────
# Folder prefix used to identify storage channels
# ──────────────────────────────────────────────
FOLDER_PREFIX: str = "TGDrive_"
DEFAULT_FOLDER_NAME: str = "General"

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

APP_DIR: Path = Path(env_str("APP_DATA_DIR", str(_PROJECT_ROOT)))
APP_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH: Path = APP_DIR / "index.db"
TEMP_DIR: Path = APP_DIR / "tmp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────
# Chunk settings (20 MB — safe for Render free tier ~512 MB RAM)
# ──────────────────────────────────────────────
CHUNK_SIZE: int = 20 * 1024 * 1024  # 20 MB

# ──────────────────────────────────────────────
# Upload / download concurrency
# Keep at 1 to avoid Telegram rate-limit bans
# ──────────────────────────────────────────────
MAX_CONCURRENT_UPLOADS: int = 1
MAX_CONCURRENT_DOWNLOADS: int = 1

# ──────────────────────────────────────────────
# Rate limiting — anti-ban
# ──────────────────────────────────────────────
RATE_LIMIT_DELAY: float = env_float("RATE_LIMIT_DELAY", 2.0)        # seconds between API calls
MAX_REQUESTS_PER_MINUTE: int = env_int("MAX_REQUESTS_PER_MINUTE", 20)
