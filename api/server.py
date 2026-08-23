"""
server.py – FastAPI app setup with all routers mounted.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from api.routes import router as file_router
from api.auth_routes import router as auth_router
from api.folder_routes import router as folder_router

from api.debug_routes import router as debug_router

app = FastAPI(title="Telegram Drive API")

# CORS is opt-in: set ALLOWED_ORIGINS="https://app.example.com,http://localhost:3000"
# Only needed when the UI is served from a different origin than this API.
_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Mount API routers
app.include_router(auth_router, prefix="/api")
app.include_router(folder_router, prefix="/api")
app.include_router(file_router, prefix="/api")
app.include_router(debug_router, prefix="/api")

# Mount frontend static files (must be last — catches all unmatched routes)
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
