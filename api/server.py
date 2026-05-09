from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from api.routes import router
from api.auth_routes import auth_router

app = FastAPI(title="Telegram Drive API")

# Mount API routes
app.include_router(router, prefix="/api")
app.include_router(auth_router, prefix="/api/auth")

# Mount frontend static files
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
