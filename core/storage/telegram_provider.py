"""
telegram_provider.py – Telegram Bot API storage provider.

Implements the StorageProvider interface using a Telegram Bot
connected via Telethon. The bot must be added as an admin to
a private channel (STORAGE_CHANNEL_ID) which acts as the root
storage container. Folders are sub-channels prefixed with TGDrive_.

Key design decisions:
    - Uses BOT_TOKEN instead of user phone + OTP (ban-safe)
    - All API calls go through the RateLimiter
    - Sequential uploads/downloads (no parallelism)
    - Graceful error handling for AccessTokenInvalidError, FloodWaitError
"""

import logging
from pathlib import Path
from typing import List, Optional

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    ChatAdminRequiredError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.channels import (
    CreateChannelRequest,
    EditTitleRequest,
    DeleteChannelRequest,
)
from telethon.tl.types import Channel

from config.settings import (
    API_ID,
    API_HASH,
    BOT_TOKEN,
    STORAGE_CHANNEL_ID,
    FOLDER_PREFIX,
    DEFAULT_FOLDER_NAME,
)
from core.rate_limiter import RateLimiter, handle_flood_wait
from core.storage.base import StorageProvider
from core.uploader import build_caption, upload_chunks, delete_messages
from core.downloader import download_chunks

log = logging.getLogger(__name__)


class TelegramProvider(StorageProvider):
    """
    Telegram storage backend using a Bot token.

    The bot connects via Telethon's MTProto (not HTTP Bot API),
    which allows uploading files up to 2 GB (same as user accounts).
    """

    def __init__(self) -> None:
        self.client: Optional[TelegramClient] = None
        self.rate_limiter = RateLimiter()
        self._folder_cache: dict[str, Channel] = {}
        self._storage_channel_id: Optional[int] = None
        self._db = None  # Set via set_db() for channel ID lookups

    def set_db(self, db) -> None:
        """Give the provider access to the database for resolving folder channel IDs."""
        self._db = db

    # ── Connection ─────────────────────────────────────────
    async def connect(self) -> None:
        """Connect to Telegram using the bot token.
        We will use a SINGLE storage channel for all files.
        """
        if not BOT_TOKEN:
            raise RuntimeError(
                "BOT_TOKEN is not set. "
                "Create a bot via @BotFather and set BOT_TOKEN in your .env file."
            )

        log.info("SYSTEM: Connecting to Telegram as a bot...")
        self.client = TelegramClient(
            StringSession(), API_ID, API_HASH
        )

        # Handle FloodWait — Telegram rate-limits repeated connections
        try:
            await self.client.start(bot_token=BOT_TOKEN)
        except FloodWaitError as e:
            log.warning(
                "SYSTEM: Telegram rate limit — waiting %d seconds before retry...",
                e.seconds,
            )
            import asyncio
            await asyncio.sleep(e.seconds)
            await self.client.start(bot_token=BOT_TOKEN)

        # Force the bot to learn about all channels/dialogs so that
        # channel access hashes are cached before any scan/iterate calls.
        try:
            await self.client.get_dialogs()
            log.info("SYSTEM: Loaded bot dialogs (channel cache primed)")
        except Exception as e:
            log.warning("SYSTEM: Could not load dialogs: %s", e)

        # Verify connection
        me = await self.client.get_me()
        log.info(
            "SYSTEM: Bot connected successfully — @%s (id=%s)",
            me.username, me.id,
        )

        # Store the storage channel ID as an integer.
        # Also resolve the entity to ensure the access hash is cached.
        if STORAGE_CHANNEL_ID:
            try:
                # Ensure it's a valid integer. If it's a username (e.g. @channel), we try to resolve it.
                if str(STORAGE_CHANNEL_ID).lstrip('-').isdigit():
                    self._storage_channel_id = int(STORAGE_CHANNEL_ID)
                    # Explicitly resolve to cache the access hash
                    try:
                        entity = await self.client.get_entity(self._storage_channel_id)
                        log.info("SYSTEM: Storage channel resolved — %s (id=%s)", entity.title, entity.id)
                    except Exception as e:
                        log.warning("SYSTEM: Could not resolve storage channel entity: %s", e)
                else:
                    entity = await self.client.get_entity(STORAGE_CHANNEL_ID)
                    self._storage_channel_id = entity.id
                    log.info("SYSTEM: Storage channel resolved to %s", self._storage_channel_id)
            except Exception as exc:
                log.error(
                    "SYSTEM: Failed to process STORAGE_CHANNEL_ID=%s — %s",
                    STORAGE_CHANNEL_ID, exc,
                )
                raise

    async def disconnect(self) -> None:
        if self.client:
            log.info("SYSTEM: Disconnecting from Telegram...")
            await self.client.disconnect()
            self.client = None

    async def is_ready(self) -> bool:
        if self.client is None:
            return False
        try:
            me = await self.client.get_me()
            return me is not None
        except Exception:
            return False

    # ── Internal helpers ─────────────────────────────────────
    def _folder_title(self, name: str) -> str:
        return f"{FOLDER_PREFIX}{name}"

    def _parse_folder_name(self, title: str) -> Optional[str]:
        if title.startswith(FOLDER_PREFIX):
            return title[len(FOLDER_PREFIX):]
        return None

    # ── Folder operations ────────────────────────────────────
    async def _resolve_channel(self, channel_id: int) -> Optional[Channel]:
        """Resolve a channel by its ID using PeerChannel (bot-safe)."""
        try:
            from telethon.tl.types import PeerChannel
            peer = PeerChannel(channel_id=channel_id)
            entity = await self.client.get_entity(peer)
            return entity
        except Exception as exc:
            log.warning("SYSTEM: Could not resolve channel %s: %s", channel_id, exc)
            return None

    async def create_folder(self, name: str) -> dict:
        """Folders are now just logical DB concepts. No channel is created."""
        assert self.client is not None
        channel_id = self._storage_channel_id or 0
        log.info("SYSTEM: Logical folder created — %s", name)
        return {"name": name, "channel_id": channel_id}

    async def list_folders(self) -> List[dict]:
        """List folders from the database."""
        if self._db is None:
            log.warning("SYSTEM: No DB set on provider, cannot list folders")
            return []

        db_folders = self._db.get_all_folders(owner="admin")
        folders = []
        for f in db_folders:
            folders.append({
                "name": f.name,
                "channel_id": f.channel_id,
                "title": self._folder_title(f.name),
            })
        return folders

    async def get_folder(self, name: str) -> Optional[int]:
        """In single-channel mode, this always returns the main storage channel ID."""
        return self._storage_channel_id

    async def rename_folder(self, old_name: str, new_name: str) -> None:
        """No-op on Telegram side, handled in DB."""
        log.info("SYSTEM: Logical folder renamed — %s → %s", old_name, new_name)

    async def delete_folder(self, name: str) -> None:
        """No-op on Telegram side. Files must be deleted individually first."""
        log.info("SYSTEM: Logical folder deleted — %s", name)

    # ── File operations ──────────────────────────────────────
    async def _resolve_storage_entity(self):
        """Resolve the storage channel entity (with cached access hash)."""
        assert self.client is not None
        if not self._storage_channel_id:
            raise ValueError("Storage channel is not resolved")
        from telethon.tl.types import PeerChannel
        peer = PeerChannel(channel_id=self._storage_channel_id)
        return await self.client.get_entity(peer)

    async def upload_file(
        self,
        folder_name: str,
        chunk_paths: List[Path],
        filename: str,
        file_hash: str,
    ) -> List[int]:
        assert self.client is not None
        entity = await self._resolve_storage_entity()
        return await upload_chunks(
            self.client, entity, chunk_paths,
            filename=filename, file_hash=file_hash,
            rate_limiter=self.rate_limiter,
        )

    async def download_file(
        self,
        folder_name: str,
        msg_ids: List[int],
        dest_dir: Path,
    ) -> List[Path]:
        assert self.client is not None
        entity = await self._resolve_storage_entity()
        return await download_chunks(
            self.client, entity, msg_ids,
            rate_limiter=self.rate_limiter,
            dest_dir=dest_dir,
        )

    async def delete_file(
        self,
        folder_name: str,
        msg_ids: List[int],
    ) -> None:
        assert self.client is not None
        entity = await self._resolve_storage_entity()
        await delete_messages(
            self.client, entity, msg_ids, self.rate_limiter,
        )

    # ── Messaging (sub-folder pointers) ──────────────────
    async def send_message(self, folder_name: str, text: str) -> int:
        """Send a text message to the given folder's channel."""
        assert self.client is not None
        entity = await self._resolve_storage_entity()
        async with self.rate_limiter:
            msg = await self.client.send_message(entity, text)
        return msg.id

    async def get_channel_link(self, folder_name: str) -> str:
        """Get a t.me/c/ link for the given folder's channel."""
        assert self.client is not None

        if not self._storage_channel_id:
            raise ValueError("Storage channel is not resolved")

        channel_id = self._storage_channel_id
        # t.me/c/ links use the channel ID without the -100 prefix
        if str(channel_id).startswith("-100"):
            channel_id = int(str(channel_id)[4:])
        return f"https://t.me/c/{channel_id}/1"

    # ── Rebuild support ──────────────────────────────────────
    async def scan_folder_messages(self, folder_name: str) -> List[dict]:
        assert self.client is not None

        if not self._storage_channel_id:
            log.warning("SYSTEM: scan_folder_messages — _storage_channel_id is not set")
            return []

        # Resolve the channel entity to ensure access hash is cached
        try:
            from telethon.tl.types import PeerChannel
            peer = PeerChannel(channel_id=self._storage_channel_id)
            entity = await self.client.get_entity(peer)
            log.info("SYSTEM: scan_folder_messages — resolved channel: %s (id=%s)", entity.title, entity.id)
        except Exception as exc:
            log.warning("SYSTEM: scan_folder_messages — could not resolve channel %s: %s", self._storage_channel_id, exc)
            return []

        messages = []
        try:
            async for msg in self.client.iter_messages(entity):
                if msg.media is None:
                    continue

                caption = msg.text or (msg.message if hasattr(msg, "message") else "")
                file_name = None
                file_size = 0

                if hasattr(msg.media, "document") and msg.media.document:
                    file_size = msg.media.document.size or 0
                    for attr in msg.media.document.attributes:
                        if hasattr(attr, "file_name") and attr.file_name:
                            file_name = attr.file_name
                            break

                messages.append({
                    "msg_id": msg.id,
                    "caption": caption,
                    "file_name": file_name,
                    "file_size": file_size,
                })
        except Exception as exc:
            log.warning("SYSTEM: scan_folder_messages — iter_messages failed: %s", exc)

        log.info("SYSTEM: scan_folder_messages — found %d messages with media", len(messages))
        return messages

    async def ensure_default_folder(self) -> dict:
        """Ensure the default 'General' folder exists."""
        return await self.create_folder(DEFAULT_FOLDER_NAME)
