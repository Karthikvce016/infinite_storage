"""
debug_routes.py – Diagnostic endpoints for Telegram Drive.

These endpoints help troubleshoot DB state, storage connection,
and allow manual rebuild of the file index from Telegram.
"""

import logging
from fastapi import APIRouter, Request

from api.auth_routes import require_auth
from core.db_rebuild import rebuild_index

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/debug/status")
async def debug_status(request: Request):
    """Return the current DB and storage status for debugging."""
    owner = require_auth(request)
    db = request.app.state.db
    storage = request.app.state.storage

    # DB stats
    folders = db.get_all_folders(owner)
    files = db.get_all_files(owner)
    total_size = db.get_total_storage(owner)

    # Storage status
    storage_ready = False
    channel_id = None
    if storage:
        try:
            storage_ready = await storage.is_ready()
            channel_id = getattr(storage, '_storage_channel_id', None)
        except Exception as e:
            log.warning("Storage is_ready check failed: %s", e)

    return {
        "owner": owner,
        "storage_connected": storage_ready,
        "storage_channel_id": channel_id,
        "folder_count": len(folders),
        "file_count": len(files),
        "total_storage_bytes": total_size,
        "folders": [{"id": f.id, "name": f.name, "channel_id": f.channel_id} for f in folders],
        "files": [{"name": f.path, "folder": f.folder, "size": f.size, "chunks": f.chunks, "msg_ids": f.msg_ids} for f in files],
    }


@router.post("/debug/rebuild")
async def debug_rebuild(request: Request):
    """Manually trigger a DB rebuild from Telegram."""
    owner = require_auth(request)
    db = request.app.state.db
    storage = request.app.state.storage

    if not storage:
        return {"error": "Storage provider not connected"}

    try:
        summary = await rebuild_index(storage, db, owner=owner)
        return {
            "message": "Rebuild completed",
            "summary": summary,
        }
    except Exception as exc:
        log.exception("Manual rebuild failed")
        return {"error": str(exc)}


@router.post("/debug/download-test")
async def debug_download_test(request: Request):
    """
    Test downloading a single message from Telegram.
    Body: { "msg_id": int }
    Returns: { "success": bool, "size": int, "error": str|None }
    """
    owner = require_auth(request)
    storage = request.app.state.storage

    if not storage:
        return {"error": "Storage provider not connected"}

    body = await request.json()
    msg_id = body.get("msg_id")
    if not msg_id:
        return {"error": "msg_id required"}

    try:
        from config.settings import TEMP_DIR
        from core.downloader import download_chunks
        from core.chunk_manager import cleanup_chunks
        from telethon.tl.types import PeerChannel

        client = storage.client
        channel_id = storage._storage_channel_id
        peer = PeerChannel(channel_id=channel_id)
        entity = await client.get_entity(peer)

        log.info("SYSTEM: debug_download_test — downloading msg_id=%s from channel=%s", msg_id, channel_id)

        paths = await download_chunks(
            client, entity, [msg_id],
            rate_limiter=storage.rate_limiter,
            dest_dir=TEMP_DIR,
        )

        size = 0
        if paths and paths[0].exists():
            size = paths[0].stat().st_size

        cleanup_chunks(paths)

        return {
            "success": True,
            "msg_id": msg_id,
            "size": size,
            "error": None,
        }
    except Exception as exc:
        log.exception("debug_download_test failed for msg_id=%s", msg_id)
        return {
            "success": False,
            "msg_id": msg_id,
            "size": 0,
            "error": str(exc),
        }
