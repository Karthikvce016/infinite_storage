"""
auth_routes.py – Authentication endpoints for multi-user Telegram login.

Endpoints:
    POST /api/auth/send-otp    → Send OTP to phone
    POST /api/auth/verify-otp  → Verify OTP, return JWT
    GET  /api/auth/me          → Current user info
    POST /api/auth/logout      → Invalidate session
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel


auth_router = APIRouter()


# ── Request / Response Models ─────────────────────────────

class SendOtpRequest(BaseModel):
    phone: str

class SendOtpResponse(BaseModel):
    phone_code_hash: str
    message: str

class VerifyOtpRequest(BaseModel):
    phone: str
    code: str
    phone_code_hash: str

class VerifyOtpResponse(BaseModel):
    token: str
    name: str


# ── Dependency: extract current user from JWT ─────────────

async def get_current_user(request: Request) -> str:
    """FastAPI dependency – returns the authenticated user's phone number."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = auth_header[7:]
    auth_manager = request.app.state.auth_manager

    try:
        payload = auth_manager.decode_jwt(token)
        return payload["phone"]
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


# ── Endpoints ─────────────────────────────────────────────

@auth_router.post("/send-otp", response_model=SendOtpResponse)
async def send_otp(body: SendOtpRequest, request: Request):
    """Send a Telegram OTP to the given phone number."""
    phone = body.phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    auth_manager = request.app.state.auth_manager

    try:
        phone_code_hash = await auth_manager.send_otp(phone)
        return SendOtpResponse(
            phone_code_hash=phone_code_hash,
            message="OTP sent to your Telegram app.",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send OTP: {e}")


@auth_router.post("/verify-otp", response_model=VerifyOtpResponse)
async def verify_otp(body: VerifyOtpRequest, request: Request):
    """Verify the OTP code and return a JWT token."""
    phone = body.phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    auth_manager = request.app.state.auth_manager

    try:
        result = await auth_manager.verify_otp(
            phone, body.code.strip(), body.phone_code_hash
        )
        return VerifyOtpResponse(token=result["token"], name=result["name"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification failed: {e}")


@auth_router.get("/me")
async def get_me(request: Request, user_phone: str = Depends(get_current_user)):
    """Return current user info from JWT."""
    auth_manager = request.app.state.auth_manager
    token = request.headers.get("Authorization", "")[7:]
    payload = auth_manager.decode_jwt(token)
    return {"phone": payload["phone"], "name": payload.get("name", "")}


@auth_router.post("/logout")
async def logout(request: Request, user_phone: str = Depends(get_current_user)):
    """Disconnect user's cached Telegram client."""
    auth_manager = request.app.state.auth_manager
    await auth_manager.logout(user_phone)
    return {"message": "Logged out successfully"}
