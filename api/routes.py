import os
import shutil
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse

from config.settings import TEMP_DIR
from core.chunk_manager import compute_hash, split_file, merge_chunks, cleanup_chunks
from core.crypto_manager import encrypt_file, decrypt_file
from core.uploader import upload_chunks, delete_messages
from core.downloader import download_chunks
from storage.database import FileRecord

router = APIRouter()

# Read the passphrase from environment variable
PASSPHRASE = os.getenv("PASSPHRASE", "default_secret_passphrase")
from core.crypto_manager import derive_key
KEY = derive_key(PASSPHRASE)


@router.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    """Uploads a file to Telegram storage."""
    tg_client = request.app.state.tg_client
    db = request.app.state.db

    # Save to temp locally
    temp_file_path = TEMP_DIR / file.filename
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save temporary file: {e}")

    file_size = temp_file_path.stat().st_size
    rel_path = file.filename
    new_hash = compute_hash(temp_file_path)

    try:
        existing = db.get_file(rel_path)
        if existing and existing.hash == new_hash:
            temp_file_path.unlink(missing_ok=True)
            return {"message": f"Skipped {rel_path} (unchanged)"}

        channel = await tg_client.ensure_channel()

        if existing:
            await delete_messages(tg_client.client, channel, existing.msg_ids)

        enc_path = TEMP_DIR / f"{temp_file_path.name}.enc"
        encrypt_file(temp_file_path, enc_path, KEY)

        chunk_paths = split_file(enc_path)
        msg_ids = await upload_chunks(tg_client.client, channel, chunk_paths)

        record = FileRecord(
            path=rel_path,
            hash=new_hash,
            size=file_size,
            chunks=len(chunk_paths),
            msg_ids=msg_ids,
        )
        db.upsert_file(record)

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")
    finally:
        # Cleanup temp local files
        cleanup_chunks(chunk_paths if 'chunk_paths' in locals() else [])
        if 'enc_path' in locals():
            enc_path.unlink(missing_ok=True)
        temp_file_path.unlink(missing_ok=True)

    return {"message": "File uploaded successfully", "file": {"name": rel_path, "size": file_size}}


@router.get("/files")
def list_files(request: Request):
    """Returns list of stored files from the database."""
    db = request.app.state.db
    files = db.get_all_files()
    return [{"id": f.path, "name": f.path, "size": f.size} for f in files]


def cleanup_file_task(path: Path):
    """Background task to remove temp file after streaming."""
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


@router.get("/download/{file_id}")
async def download_file(file_id: str, request: Request, background_tasks: BackgroundTasks):
    """Downloads a file by retrieving chunks, merging, and decrypting."""
    tg_client = request.app.state.tg_client
    db = request.app.state.db

    record = db.get_file(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        channel = await tg_client.ensure_channel()
        chunk_paths = await download_chunks(tg_client.client, channel, record.msg_ids)

        merged_enc = TEMP_DIR / f"{Path(file_id).name}.enc"
        merge_chunks(chunk_paths, merged_enc)

        decrypted = TEMP_DIR / Path(file_id).name
        decrypt_file(merged_enc, decrypted, KEY)

        cleanup_chunks(chunk_paths)
        merged_enc.unlink(missing_ok=True)

        def file_iterator():
            with open(decrypted, "rb") as f:
                while chunk := f.read(8 * 1024 * 1024):
                    yield chunk

        background_tasks.add_task(cleanup_file_task, decrypted)

        return StreamingResponse(
            file_iterator(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={file_id}"}
        )

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Download failed: {exc}")


@router.delete("/file/{file_id}")
async def delete_file(file_id: str, request: Request):
    """Deletes a file from Telegram and database."""
    tg_client = request.app.state.tg_client
    db = request.app.state.db

    record = db.get_file(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        channel = await tg_client.ensure_channel()
        await delete_messages(tg_client.client, channel, record.msg_ids)
        db.delete_file(file_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}")

    return {"message": "File deleted successfully"}
