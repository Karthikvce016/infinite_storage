"""
main.py – Entry point for Telegram Drive (Web API).

Architecture:
    1. Initialize Database (Postgres or SQLite fallback).
    2. Initialize Storage Provider (Telegram Bot).
    3. Run DB rebuild to sync file index from Telegram.
    4. Start FastAPI application via uvicorn.
"""

import logging
import os
import sys
from contextlib import asynccontextmanager

import uvicorn

from config.settings import API_ID, API_HASH, BOT_TOKEN, DATABASE_URL
from storage.database import Database
from core.storage.telegram_provider import TelegramProvider
from core.db_rebuild import rebuild_index

from api.server import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-24s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger("telegram_drive")


@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan: startup and shutdown logic."""
    # ── Startup ──────────────────────────────────────────
    log.info("SYSTEM: Starting Telegram Drive...")

    # 1. Database
    db = Database()
    db.connect()
    app.state.db = db

    # 2. Storage provider (Telegram Bot)
    storage = TelegramProvider()
    try:
        await storage.connect()
        storage.set_db(db)
        app.state.storage = storage

        # 3. Rebuild file index from Telegram (non-destructive — upserts only)
        try:
            summary = await rebuild_index(storage, db, owner="admin")
            log.info("SYSTEM: DB rebuild on startup — %s", summary)
        except Exception as rebuild_err:
            log.warning("SYSTEM: DB rebuild failed (non-fatal): %s", rebuild_err)

    except Exception as exc:
        log.error("SYSTEM: Failed to connect storage provider: %s", exc)
        log.error(
            "SYSTEM: The app will start but storage operations will fail. "
            "Check BOT_TOKEN and ensure the bot is an admin in the storage channel."
        )
        app.state.storage = None

    log.info("SYSTEM: Startup complete.")

    yield

    # ── Shutdown ─────────────────────────────────────────
    log.info("SYSTEM: Shutting down...")
    if app.state.storage:
        await app.state.storage.disconnect()
    db.close()
    log.info("SYSTEM: Shutdown complete.")


# Attach lifespan to the app
app.router.lifespan_context = lifespan


def main() -> None:
    # ── Pre-flight checks ────────────────────────────────────
    if not API_ID or not API_HASH:
        print(
            "\n⚠  Telegram API credentials missing.\n"
            "   1. Visit https://my.telegram.org and create an application.\n"
            "   2. Copy .env.example to .env and fill in API_ID and API_HASH.\n"
        )
        sys.exit(1)

    if not BOT_TOKEN:
        print(
            "\n⚠  Bot token missing.\n"
            "   1. Talk to @BotFather on Telegram and create a bot.\n"
            "   2. Copy the token and set BOT_TOKEN in your .env file.\n"
            "   3. Add the bot as an admin to your private storage channel.\n"
            "   4. Set STORAGE_CHANNEL_ID in .env (the channel's numeric ID).\n"
        )
        sys.exit(1)

    if DATABASE_URL:
        log.info("SYSTEM: Using PostgreSQL from DATABASE_URL")
    else:
        log.info("SYSTEM: No DATABASE_URL found — using local SQLite")

    # Launch uvicorn
    port = int(os.environ.get("PORT", 8000))
    log.info("SYSTEM: Starting Web API on http://0.0.0.0:%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
