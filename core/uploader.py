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


import hashlib
import inspect
from typing import Union
from telethon import helpers
from telethon.tl import types, functions


async def fast_upload_file(
    client: TelegramClient,
    file_path: Path,
    part_size_kb: int = 512,
    workers: int = 8,
    file_name: Optional[str] = None,
    progress_cb: ProgressCallback = None,
) -> Union[types.InputFile, types.InputFileBig]:
    """Upload a file using parallel MTProto part transfers (512 KB parts).

    Dramatically increases upload speeds by pipeline-transmitting multiple
    encrypted chunks concurrently over Telegram's MTProto layer.
    """
    file_size = file_path.stat().st_size
    part_size = part_size_kb * 1024
    part_count = max(1, (file_size + part_size - 1) // part_size)
    is_big = file_size > 10 * 1024 * 1024
    file_id = helpers.generate_random_long()
    target_name = file_name or file_path.name

    semaphore = asyncio.Semaphore(workers)
    uploaded_bytes = 0
    bytes_lock = asyncio.Lock()

    async def _send_part(part_index: int):
        nonlocal uploaded_bytes
        offset = part_index * part_size
        length = min(part_size, file_size - offset)
        with open(file_path, "rb") as f:
            f.seek(offset)
            data = f.read(length)

        retries = 0
        while True:
            try:
                async with semaphore:
                    if is_big:
                        req = functions.upload.SaveBigFilePartRequest(
                            file_id=file_id,
                            file_part=part_index,
                            file_total_parts=part_count,
                            bytes=data,
                        )
                    else:
                        req = functions.upload.SaveFilePartRequest(
                            file_id=file_id,
                            file_part=part_index,
                            bytes=data,
                        )
                    await client(req)
                break
            except FloodWaitError as err:
                await handle_flood_wait(err, context=f"upload part {part_index}")
            except Exception as err:
                retries += 1
                if retries >= 5:
                    log.error("Failed to upload part %d after %d retries: %s", part_index, retries, err)
                    raise
                log.warning("Transient error on part %d: %s. Retrying (%d/5)...", part_index, err, retries)
                await asyncio.sleep(1.0)

        async with bytes_lock:
            uploaded_bytes += length
            if progress_cb:
                if inspect.iscoroutinefunction(progress_cb):
                    await progress_cb(uploaded_bytes, file_size)
                else:
                    progress_cb(uploaded_bytes, file_size)

    tasks = [asyncio.create_task(_send_part(i)) for i in range(part_count)]
    await asyncio.gather(*tasks)

    if is_big:
        return types.InputFileBig(id=file_id, parts=part_count, name=target_name)
    else:
        with open(file_path, "rb") as f:
            md5_val = hashlib.md5(f.read()).hexdigest()
        return types.InputFile(id=file_id, parts=part_count, name=target_name, md5_checksum=md5_val)


async def _upload_single_chunk(
    client: TelegramClient,
    channel: Channel,
    chunk_path: Path,
    caption: str,
    rate_limiter: RateLimiter,
    file_name: Optional[str] = None,
    progress_cb: ProgressCallback = None,
) -> int:
    """Upload one chunk file and return the resulting Telegram message ID."""
    file_size = chunk_path.stat().st_size
    doc_name = file_name or chunk_path.name

    while True:
        try:
            log.info("Uploading: %s (%d bytes) with parallel workers", doc_name, file_size)
            input_file = await fast_upload_file(
                client,
                chunk_path,
                part_size_kb=512,
                workers=8,
                file_name=doc_name,
                progress_cb=progress_cb,
            )

            async with rate_limiter:
                msg = await client.send_file(
                    channel,
                    input_file,
                    caption=caption,
                    force_document=True,
                    attributes=[types.DocumentAttributeFilename(file_name=doc_name)],
                )

            log.info("Uploaded %s → msg_id=%d", doc_name, msg.id)
            return msg.id

        except FloodWaitError as e:
            await handle_flood_wait(e, context=f"upload {doc_name}")


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
