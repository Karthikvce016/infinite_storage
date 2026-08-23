"""
routes.py – File upload/download/delete endpoints for Telegram Drive.

All endpoints are folder-scoped (by folder ID) and require authentication.
Uses the StorageProvider abstraction — no direct Telegram calls.
"""

import shutil
import logging
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, UploadFile, File, Form, Request, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse

from config.settings import TEMP_DIR
from core.chunk_manager import compute_hash, split_file, merge_chunks, cleanup_chunks
from api.auth_routes import require_auth
from storage.database import FileRecord

log = logging.getLogger(__name__)

router = APIRouter()


def _sanitize_filename(name: str) -> str:
    """Strip any directory components from a client-supplied filename.

    Uploads are written under TEMP_DIR using the raw filename; without this,
    a crafted name like "../../main.py" (or an absolute path) escapes the
    temp dir. Backslashes are normalised first so Windows-style paths from
    browsers can't sneak through either.
    """
    name = (name or "").replace("\\", "/")
    name = name.split("/")[-1].strip().lstrip(".")
    return name or "upload"


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

    # Never trust client-supplied filenames — strip directory components so
    # something like "../../main.py" can't escape the temp directory.
    safe_name = _sanitize_filename(file.filename)

    # Save to a collision-proof temp file (two users uploading "report.pdf"
    # at the same time must not overwrite each other's temp file).
    temp_file_path = TEMP_DIR / f"upload_{uuid4().hex}_{safe_name}"
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save temporary file: {e}")

    file_size = temp_file_path.stat().st_size

    # Use alias if provided, preserving the original file extension
    if alias and alias.strip():
        original_ext = Path(safe_name).suffix
        alias_name = _sanitize_filename(alias)
        if not Path(alias_name).suffix:
            alias_name += original_ext
        rel_path = alias_name
    else:
        rel_path = safe_name

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
        raise HTTPException(status_code=404, detail="File record not found in database")

    log.info("SYSTEM: Download — found record with %d chunks, msg_ids=%s", record.chunks, record.msg_ids)

    try:
        chunk_paths = await storage.download_file(
            folder_name=folder_name,
            msg_ids=record.msg_ids,
            dest_dir=TEMP_DIR,
        )
        log.info("SYSTEM: Download — downloaded %d chunks to temp", len(chunk_paths))

        # Merge chunks to unique temp file
        safe_base = Path(file_id).name
        unique_name = f"dl_{uuid4().hex}_{safe_base}"
        merged = TEMP_DIR / unique_name
        merge_chunks(chunk_paths, merged)
        cleanup_chunks(chunk_paths)
        log.info("SYSTEM: Download — merged chunks to %s (%d bytes)", merged, merged.stat().st_size)

        background_tasks.add_task(cleanup_file_task, merged)

        return FileResponse(
            path=merged,
            media_type="application/octet-stream",
            filename=safe_base,
            content_disposition_type="attachment",
        )

    except FileNotFoundError as fnf:
        log.warning("Download failed — media chunk not in storage channel: %s", fnf)
        raise HTTPException(
            status_code=404,
            detail="File message not found in Telegram channel. The file might have been uploaded to a previous channel or deleted."
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Download failed for %s", file_id)
        raise HTTPException(status_code=500, detail=f"Download failed: {exc}")


def _get_media_type(filename: str) -> str:
    """Determine media type from file extension."""
    ext = Path(filename).suffix.lower()
    media_types = {
        # Images
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".bmp": "image/bmp",
        ".ico": "image/x-icon",
        # Videos
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
        # Audio
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        # Documents
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".json": "application/json",
        ".xml": "application/xml",
        ".html": "text/html",
        ".css": "text/css",
        ".js": "application/javascript",
        # Archives
        ".zip": "application/zip",
        ".tar": "application/x-tar",
        ".gz": "application/gzip",
        ".rar": "application/vnd.rar",
        ".7z": "application/x-7z-compressed",
    }
    return media_types.get(ext, "application/octet-stream")


def _is_previewable(filename: str) -> bool:
    """Check if file type supports inline preview."""
    ext = Path(filename).suffix.lower()
    previewable = {
        # Images
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico",
        # Videos
        ".mp4", ".webm", ".mov", ".mkv",
        # Audio
        ".mp3", ".wav", ".ogg", ".m4a", ".flac",
        # Documents
        ".pdf", ".txt", ".md", ".json", ".xml", ".html", ".css", ".js",
    }
    return ext in previewable


@router.get("/folders/{folder_id:int}/preview/{file_id:path}")
async def preview_file(
    folder_id: int,
    file_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Preview a file inline in the browser (for images, videos, PDFs, text, etc.)."""
    storage, owner, db = _get_context(request)
    folder = _resolve_folder(db, folder_id, owner)
    folder_name = folder.name

    log.info("SYSTEM: Preview request — file_id=%s, folder=%s, owner=%s", file_id, folder_name, owner)

    record = db.get_file(file_id, folder_name, owner)
    if not record:
        log.warning("SYSTEM: Preview failed — file not found: %s in folder %s", file_id, folder_name)
        raise HTTPException(status_code=404, detail="File record not found in database")

    if not _is_previewable(file_id):
        raise HTTPException(status_code=400, detail="File type not previewable")

    log.info("SYSTEM: Preview — found record with %d chunks, msg_ids=%s", record.chunks, record.msg_ids)

    try:
        chunk_paths = await storage.download_file(
            folder_name=folder_name,
            msg_ids=record.msg_ids,
            dest_dir=TEMP_DIR,
        )
        log.info("SYSTEM: Preview — downloaded %d chunks to temp", len(chunk_paths))

        # Merge chunks to unique temp file
        safe_base = Path(file_id).name
        unique_name = f"prev_{uuid4().hex}_{safe_base}"
        merged = TEMP_DIR / unique_name
        merge_chunks(chunk_paths, merged)
        cleanup_chunks(chunk_paths)
        log.info("SYSTEM: Preview — merged chunks to %s (%d bytes)", merged, merged.stat().st_size)

        media_type = _get_media_type(file_id)
        background_tasks.add_task(cleanup_file_task, merged)

        return FileResponse(
            path=merged,
            media_type=media_type,
            filename=safe_base,
            content_disposition_type="inline",
            headers={
                "Cache-Control": "public, max-age=3600",
                "Accept-Ranges": "bytes",
            },
        )

    except FileNotFoundError as fnf:
        log.warning("Preview failed — media chunk not in storage channel: %s", fnf)
        raise HTTPException(
            status_code=404,
            detail="File message not found in Telegram channel. The file might have been uploaded to a previous channel or deleted."
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Preview failed for %s", file_id)
        raise HTTPException(status_code=500, detail=f"Preview failed: {exc}")


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
