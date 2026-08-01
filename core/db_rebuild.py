"""
db_rebuild.py – Reconstruct file index from Telegram messages.

Scans the user's TGDrive_* channels and reconstructs the database
file index from message captions. This is critical because Render's
free tier has ephemeral disk — the DB can get wiped on deploy.

Uses the StorageProvider interface (not Telegram directly).

Caption format (set by uploader.py):
    TGDrive|<filename>|<chunk_index>|<total_chunks>|<sha256_hash>
"""

import logging
from collections import defaultdict
from typing import Optional

from core.storage.base import StorageProvider
from core.uploader import parse_caption
from storage.database import Database, FileRecord, FolderRecord

log = logging.getLogger(__name__)


async def rebuild_index(
    storage: StorageProvider,
    db: Database,
    owner: str = "default",
) -> dict:
    """
    Scan the Telegram storage channel and rebuild the file index.
    Since all files are stored in a single Telegram channel, we scan
    the channel directly and restore files to the default folder.

    NOTE: We do NOT clear the DB first. This preserves existing records
    if the scan fails for any reason (e.g., Telegram rate limits, network
    issues, or channel access problems). The scan is additive/upsert only.
    """
    from config.settings import DEFAULT_FOLDER_NAME

    log.info("SYSTEM: Starting DB rebuild for owner '%s'...", owner)

    # ── STEP 1: Ensure the default folder exists (do NOT clear DB) ──
    channel_id = 0
    if hasattr(storage, '_storage_channel_id') and storage._storage_channel_id:
        channel_id = storage._storage_channel_id

    db.upsert_folder(FolderRecord(
        name=DEFAULT_FOLDER_NAME,
        channel_id=channel_id,
        owner=owner,
    ))
    log.info("SYSTEM: Default folder '%s' ensured in DB", DEFAULT_FOLDER_NAME)

    # ── STEP 2: Scan the storage channel directly ──
    log.info("SYSTEM: Scanning Telegram channel for files...")
    messages = await storage.scan_folder_messages(DEFAULT_FOLDER_NAME)
    log.info("SYSTEM: Scan returned %d messages with media", len(messages))

    if not messages:
        log.warning("SYSTEM: No messages found in channel. Either the channel is empty, "
                    "the bot cannot access the channel, or the channel ID is wrong.")
        return {"folders": 1, "files": 0}

    # Group chunks by filename
    file_chunks: dict[str, dict] = defaultdict(lambda: {
        "chunks": {},
        "total_chunks": 0,
        "hash": "",
        "total_size": 0,
    })

    parsed_count = 0
    legacy_count = 0
    for msg_data in messages:
        caption = msg_data["caption"]
        parsed = parse_caption(caption)

        if parsed is None:
            # Legacy message without structured caption — use document filename
            fname = msg_data.get("file_name")
            if fname:
                file_chunks[fname]["chunks"][0] = msg_data["msg_id"]
                file_chunks[fname]["total_chunks"] = 1
                file_chunks[fname]["hash"] = ""
                file_chunks[fname]["total_size"] += msg_data.get("file_size", 0)
                legacy_count += 1
            continue

        fname = parsed["filename"]
        chunk_idx = parsed["chunk_index"]
        total = parsed["total_chunks"]
        file_hash = parsed["hash"]

        file_chunks[fname]["chunks"][chunk_idx] = msg_data["msg_id"]
        file_chunks[fname]["total_chunks"] = total
        file_chunks[fname]["hash"] = file_hash
        file_chunks[fname]["total_size"] += msg_data.get("file_size", 0)
        parsed_count += 1

    log.info("SYSTEM: Parsed %d TGDrive captions, %d legacy messages", parsed_count, legacy_count)

    # Create FileRecord entries from the grouped chunks
    total_files = 0
    skipped_files = 0
    for filename, info in file_chunks.items():
        expected = info["total_chunks"]
        actual_chunks = info["chunks"]

        if expected == 0:
            continue

        # Check all chunks are present
        missing = [i for i in range(expected) if i not in actual_chunks]
        if missing:
            log.warning(
                "SYSTEM: File '%s' is incomplete (missing chunks: %s), skipping",
                filename, missing,
            )
            skipped_files += 1
            continue

        # Build ordered msg_ids list
        msg_ids = [actual_chunks[i] for i in range(expected)]

        record = FileRecord(
            path=filename,
            hash=info["hash"],
            size=info["total_size"],
            chunks=expected,
            folder=DEFAULT_FOLDER_NAME,
            owner=owner,
            msg_ids=msg_ids,
        )
        db.upsert_file(record)
        total_files += 1

    log.info(
        "SYSTEM: Rebuilt folder '%s' — %d files upserted, %d skipped",
        DEFAULT_FOLDER_NAME, total_files, skipped_files,
    )

    summary = {"folders": 1, "files": total_files, "skipped": skipped_files}
    log.info("SYSTEM: DB rebuild complete — %s", summary)
    return summary
