import shutil
import urllib.parse
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, Form, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from config.settings import TEMP_DIR
from core.chunk_manager import compute_hash, split_file, merge_chunks, cleanup_chunks
from core.uploader import upload_chunks, delete_messages
from core.downloader import download_chunks
from storage.database import FileRecord
from api.auth_routes import get_current_user

router = APIRouter()


@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    alias: Optional[str] = Form(None),
    user_phone: str = Depends(get_current_user),
):
    """Uploads a file to the user's Telegram Saved Messages."""
    auth_manager = request.app.state.auth_manager
    db = request.app.state.db

    try:
        client = await auth_manager.get_user_client(user_phone)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

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
        # Add the original extension if the alias doesn't already have one
        if not Path(alias_name).suffix:
            alias_name += original_ext
        rel_path = alias_name
    else:
        rel_path = file.filename
    new_hash = compute_hash(temp_file_path)

    chunk_paths = []
    try:
        existing = db.get_file(rel_path, user_phone)
        if existing and existing.hash == new_hash:
            temp_file_path.unlink(missing_ok=True)
            return {"message": f"Skipped {rel_path} (unchanged)"}

        if existing:
            await delete_messages(client, "me", existing.msg_ids)

        # Split raw file directly (no encryption)
        chunk_paths = split_file(temp_file_path)
        msg_ids = await upload_chunks(client, "me", chunk_paths)

        record = FileRecord(
            path=rel_path,
            hash=new_hash,
            size=file_size,
            chunks=len(chunk_paths),
            user_phone=user_phone,
            msg_ids=msg_ids,
        )
        db.upsert_file(record)

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")
    finally:
        # Cleanup temp local files
        cleanup_chunks(chunk_paths)
        temp_file_path.unlink(missing_ok=True)

    return {"message": "File uploaded successfully", "file": {"name": rel_path, "size": file_size}}


@router.get("/files")
def list_files(request: Request, user_phone: str = Depends(get_current_user)):
    """Returns list of stored files for the authenticated user."""
    db = request.app.state.db
    files = db.get_all_files(user_phone)
    return [{"id": f.path, "name": f.path, "size": f.size} for f in files]


@router.get("/download/{file_id:path}")
async def download_file(
    file_id: str,
    request: Request,
    user_phone: str = Depends(get_current_user),
):
    """Downloads a file by retrieving chunks from user's Saved Messages."""
    auth_manager = request.app.state.auth_manager
    db = request.app.state.db

    try:
        client = await auth_manager.get_user_client(user_phone)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    # URL-decode in case the filename was percent-encoded
    file_id = urllib.parse.unquote(file_id)

    record = db.get_file(file_id, user_phone)
    if not record:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        chunk_paths = await download_chunks(client, "me", record.msg_ids)

        # Ensure TEMP_DIR exists (may be wiped between restarts)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)

        # Merge chunks directly to final file (no decryption)
        merged = TEMP_DIR / Path(file_id).name
        merge_chunks(chunk_paths, merged)

        cleanup_chunks(chunk_paths)

        file_size = merged.stat().st_size

        async def file_iterator():
            """Async generator that streams the file and cleans up after."""
            try:
                with open(merged, "rb") as f:
                    while chunk := f.read(8 * 1024 * 1024):
                        yield chunk
            finally:
                # Cleanup only AFTER streaming is fully done or aborted
                try:
                    merged.unlink(missing_ok=True)
                except Exception:
                    pass

        # Properly quote the filename for Content-Disposition (RFC 6266)
        safe_filename = Path(file_id).name
        return StreamingResponse(
            file_iterator(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_filename}"',
                "Content-Length": str(file_size),
            },
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Download failed: {exc}")


@router.delete("/file/{file_id:path}")
async def delete_file(
    file_id: str,
    request: Request,
    user_phone: str = Depends(get_current_user),
):
    """Deletes a file from user's Telegram and database."""
    auth_manager = request.app.state.auth_manager
    db = request.app.state.db

    try:
        client = await auth_manager.get_user_client(user_phone)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    # URL-decode in case the filename was percent-encoded
    file_id = urllib.parse.unquote(file_id)

    record = db.get_file(file_id, user_phone)
    if not record:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        await delete_messages(client, "me", record.msg_ids)
        db.delete_file(file_id, user_phone)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}")

    return {"message": "File deleted successfully"}
