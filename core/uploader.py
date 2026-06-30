"""
uploader.py – Rate-limited chunk uploader for Telegram Drive.

Uses the two-step upload optimisation:
    1. client.upload_file()   – raw upload, returns an InputFile handle
    2. client.send_file()     – sends the already-uploaded blob as a message

Structured message caption format:
    TGDrive|<filename>|<chunk_index>|<total_chunks>|<sha256_hash>

This caption format allows DB rebuild from Telegram messages.
"""

import asyncio
import logging
from pathlib import Path
from typing import Callable, List, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import Channel

from config.settings import MAX_CONCURRENT_UPLOADS
from core.rate_limiter import RateLimiter, handle_flood_wait

log = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, int], None]]

# Caption format used for DB rebuild
CAPTION_SEPARATOR = "|"


def build_caption(
    filename: str, chunk_index: int, total_chunks: int, file_hash: str
) -> str:
    """Build a structured caption for a chunk message."""
    return CAPTION_SEPARATOR.join(
        ["TGDrive", filename, str(chunk_index), str(total_chunks), file_hash]
    )


def parse_caption(caption: str) -> Optional[dict]:
    """
    Parse a structured TGDrive caption.

    Returns dict with keys: filename, chunk_index, total_chunks, hash
    or None if the caption is not a valid TGDrive caption.
    """
    if not caption or not caption.startswith("TGDrive" + CAPTION_SEPARATOR):
        return None
    parts = caption.split(CAPTION_SEPARATOR)
    if len(parts) != 5:
        return None
    try:
        return {
            "filename": parts[1],
            "chunk_index": int(parts[2]),
            "total_chunks": int(parts[3]),
            "hash": parts[4],
        }
    except (ValueError, IndexError):
        return None


async def _upload_single_chunk(
    client: TelegramClient,
    channel: Channel,
    chunk_path: Path,
    caption: str,
    rate_limiter: RateLimiter,
    progress_cb: ProgressCallback = None,
) -> int:
    """Upload one chunk file and return the resulting Telegram message ID."""
    file_size = chunk_path.stat().st_size

    while True:
        try:
            async with rate_limiter:
                log.info("Uploading chunk: %s (%d bytes)", chunk_path.name, file_size)
                input_file = await client.upload_file(
                    chunk_path,
                    progress_callback=progress_cb,
                )

            async with rate_limiter:
                msg = await client.send_file(
                    channel,
                    input_file,
                    caption=caption,
                    force_document=True,
                )

            log.info("Uploaded %s → msg_id=%d", chunk_path.name, msg.id)
            return msg.id

        except FloodWaitError as e:
            await handle_flood_wait(e, context=f"upload {chunk_path.name}")


async def upload_chunks(
    client: TelegramClient,
    channel: Channel,
    chunk_paths: List[Path],
    filename: str,
    file_hash: str,
    rate_limiter: RateLimiter,
    progress_cb: ProgressCallback = None,
) -> List[int]:
    """
    Upload all *chunk_paths* sequentially (rate-limited) and return an
    ordered list of Telegram message IDs.

    Chunks are uploaded one at a time to avoid triggering Telegram bans.
    """
    total_chunks = len(chunk_paths)
    msg_ids: List[int] = []

    for i, cp in enumerate(chunk_paths):
        caption = build_caption(filename, i, total_chunks, file_hash)
        msg_id = await _upload_single_chunk(
            client, channel, cp, caption, rate_limiter, progress_cb
        )
        msg_ids.append(msg_id)

    return msg_ids


async def delete_messages(
    client: TelegramClient,
    channel: Channel,
    msg_ids: List[int],
    rate_limiter: RateLimiter,
) -> None:
    """Delete previously uploaded chunk messages from the channel."""
    if not msg_ids:
        return
    try:
        async with rate_limiter:
            await client.delete_messages(channel, msg_ids)
        log.info("Deleted %d messages from channel", len(msg_ids))
    except FloodWaitError as e:
        await handle_flood_wait(e, context="delete_messages")
        async with rate_limiter:
            await client.delete_messages(channel, msg_ids)
    except Exception as exc:
        log.error("Failed to delete messages: %s", exc)
