"""
auth.py – Multi-user Telegram authentication manager.

Handles OTP-based login flow:
  1. send_otp(phone)                → creates temp client, sends code
  2. verify_otp(phone, code, hash)  → signs in, saves session, issues JWT
  3. get_user_client(phone)         → connected TelegramClient for a user
"""

import logging
import time
from typing import Dict, Optional, Tuple

import jwt
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from config.settings import API_ID, API_HASH, JWT_SECRET, JWT_EXPIRY_DAYS

log = logging.getLogger(__name__)

# phone → (TelegramClient, phone_code_hash, timestamp)
_pending_auth: Dict[str, Tuple[TelegramClient, str, float]] = {}

# phone → (TelegramClient, last_used_timestamp)
_client_cache: Dict[str, Tuple[TelegramClient, float]] = {}

_CACHE_TTL = 30 * 60  # 30 minutes


class AuthManager:
    """Manages user authentication and per-user Telegram client lifecycle."""

    def __init__(self, db) -> None:
        self.db = db

    # ── OTP Flow ─────────────────────────────────────────────

    async def send_otp(self, phone: str) -> str:
        """Send Telegram login code. Returns phone_code_hash."""
        await self._cleanup_pending(phone)

        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()

        try:
            result = await client.send_code_request(phone)
            _pending_auth[phone] = (client, result.phone_code_hash, time.time())
            log.info("OTP sent to %s", phone)
            return result.phone_code_hash
        except PhoneNumberInvalidError:
            await client.disconnect()
            raise ValueError("Invalid phone number. Include country code (e.g. +91...).")
        except FloodWaitError as e:
            await client.disconnect()
            raise ValueError(f"Too many attempts. Please wait {e.seconds} seconds.")
        except Exception:
            await client.disconnect()
            raise

    async def verify_otp(self, phone: str, code: str, phone_code_hash: str) -> dict:
        """Verify OTP, save session, return {token, name}."""
        if phone not in _pending_auth:
            raise ValueError("No pending OTP. Please request a new code.")

        client, stored_hash, ts = _pending_auth[phone]

        if time.time() - ts > 300:
            await self._cleanup_pending(phone)
            raise ValueError("OTP expired. Please request a new code.")

        try:
            await client.sign_in(
                phone=phone, code=code, phone_code_hash=phone_code_hash
            )
        except PhoneCodeInvalidError:
            raise ValueError("Invalid OTP code. Please try again.")
        except PhoneCodeExpiredError:
            await self._cleanup_pending(phone)
            raise ValueError("OTP expired. Please request a new code.")
        except SessionPasswordNeededError:
            await self._cleanup_pending(phone)
            raise ValueError(
                "Two-factor authentication is enabled on this account. "
                "Please disable 2FA in Telegram settings to use this app."
            )

        # Extract session & user info
        session_string = client.session.save()
        me = await client.get_me()
        display_name = (me.first_name or "") + (" " + me.last_name if me.last_name else "")
        display_name = display_name.strip() or phone

        # Persist user
        self.db.upsert_user(phone, session_string, display_name)

        # Move to active cache
        _client_cache[phone] = (client, time.time())
        del _pending_auth[phone]

        token = self._create_jwt(phone, display_name)
        log.info("User %s (%s) authenticated", phone, display_name)
        return {"token": token, "name": display_name}

    # ── Client Management ────────────────────────────────────

    async def get_user_client(self, phone: str) -> TelegramClient:
        """Return a connected TelegramClient for an authenticated user."""
        # Try cache first
        if phone in _client_cache:
            client, _ = _client_cache[phone]
            if client.is_connected():
                _client_cache[phone] = (client, time.time())
                return client
            del _client_cache[phone]

        # Load from DB
        user = self.db.get_user(phone)
        if not user:
            raise ValueError("User not found. Please log in again.")

        client = TelegramClient(
            StringSession(user["session_string"]), API_ID, API_HASH
        )
        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            self.db.delete_user(phone)
            raise ValueError("Session expired. Please log in again.")

        _client_cache[phone] = (client, time.time())
        return client

    # ── JWT ───────────────────────────────────────────────────

    def _create_jwt(self, phone: str, display_name: str) -> str:
        payload = {
            "phone": phone,
            "name": display_name,
            "iat": time.time(),
            "exp": time.time() + (JWT_EXPIRY_DAYS * 86400),
        }
        return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    def decode_jwt(self, token: str) -> dict:
        try:
            return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise ValueError("Token expired. Please log in again.")
        except jwt.InvalidTokenError:
            raise ValueError("Invalid token. Please log in again.")

    # ── Cleanup ──────────────────────────────────────────────

    async def _cleanup_pending(self, phone: str) -> None:
        if phone in _pending_auth:
            client, _, _ = _pending_auth[phone]
            try:
                await client.disconnect()
            except Exception:
                pass
            del _pending_auth[phone]

    async def logout(self, phone: str) -> None:
        if phone in _client_cache:
            client, _ = _client_cache[phone]
            try:
                await client.disconnect()
            except Exception:
                pass
            del _client_cache[phone]

    async def cleanup_stale(self) -> None:
        """Remove cached clients idle for > _CACHE_TTL."""
        now = time.time()
        for phone in list(_client_cache):
            _, last_used = _client_cache[phone]
            if now - last_used > _CACHE_TTL:
                client, _ = _client_cache.pop(phone)
                try:
                    await client.disconnect()
                except Exception:
                    pass
                log.info("Cleaned up stale client for %s", phone)

        for phone in list(_pending_auth):
            _, _, ts = _pending_auth[phone]
            if now - ts > 600:
                await self._cleanup_pending(phone)
