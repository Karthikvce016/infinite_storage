"""
main.py – Entry point for Telegram Drive (Web API).

Architecture:
    1. Start FastAPI application via uvicorn.
    2. Initialize Telegram Client and Database via FastAPI lifespan.
    3. Expose REST endpoints under `/api`.
    4. Serve frontend via StaticFiles.
"""

import asyncio
import logging
import os
import sys
import uvicorn

from config.settings import API_ID, API_HASH
from storage.database import Database
from core.telegram_client import TelegramDriveClient

from api.server import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-24s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger("telegram_drive")


def main() -> None:
    # ── Pre-flight checks ────────────────────────────────────
    if not API_ID or not API_HASH:
        print(
            "\n⚠  Telegram API credentials missing.\n"
            "   1. Visit https://my.telegram.org and create an application.\n"
            "   2. Copy .env.example to .env and fill in API_ID and API_HASH.\n"
            "      Or set them as environment variables on your deployment platform.\n"
        )
        sys.exit(1)

    db = Database()
    db.connect()

    tg_client = TelegramDriveClient()
    
    # Store instances in FastAPI app state for routes to access
    app.state.db = db
    app.state.tg_client = tg_client

    # Create a lifespan context manager for FastAPI
    @app.router.on_event("startup")
    async def startup_event():
        log.info("Starting up Telegram Client...")
        await tg_client.create_and_connect()
        try:
            authorized = await tg_client.is_authorized()
            if not authorized:
                log.warning("Telegram client is NOT authorized! Please check instructions to login.")
            else:
                log.info("Telegram client authorized.")
                await tg_client.ensure_channel()
        except Exception as e:
            log.error("Failed to authenticate Telegram client on startup: %s", e)

    @app.router.on_event("shutdown")
    async def shutdown_event():
        log.info("Disconnecting Telegram Client...")
        await tg_client.disconnect()
        db.close()

    # Launch uvicorn
    port = int(os.environ.get("PORT", 8000))
    log.info("Starting Web API on http://0.0.0.0:%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
