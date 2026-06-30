"""
downloader.py – Rate-limited chunk downloader for Telegram Drive.

Downloads chunk messages from the storage channel, saves them to a
temporary directory, and returns the ordered list of local paths
ready for merging.
"""

import asyncio
import logging
from pathlib import Path
from typing import Callable, List, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import Channel

from config.settings import MAX_CONCURRENT_DOWNLOADS, TEMP_DIR
from core.rate_limiter import RateLimiter, handle_flood_wait

log = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, int], None]]


async def _download_single(
    client: TelegramClient,
    channel: Channel,
    msg_id: int,
    dest_dir: Path,
    index: int,
    rate_limiter: RateLimiter,
    progress_cb: ProgressCallback = None,
) -> Path:
    """Download one message attachment and return the local path."""
    while True:
        try:
            async with rate_limiter:
                msg = await client.get_messages(channel, ids=msg_id)

            if msg is None or msg.media is None:
                raise FileNotFoundError(f"Message {msg_id} has no media")

            out_path = dest_dir / f"chunk_{index}"

            async with rate_limiter:
                # download_media returns the actual file path (may add extension)
                actual_path = await client.download_media(
                    msg,
                    file=str(out_path),
                    progress_callback=progress_cb,
                )

            # Telethon may append the file extension (e.g. chunk_0 -> chunk_0.pdf)
            # Use the actual returned path instead of our expected path
            actual_path = Path(actual_path) if actual_path else out_path

            log.info("Downloaded msg_id=%d → %s", msg_id, actual_path.name)
            return actual_path

        except FloodWaitError as e:
            await handle_flood_wait(e, context=f"download msg_id={msg_id}")


async def download_chunks(
    client: TelegramClient,
    channel: Channel,
    msg_ids: List[int],
    rate_limiter: RateLimiter,
    dest_dir: Path = TEMP_DIR,
    progress_cb: ProgressCallback = None,
) -> List[Path]:
    """
    Download all chunks identified by *msg_ids* into *dest_dir*.
    Returns an ordered list of local chunk paths.

    Downloads sequentially to avoid rate-limit bans.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    paths: List[Path] = []
    for i, mid in enumerate(msg_ids):
        path = await _download_single(
            client, channel, mid, dest_dir, i, rate_limiter, progress_cb
        )
        paths.append(path)

    return paths
