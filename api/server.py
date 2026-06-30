"""
server.py – FastAPI app setup with all routers mounted.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from api.routes import router as file_router
from api.auth_routes import router as auth_router
from api.folder_routes import router as folder_router

app = FastAPI(title="Telegram Drive API")

# Mount API routers
app.include_router(auth_router, prefix="/api")
app.include_router(folder_router, prefix="/api")
app.include_router(file_router, prefix="/api")

# Mount frontend static files (must be last — catches all unmatched routes)
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
