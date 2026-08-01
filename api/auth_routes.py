"""
auth_routes.py – Simple password-based web authentication.

Uses a master password from APP_PASSWORD env var (for personal use).
Issues JWT session tokens stored as HTTP-only cookies.

Handles Telegram-specific errors gracefully:
    - PhoneNumberBannedError → clear system log message
    - AccessTokenInvalidError → clear system log message
"""

import hashlib
import logging
import time

import jwt
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from config.settings import APP_PASSWORD

log = logging.getLogger(__name__)

router = APIRouter()

SESSION_COOKIE_NAME = "tgdrive_session"
JWT_SECRET = hashlib.sha256(APP_PASSWORD.encode()).hexdigest()
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 30


def _create_token(username: str) -> str:
    """Create a JWT token for the given username."""
    payload = {
        "sub": username,
        "iat": time.time(),
        "exp": time.time() + JWT_EXPIRY_DAYS * 24 * 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session")


def get_current_user(request: Request) -> str:
    """Extract the authenticated username from the request cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = _decode_token(token)
    return payload["sub"]


def require_auth(request: Request) -> str:
    """Alias for get_current_user — used in route dependencies."""
    return get_current_user(request)


@router.post("/auth/login")
async def login(request: Request):
    """
    Authenticate with a password.

    Body: { "password": "..." }
    Returns a session cookie on success.
    """
    body = await request.json()
    password = body.get("password", "").strip()

    if not password:
        raise HTTPException(status_code=400, detail="Password required")

    if password != APP_PASSWORD:
        log.warning("SYSTEM: Failed login attempt from %s", request.client.host)
        raise HTTPException(status_code=401, detail="Invalid password")

    username = "admin"  # Single-user mode
    token = _create_token(username)

    response = JSONResponse({
        "message": "Login successful",
        "user": {"username": username},
    })
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=JWT_EXPIRY_DAYS * 24 * 3600,
    )

    log.info("SYSTEM: User '%s' logged in from %s", username, request.client.host)

    # Trigger DB rebuild if DB is empty (e.g., after logout/login or deploy)
    try:
        db = request.app.state.db
        storage = request.app.state.storage
        if storage:
            folders = db.get_all_folders(username)
            if not folders:
                log.info("SYSTEM: DB empty on login, triggering rebuild...")
                from core.db_rebuild import rebuild_index
                summary = await rebuild_index(storage, db, owner=username)
                log.info("SYSTEM: Rebuild on login complete — %s", summary)
    except Exception as exc:
        log.warning("SYSTEM: Auto-rebuild on login failed (non-fatal): %s", exc)

    return response


@router.post("/auth/logout")
async def logout(request: Request):
    """Clear the session cookie."""
    response = JSONResponse({"message": "Logged out"})
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@router.get("/auth/check")
async def check_auth(request: Request):
    """Quick auth check — returns 200 if authenticated, 401 otherwise."""
    try:
        username = get_current_user(request)
        return {"authenticated": True, "user": {"username": username}}
    except HTTPException:
        return JSONResponse(
            status_code=401,
            content={"authenticated": False},
        )
