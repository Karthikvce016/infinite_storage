"""
routes.py – File upload/download/delete endpoints for Telegram Drive.

All endpoints are folder-scoped (by folder ID) and require authentication.
Uses the StorageProvider abstraction — no direct Telegram calls.
"""

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, UploadFile, File, Form, Request, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse, Response

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


# Active upload tasks dictionary for explicit cancellation: {upload_id: asyncio.Task}
_active_uploads: dict[str, asyncio.Task] = {}


@router.post("/upload/cancel/{upload_id}")
async def cancel_upload_by_id(upload_id: str, request: Request):
    """Explicitly cancels an ongoing upload by its upload_id."""
    _get_context(request)  # verify auth
    task = _active_uploads.get(upload_id)
    if task and not task.done():
        log.info("Explicit cancellation requested for upload %s", upload_id)
        task.cancel()
        return {"status": "cancelled", "upload_id": upload_id}
    return {"status": "not_found_or_finished", "upload_id": upload_id}


@router.post("/folders/{folder_id:int}/upload")
async def upload_file(
    folder_id: int,
    request: Request,
    file: UploadFile = File(...),
    alias: Optional[str] = Form(None),
):
    """Uploads a file to a specific folder via the storage provider.

    Returns a streaming NDJSON response with progress events so the
    frontend displays accurate real-time progress through all phases:
      1. hashing    – computing SHA-256 (10%)
      2. splitting  – splitting into 20 MB chunks (15%)
      3. uploading  – continuous byte-level progress as chunks upload to Telegram (15% - 98%)
      4. done       – DB upsert and final result (100%)

    Cancellation (via client disconnect or POST /upload/cancel/{upload_id}):
      - Immediately cancels Telegram chunk uploads.
      - Deletes any chunks already uploaded to Telegram to prevent orphaned files.
      - Leaves database and existing files untouched.
    """
    storage, owner, db = _get_context(request)
    folder = _resolve_folder(db, folder_id, owner)
    folder_name = folder.name

    safe_name = _sanitize_filename(file.filename)

    if alias and alias.strip():
        original_ext = Path(safe_name).suffix
        alias_name = _sanitize_filename(alias)
        if not Path(alias_name).suffix:
            alias_name += original_ext
        rel_path = alias_name
    else:
        rel_path = safe_name

    upload_id = request.headers.get("X-Upload-ID") or uuid4().hex
    temp_file_path = TEMP_DIR / f"upload_{uuid4().hex}_{safe_name}"

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save temporary file: {e}")

    file_size = temp_file_path.stat().st_size

    async def _progress_stream():
        queue: asyncio.Queue = asyncio.Queue()
        chunk_paths = []
        msg_ids = []
        completed = False
        replaced_old_msg_ids = None

        async def _upload_worker():
            nonlocal chunk_paths, msg_ids, completed, replaced_old_msg_ids
            try:
                # ── Phase 1: Hashing ──
                queue.put_nowait({"stage": "hashing", "progress": 0})
                await asyncio.sleep(0.01)
                new_hash = compute_hash(temp_file_path)

                # ── Dedupe check ──
                existing = db.get_file(rel_path, folder_name, owner)
                if existing and existing.hash == new_hash:
                    temp_file_path.unlink(missing_ok=True)
                    queue.put_nowait({
                        "stage": "done",
                        "progress": 100,
                        "result": {"message": f"Skipped {rel_path} (unchanged)"},
                    })
                    completed = True
                    return

                if existing:
                    # Note old msg_ids to delete ONLY after new upload finishes!
                    replaced_old_msg_ids = existing.msg_ids

                # ── Phase 2: Splitting ──
                queue.put_nowait({"stage": "splitting", "progress": 0})
                await asyncio.sleep(0.01)
                chunk_paths = split_file(temp_file_path)
                total_chunks = len(chunk_paths)

                queue.put_nowait({
                    "stage": "uploading",
                    "progress": 0,
                    "chunk": 1,
                    "total_chunks": total_chunks,
                    "bytes_uploaded": 0,
                    "total_bytes": file_size,
                })

                # ── Phase 3: Uploading chunks to Telegram ──
                from core.uploader import build_caption, _upload_single_chunk
                entity = await storage._resolve_storage_entity()

                cumulative_bytes = 0
                for i, cp in enumerate(chunk_paths):
                    cp_size = cp.stat().st_size
                    prev_bytes = cumulative_bytes

                    def make_progress_cb(chunk_idx, prev_b, total_b):
                        last_sent = 0
                        def _cb(current, total):
                            nonlocal last_sent
                            # Throttle updates to avoid flooding
                            if current - last_sent >= 262144 or current == total:
                                last_sent = current
                                done_b = prev_b + current
                                pct = min(99, int((done_b / max(total_b, 1)) * 100))
                                queue.put_nowait({
                                    "stage": "uploading",
                                    "progress": pct,
                                    "chunk": chunk_idx + 1,
                                    "total_chunks": total_chunks,
                                    "bytes_uploaded": done_b,
                                    "total_bytes": total_b,
                                })
                        return _cb

                    caption = build_caption(rel_path, i, total_chunks, new_hash)
                    cb = make_progress_cb(i, prev_bytes, file_size)

                    msg_id = await _upload_single_chunk(
                        storage.client, entity, cp, caption,
                        storage.rate_limiter,
                        file_name=rel_path if total_chunks == 1 else f"{rel_path}.part{i+1}",
                        progress_cb=cb,
                    )
                    msg_ids.append(msg_id)
                    cumulative_bytes += cp_size

                # ── Phase 4: Save to DB & clean up old replaced file ──
                if replaced_old_msg_ids:
                    queue.put_nowait({"stage": "replacing", "progress": 99})
                    try:
                        await storage.delete_file(folder_name, replaced_old_msg_ids)
                    except Exception as e:
                        log.warning("Could not delete old replaced messages: %s", e)

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
                completed = True

                queue.put_nowait({
                    "stage": "done",
                    "progress": 100,
                    "result": {
                        "message": "File uploaded successfully",
                        "file": {"name": rel_path, "size": file_size, "folder": folder_name},
                    },
                })

            except (asyncio.CancelledError, GeneratorExit):
                log.info("Upload worker cancelled for %s", rel_path)
                raise
            except Exception as exc:
                log.exception("Upload failed for %s", rel_path)
                queue.put_nowait({
                    "stage": "error",
                    "progress": 0,
                    "detail": f"Upload failed: {exc}",
                })
            finally:
                cleanup_chunks(chunk_paths, preserve_path=temp_file_path)
                temp_file_path.unlink(missing_ok=True)

                if not completed and msg_ids:
                    log.info("Cancelling/cleaning up %d Telegram messages for %s", len(msg_ids), rel_path)
                    try:
                        await storage.delete_file(folder_name, msg_ids)
                    except Exception as clean_exc:
                        log.error("Failed to clean up Telegram messages during cancel: %s", clean_exc)

        # Launch background upload task
        worker_task = asyncio.create_task(_upload_worker())
        _active_uploads[upload_id] = worker_task

        try:
            while True:
                # Check for client disconnect
                if await request.is_disconnected():
                    log.info("Client disconnected during upload of %s", rel_path)
                    worker_task.cancel()
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.3)
                    yield json.dumps(event) + "\n"
                    if event.get("stage") in ("done", "error"):
                        break
                except asyncio.TimeoutError:
                    if worker_task.done():
                        # Drain any remaining queue items
                        while not queue.empty():
                            ev = queue.get_nowait()
                            yield json.dumps(ev) + "\n"
                        break

            await worker_task

        except (asyncio.CancelledError, GeneratorExit):
            log.info("Streaming response cancelled for upload %s (%s)", upload_id, rel_path)
            worker_task.cancel()
            try:
                await worker_task
            except (asyncio.CancelledError, Exception):
                pass
        finally:
            _active_uploads.pop(upload_id, None)

    return StreamingResponse(
        _progress_stream(),
        media_type="application/x-ndjson",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-cache",
            "X-Upload-ID": upload_id,
        },
    )


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
            # Content hash → used by the UI to cache-bust previews after a
            # file is re-uploaded with the same name.
            "hash": f.hash,
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
@router.head("/folders/{folder_id:int}/download/{file_id:path}")
async def download_file(
    folder_id: int,
    file_id: str,
    request: Request,
):
    """Downloads a file by streaming chunks directly from Telegram to the browser."""
    storage, owner, db = _get_context(request)
    folder = _resolve_folder(db, folder_id, owner)
    folder_name = folder.name

    log.info("SYSTEM: Download request — file_id=%s, folder=%s, owner=%s", file_id, folder_name, owner)

    record = db.get_file(file_id, folder_name, owner)
    if not record:
        log.warning("SYSTEM: Download failed — file not found: %s in folder %s", file_id, folder_name)
        raise HTTPException(status_code=404, detail="File record not found in database")

    if not record.msg_ids:
        raise HTTPException(status_code=404, detail="File has no stored chunks")

    total_size = record.size
    safe_base = Path(file_id).name
    quoted_name = quote(safe_base)

    range_header = request.headers.get("range")
    start = 0
    end = total_size - 1
    is_range = False

    if range_header and total_size > 0:
        range_match = re.match(r"^bytes=(\d*)-(\d*)$", range_header.strip())
        if range_match:
            raw_start, raw_end = range_match.groups()
            if raw_start and raw_end:
                start = int(raw_start)
                end = int(raw_end)
                is_range = True
            elif raw_start:
                start = int(raw_start)
                end = total_size - 1
                is_range = True
            elif raw_end:
                suffix = int(raw_end)
                start = max(0, total_size - suffix)
                end = total_size - 1
                is_range = True

        if is_range:
            if start >= total_size or start < 0 or start > end:
                return Response(
                    status_code=416,
                    headers={
                        "Content-Range": f"bytes */{total_size}",
                        "Accept-Ranges": "bytes",
                    },
                )
            end = min(end, total_size - 1)

    content_length = (end - start + 1) if total_size > 0 else 0
    status_code = 206 if is_range else 200

    ascii_base = safe_base.encode("ascii", "ignore").decode("ascii").replace('"', "") or "download"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Type": "application/octet-stream",
        "Content-Disposition": f'attachment; filename="{ascii_base}"; filename*=UTF-8\'\'{quoted_name}',
    }
    if is_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"

    if request.method == "HEAD":
        return Response(status_code=status_code, headers=headers)

    if total_size == 0:
        return Response(content=b"", status_code=status_code, headers=headers, media_type="application/octet-stream")

    async def stream_generator():
        try:
            async for chunk in storage.stream_file(
                folder_name=folder_name,
                msg_ids=record.msg_ids,
                start=start,
                end=end,
                filename=file_id,
                file_hash=record.hash or "",
                file_size=total_size,
            ):
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            return
        except Exception as exc:
            log.warning("SYSTEM: Download stream error for %s: %s", file_id, exc)
            return

    return StreamingResponse(
        stream_generator(),
        status_code=status_code,
        headers=headers,
        media_type="application/octet-stream",
    )


# ──────────────────────────────────────────────────────────────
#  Preview support
#  Extension groups are mirrored in frontend/app.js — keep them in sync.
# ──────────────────────────────────────────────────────────────
IMAGE_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".avif": "image/avif",
    ".bmp": "image/bmp", ".svg": "image/svg+xml", ".ico": "image/x-icon",
}
VIDEO_TYPES = {
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".mkv": "video/x-matroska", ".m4v": "video/mp4",
}
AUDIO_TYPES = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
    ".oga": "audio/ogg", ".m4a": "audio/mp4", ".flac": "audio/flac",
    ".aac": "audio/aac", ".opus": "audio/opus",
}
PDF_TYPES = {".pdf": "application/pdf"}

# Plain-text/code files. Anything listed here (or a file with no extension at
# all) is stored as text/plain rather than its "real" MIME type, so a previewed
# upload can never be re-interpreted as HTML/JS in the app's origin.
TEXT_EXTENSIONS = {
    ".txt", ".text", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv",
    ".json", ".jsonl", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".conf", ".env", ".properties", ".html", ".htm", ".xhtml", ".css",
    ".scss", ".sass", ".less", ".js", ".mjs", ".cjs", ".jsx", ".ts",
    ".tsx", ".vue", ".svelte", ".py", ".pyw", ".rb", ".php", ".pl",
    ".lua", ".r", ".go", ".rs", ".java", ".kt", ".kts", ".swift", ".c",
    ".h", ".cpp", ".cc", ".cxx", ".hpp", ".cs", ".m", ".mm", ".sql",
    ".sh", ".bash", ".zsh", ".fish", ".bat", ".cmd", ".ps1", ".dockerfile",
    ".makefile", ".gitignore", ".editorconfig", ".diff", ".patch", ".tex",
    ".graphql", ".gql", ".proto", ".tf", ".gradle", ".rake", ".asm", ".v",
    ".ex", ".exs", ".clj", ".hs", ".scala", ".dart", ".groovy", ".vb",
    ".pas", ".nim", ".zig",
}

PREVIEWABLE_EXTENSIONS = (
    set(IMAGE_TYPES) | set(VIDEO_TYPES) | set(AUDIO_TYPES)
    | set(PDF_TYPES) | TEXT_EXTENSIONS
)


def _get_media_type(filename: str) -> str:
    """Resolve the media type used when streaming a preview."""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_TYPES:
        return IMAGE_TYPES[ext]
    if ext in VIDEO_TYPES:
        return VIDEO_TYPES[ext]
    if ext in AUDIO_TYPES:
        return AUDIO_TYPES[ext]
    if ext in PDF_TYPES:
        return PDF_TYPES[ext]
    if ext in TEXT_EXTENSIONS or ext == "":
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def _is_previewable(filename: str) -> bool:
    """Check if a file type supports inline preview."""
    ext = Path(filename).suffix.lower()
    return ext == "" or ext in PREVIEWABLE_EXTENSIONS


@router.get("/folders/{folder_id:int}/preview/{file_id:path}")
@router.head("/folders/{folder_id:int}/preview/{file_id:path}")
async def preview_file(
    folder_id: int,
    file_id: str,
    request: Request,
):
    """Preview a file inline with HTTP Range support for instant media streaming."""
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

    if not record.msg_ids:
        raise HTTPException(status_code=404, detail="File has no stored chunks")

    total_size = record.size
    media_type = _get_media_type(file_id)

    # ── Instant local web-optimized stream check ──
    from core.stream_buffer import CACHE_DIR, remux_to_web_mp4
    clean_stem = Path(file_id).stem.encode("ascii", "ignore").decode("ascii").replace("/", "_").replace(" ", "_") or "file"
    file_hash_pfx = (record.hash or "")[:16]
    web_mp4 = CACHE_DIR / f"sb_{file_hash_pfx}_{clean_stem}.mp4"

    if not web_mp4.exists() or web_mp4.stat().st_size == 0:
        candidates = [
            CACHE_DIR / f"sb_{file_hash_pfx}_{clean_stem}.mov",
            TEMP_DIR / f"upload_{file_id}",
        ]
        for p in TEMP_DIR.glob(f"upload_*_{Path(file_id).name}"):
            candidates.append(p)
        for src in candidates:
            if src.exists() and src.stat().st_size == record.size:
                remux_to_web_mp4(src, web_mp4)
                if web_mp4.exists() and web_mp4.stat().st_size > 0:
                    break

    if web_mp4.exists() and web_mp4.stat().st_size > 0:
        return FileResponse(
            web_mp4,
            media_type="video/mp4",
            content_disposition_type="inline",
            filename=f"{Path(file_id).stem}.mp4",
        )
    safe_base = Path(file_id).name
    quoted_name = quote(safe_base)

    range_header = request.headers.get("range")
    start = 0
    end = total_size - 1
    is_range = False

    if range_header and total_size > 0:
        range_match = re.match(r"^bytes=(\d*)-(\d*)$", range_header.strip())
        if range_match:
            raw_start, raw_end = range_match.groups()
            if raw_start and raw_end:
                start = int(raw_start)
                end = int(raw_end)
                is_range = True
            elif raw_start:
                start = int(raw_start)
                end = total_size - 1
                is_range = True
            elif raw_end:
                suffix = int(raw_end)
                start = max(0, total_size - suffix)
                end = total_size - 1
                is_range = True

        if is_range:
            if start >= total_size or start < 0 or start > end:
                return Response(
                    status_code=416,
                    headers={
                        "Content-Range": f"bytes */{total_size}",
                        "Accept-Ranges": "bytes",
                    },
                )
            end = min(end, total_size - 1)

    content_length = (end - start + 1) if total_size > 0 else 0
    status_code = 206 if is_range else 200

    ascii_base = safe_base.encode("ascii", "ignore").decode("ascii").replace('"', "") or "preview"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Type": media_type,
        "Cache-Control": "public, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'inline; filename="{ascii_base}"; filename*=UTF-8\'\'{quoted_name}',
    }
    if is_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"

    if request.method == "HEAD":
        return Response(status_code=status_code, headers=headers)

    if total_size == 0:
        return Response(content=b"", status_code=status_code, headers=headers, media_type=media_type)

    async def stream_generator():
        try:
            async for chunk in storage.stream_file(
                folder_name=folder_name,
                msg_ids=record.msg_ids,
                start=start,
                end=end,
                filename=file_id,
                file_hash=record.hash or "",
                file_size=total_size,
            ):
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            return
        except Exception as exc:
            log.warning("SYSTEM: Preview stream error for %s: %s", file_id, exc)
            return

    return StreamingResponse(
        stream_generator(),
        status_code=status_code,
        headers=headers,
        media_type=media_type,
    )


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
