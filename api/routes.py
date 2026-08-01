"""
routes.py – File upload/download/delete endpoints for Telegram Drive.

All endpoints are folder-scoped (by folder ID) and require authentication.
Uses the StorageProvider abstraction — no direct Telegram calls.
"""

import shutil
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, Request, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse

from config.settings import TEMP_DIR
from core.chunk_manager import compute_hash, split_file, merge_chunks, cleanup_chunks
from api.auth_routes import require_auth
from storage.database import FileRecord

log = logging.getLogger(__name__)

router = APIRouter()


def _get_context(request: Request):
    """Extract storage provider, owner, and DB from request."""
    owner = require_auth(request)
    storage = request.app.state.storage
    db = request.app.state.db
    return storage, owner, db


def _resolve_folder(db, folder_id: int, owner: str):
    """Resolve a folder by ID, raise 404 if not found."""
    folder = db.get_folder_by_id(folder_id, owner)
    if not folder:
        raise HTTPException(status_code=404, detail=f"Folder with id '{folder_id}' not found")
    return folder


@router.post("/folders/{folder_id:int}/upload")
async def upload_file(
    folder_id: int,
    request: Request,
    file: UploadFile = File(...),
    alias: Optional[str] = Form(None),
):
    """Uploads a file to a specific folder via the storage provider."""
    storage, owner, db = _get_context(request)

    folder = _resolve_folder(db, folder_id, owner)
    folder_name = folder.name

    # Save to temp locally
    temp_file_path = TEMP_DIR / file.filename
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save temporary file: {e}")

    file_size = temp_file_path.stat().st_size

    # Use alias if provided, preserving the original file extension
    if alias and alias.strip():
        original_ext = Path(file.filename).suffix
        alias_name = alias.strip()
        if not Path(alias_name).suffix:
            alias_name += original_ext
        rel_path = alias_name
    else:
        rel_path = file.filename

    new_hash = compute_hash(temp_file_path)
    chunk_paths = []

    try:
        existing = db.get_file(rel_path, folder_name, owner)
        if existing and existing.hash == new_hash:
            temp_file_path.unlink(missing_ok=True)
            return {"message": f"Skipped {rel_path} (unchanged)"}

        if existing:
            await storage.delete_file(folder_name, existing.msg_ids)

        # Split and upload
        chunk_paths = split_file(temp_file_path)

        msg_ids = await storage.upload_file(
            folder_name=folder_name,
            chunk_paths=chunk_paths,
            filename=rel_path,
            file_hash=new_hash,
        )

        record = FileRecord(
            path=rel_path,
            hash=new_hash,
            size=file_size,
            chunks=len(chunk_paths),
            folder=folder_name,
            owner=owner,
            msg_ids=msg_ids,
        )
        db.upsert_file(record)

    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Upload failed for %s", rel_path)
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")
    finally:
        cleanup_chunks(chunk_paths)
        temp_file_path.unlink(missing_ok=True)

    return {"message": "File uploaded successfully", "file": {"name": rel_path, "size": file_size, "folder": folder_name}}


@router.get("/folders/{folder_id:int}/files")
def list_files(folder_id: int, request: Request):
    """Returns list of stored files in a folder."""
    _, owner, db = _get_context(request)
    folder = _resolve_folder(db, folder_id, owner)
    files = db.get_files_in_folder(folder.name, owner)
    return [
        {
            "id": f.path,
            "name": f.path,
            "size": f.size,
            "folder": f.folder,
            "chunks": f.chunks,
        }
        for f in files
    ]


def cleanup_file_task(path: Path):
    """Background task to remove temp file after streaming."""
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


@router.get("/folders/{folder_id:int}/download/{file_id:path}")
async def download_file(
    folder_id: int,
    file_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Downloads a file by retrieving chunks and streaming to the browser."""
    storage, owner, db = _get_context(request)
    folder = _resolve_folder(db, folder_id, owner)
    folder_name = folder.name

    log.info("SYSTEM: Download request — file_id=%s, folder=%s, owner=%s", file_id, folder_name, owner)

    record = db.get_file(file_id, folder_name, owner)
    if not record:
        log.warning("SYSTEM: Download failed — file not found: %s in folder %s", file_id, folder_name)
        raise HTTPException(status_code=404, detail="File not found")

    log.info("SYSTEM: Download — found record with %d chunks, msg_ids=%s", record.chunks, record.msg_ids)

    try:
        chunk_paths = await storage.download_file(
            folder_name=folder_name,
            msg_ids=record.msg_ids,
            dest_dir=TEMP_DIR,
        )
        log.info("SYSTEM: Download — downloaded %d chunks to temp", len(chunk_paths))

        # Merge chunks to temp
        merged = TEMP_DIR / Path(file_id).name
        merge_chunks(chunk_paths, merged)
        cleanup_chunks(chunk_paths)
        log.info("SYSTEM: Download — merged chunks to %s (%d bytes)", merged, merged.stat().st_size)

        def file_iterator():
            with open(merged, "rb") as f:
                while chunk := f.read(8 * 1024 * 1024):
                    yield chunk

        background_tasks.add_task(cleanup_file_task, merged)

        safe_name = file_id.replace('"', '\\"')
        log.info("SYSTEM: Download — streaming response for %s", safe_name)
        return StreamingResponse(
            file_iterator(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
        )

    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Download failed for %s", file_id)
        raise HTTPException(status_code=500, detail=f"Download failed: {exc}")


@router.delete("/folders/{folder_id:int}/files/{file_id:path}")
async def delete_file(folder_id: int, file_id: str, request: Request):
    """Deletes a file from the storage backend and database."""
    storage, owner, db = _get_context(request)
    folder = _resolve_folder(db, folder_id, owner)
    folder_name = folder.name

    record = db.get_file(file_id, folder_name, owner)
    if not record:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        await storage.delete_file(folder_name, record.msg_ids)
        db.delete_file(file_id, folder_name, owner)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Delete failed for %s", file_id)
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}")

    return {"message": "File deleted successfully"}
