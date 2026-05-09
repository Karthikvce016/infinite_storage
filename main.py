"""
main.py – Entry point for Telegram Drive (Web API).

Architecture:
    1. Start FastAPI application via uvicorn.
    2. Initialize Database and AuthManager via FastAPI lifespan.
    3. Expose REST endpoints under `/api`.
    4. Serve frontend via StaticFiles.
"""

import logging
import os
import sys
import uvicorn

from config.settings import API_ID, API_HASH
from storage.database import Database
from core.auth import AuthManager

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

    auth_manager = AuthManager(db)

    # Store instances in FastAPI app state for routes to access
    app.state.db = db
    app.state.auth_manager = auth_manager

    @app.router.on_event("startup")
    async def startup_event():
        log.info("Telegram Drive started (multi-user mode).")
        log.info("Users authenticate with their own Telegram account via OTP.")

    @app.router.on_event("shutdown")
    async def shutdown_event():
        log.info("Shutting down – cleaning up client connections...")
        await auth_manager.cleanup_stale()
        db.close()

    # Launch uvicorn
    port = int(os.environ.get("PORT", 8000))
    log.info("Starting Web API on http://0.0.0.0:%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
