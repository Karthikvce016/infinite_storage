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
    Scan all TGDrive_* channels via the storage provider
    and rebuild the file index.

    Returns a summary dict: { "folders": int, "files": int }
    """
    log.info("SYSTEM: Starting DB rebuild for owner '%s'...", owner)

    # Clear existing data (we'll rebuild from scratch)
    db.clear_owner_data(owner)

    folders = await storage.list_folders()
    total_files = 0

    for folder_info in folders:
        folder_name = folder_info["name"]
        channel_id = folder_info["channel_id"]

        # Save folder record
        db.upsert_folder(FolderRecord(
            name=folder_name,
            channel_id=channel_id,
            owner=owner,
        ))

        # Scan all messages in the folder via the provider
        messages = await storage.scan_folder_messages(folder_name)

        # Group chunks by filename
        file_chunks: dict[str, dict] = defaultdict(lambda: {
            "chunks": {},
            "total_chunks": 0,
            "hash": "",
            "total_size": 0,
        })

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
                continue

            fname = parsed["filename"]
            chunk_idx = parsed["chunk_index"]
            total = parsed["total_chunks"]
            file_hash = parsed["hash"]

            file_chunks[fname]["chunks"][chunk_idx] = msg_data["msg_id"]
            file_chunks[fname]["total_chunks"] = total
            file_chunks[fname]["hash"] = file_hash
            file_chunks[fname]["total_size"] += msg_data.get("file_size", 0)

        # Create FileRecord entries from the grouped chunks
        for filename, info in file_chunks.items():
            expected = info["total_chunks"]
            actual_chunks = info["chunks"]

            if expected == 0:
                continue

            # Check all chunks are present
            missing = [i for i in range(expected) if i not in actual_chunks]
            if missing:
                log.warning(
                    "SYSTEM: File '%s' in folder '%s' is incomplete (missing chunks: %s), skipping",
                    filename, folder_name, missing,
                )
                continue

            # Build ordered msg_ids list
            msg_ids = [actual_chunks[i] for i in range(expected)]

            record = FileRecord(
                path=filename,
                hash=info["hash"],
                size=info["total_size"],
                chunks=expected,
                folder=folder_name,
                owner=owner,
                msg_ids=msg_ids,
            )
            db.upsert_file(record)
            total_files += 1

        log.info(
            "SYSTEM: Rebuilt folder '%s' — %d files found",
            folder_name, sum(1 for f in file_chunks if file_chunks[f]["total_chunks"] > 0),
        )

    summary = {"folders": len(folders), "files": total_files}
    log.info("SYSTEM: DB rebuild complete — %s", summary)
    return summary
