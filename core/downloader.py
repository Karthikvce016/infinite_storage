"""
downloader.py – Parallel chunk downloader for Telegram Drive.

Downloads chunk messages from the storage channel, saves them to a
temporary directory, and returns the ordered list of local paths
ready for merging and decryption.
"""

import asyncio
import logging
from pathlib import Path
from typing import Callable, List, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import Channel

from config.settings import MAX_CONCURRENT_DOWNLOADS, TEMP_DIR

log = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, int], None]]


async def _download_single(
    client: TelegramClient,
    channel: Channel,
    msg_id: int,
    dest_dir: Path,
    index: int,
    semaphore: asyncio.Semaphore,
    progress_cb: ProgressCallback = None,
) -> Path:
    """Download one message attachment and return the local path."""
    async with semaphore:
        while True:
            try:
                msg = await client.get_messages(channel, ids=msg_id)
                if msg is None or msg.media is None:
                    raise FileNotFoundError(f"Message {msg_id} has no media")

                out_path = dest_dir / f"chunk_{index}"
                await client.download_media(
                    msg,
                    file=str(out_path),
                    progress_callback=progress_cb,
                )
                log.info("Downloaded msg_id=%d → %s", msg_id, out_path.name)
                return out_path

            except FloodWaitError as e:
                log.warning("FloodWait: sleeping %d s (msg_id=%d)", e.seconds, msg_id)
                await asyncio.sleep(e.seconds + 1)


async def download_chunks(
    client: TelegramClient,
    channel: Channel,
    msg_ids: List[int],
    dest_dir: Path = TEMP_DIR,
    progress_cb: ProgressCallback = None,
) -> List[Path]:
    """
    Download all chunks identified by *msg_ids* into *dest_dir*.
    Returns an ordered list of local chunk paths.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

    tasks = [
        _download_single(client, channel, mid, dest_dir, i, semaphore, progress_cb)
        for i, mid in enumerate(msg_ids)
    ]
    paths: List[Path] = await asyncio.gather(*tasks)
    return list(paths)

