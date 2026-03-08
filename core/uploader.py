"""
uploader.py – Parallel chunk uploader with rate-limit handling.

Uses the two-step upload optimisation:
    1. client.upload_file()   – raw upload, returns an InputFile handle
    2. client.send_file()     – sends the already-uploaded blob as a message

Concurrency is limited via asyncio.Semaphore to avoid FloodWaitError.
"""

import asyncio
import logging
from pathlib import Path
from typing import Callable, List, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import Channel

from config.settings import MAX_CONCURRENT_UPLOADS

log = logging.getLogger(__name__)

# Type alias for a progress callback:  (bytes_uploaded, total_bytes) → None
ProgressCallback = Optional[Callable[[int, int], None]]


async def _upload_single_chunk(
    client: TelegramClient,
    channel: Channel,
    chunk_path: Path,
    semaphore: asyncio.Semaphore,
    progress_cb: ProgressCallback = None,
) -> int:
    """Upload one chunk file and return the resulting Telegram message ID."""
    async with semaphore:
        file_size = chunk_path.stat().st_size

        while True:
            try:
                # Step 1 – raw upload
                log.info("Uploading chunk: %s (%d bytes)", chunk_path.name, file_size)
                input_file = await client.upload_file(
                    chunk_path,
                    progress_callback=progress_cb,
                )
                # Step 2 – send as document message
                msg = await client.send_file(
                    channel,
                    input_file,
                    caption=chunk_path.name,
                    force_document=True,
                )
                log.info("Uploaded %s → msg_id=%d", chunk_path.name, msg.id)
                return msg.id

            except FloodWaitError as e:
                log.warning("FloodWait: sleeping %d s before retrying %s", e.seconds, chunk_path.name)
                await asyncio.sleep(e.seconds + 1)


async def upload_chunks(
    client: TelegramClient,
    channel: Channel,
    chunk_paths: List[Path],
    progress_cb: ProgressCallback = None,
) -> List[int]:
    """
    Upload all *chunk_paths* concurrently (up to MAX_CONCURRENT_UPLOADS)
    and return an ordered list of Telegram message IDs.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)
    tasks = [
        _upload_single_chunk(client, channel, cp, semaphore, progress_cb)
        for cp in chunk_paths
    ]
    msg_ids: List[int] = await asyncio.gather(*tasks)
    return list(msg_ids)


async def delete_messages(
    client: TelegramClient,
    channel: Channel,
    msg_ids: List[int],
) -> None:
    """Delete previously uploaded chunk messages from the channel."""
    if not msg_ids:
        return
    try:
        await client.delete_messages(channel, msg_ids)
        log.info("Deleted %d messages from channel", len(msg_ids))
    except Exception as exc:
        log.error("Failed to delete messages: %s", exc)

