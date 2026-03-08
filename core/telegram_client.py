"""
telegram_client.py – Telethon client wrapper for Telegram Drive.

Manages connection, authentication, and channel creation/lookup.

IMPORTANT: The TelegramClient must be instantiated *inside* the asyncio
event loop that will be used for all subsequent calls (Telethon checks
that the loop hasn't changed).  Use ``create_and_connect()`` from within
the target loop.
"""

import logging
import os
from typing import Optional

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import CreateChannelRequest
from telethon.tl.types import Channel

from config.settings import API_ID, API_HASH, CHANNEL_NAME

log = logging.getLogger(__name__)


class TelegramDriveClient:
    """Thin wrapper around a Telethon TelegramClient."""

    def __init__(self) -> None:
        self.client: Optional[TelegramClient] = None
        self._channel: Optional[Channel] = None

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    async def create_and_connect(self) -> None:
        """
        Instantiate the Telethon client *and* connect, from within the
        asyncio loop that will be used for all future operations.

        Uses a StringSession loaded from the SESSION_STRING env var
        so no .session file is needed on disk.
        """
        session_string = os.getenv("SESSION_STRING", "")
        self.client = TelegramClient(
            StringSession(session_string), API_ID, API_HASH
        )
        await self.client.connect()

    async def disconnect(self) -> None:
        if self.client:
            await self.client.disconnect()

    async def is_authorized(self) -> bool:
        assert self.client is not None
        return await self.client.is_user_authorized()

    async def send_code(self, phone: str) -> str:
        """Send a login code and return the phone_code_hash."""
        assert self.client is not None
        result = await self.client.send_code_request(phone)
        return result.phone_code_hash

    async def sign_in(self, phone: str, code: str, phone_code_hash: str) -> None:
        assert self.client is not None
        await self.client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)

    # ------------------------------------------------------------------
    # Channel management
    # ------------------------------------------------------------------
    async def ensure_channel(self) -> Channel:
        """Find or create the private storage channel. Returns the Channel entity."""
        assert self.client is not None
        if self._channel is not None:
            return self._channel

        # Search existing dialogs
        async for dialog in self.client.iter_dialogs():
            if dialog.name == CHANNEL_NAME and isinstance(dialog.entity, Channel):
                self._channel = dialog.entity
                log.info("Found existing channel: %s (id=%s)", CHANNEL_NAME, self._channel.id)
                return self._channel

        # Create a new private channel (megagroup=False)
        result = await self.client(
            CreateChannelRequest(
                title=CHANNEL_NAME,
                about="Telegram Drive – encrypted file storage",
                megagroup=False,
            )
        )
        self._channel = result.chats[0]
        log.info("Created new channel: %s (id=%s)", CHANNEL_NAME, self._channel.id)
        return self._channel

    @property
    def channel(self) -> Optional[Channel]:
        return self._channel

