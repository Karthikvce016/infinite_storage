"""
folder_routes.py – Folder CRUD endpoints for Telegram Drive.

Each folder maps to a private Telegram channel prefixed with TGDrive_.
Uses the StorageProvider abstraction.
Supports hierarchical sub-folders: each folder has an optional parent_id.
When a sub-folder is created, the bot posts a link message in the parent channel.
"""

import logging

from fastapi import APIRouter, Request, HTTPException

from api.auth_routes import require_auth
from storage.database import FolderRecord

log = logging.getLogger(__name__)

router = APIRouter()


def _get_context(request: Request):
    """Extract storage, owner, and DB."""
    owner = require_auth(request)
    storage = request.app.state.storage
    db = request.app.state.db
    return storage, owner, db


@router.get("/folders")
async def list_folders(request: Request, parent_id: int = None):
    """
    List folders. If parent_id is given, return only children of that folder.
    If parent_id is None, return root-level folders.
    """
    storage, owner, db = _get_context(request)

    folders = db.get_child_folders(parent_id, owner)

    # If root and DB is empty (first time), ensure default folder exists
    # storage.list_folders() reads from DB so it can't be used as a fallback
    if parent_id is None and not folders:
        try:
            from config.settings import DEFAULT_FOLDER_NAME
            channel_id = 0
            if hasattr(storage, '_storage_channel_id') and storage._storage_channel_id:
                channel_id = storage._storage_channel_id
            db.upsert_folder(FolderRecord(
                name=DEFAULT_FOLDER_NAME,
                channel_id=channel_id,
                owner=owner,
                parent_id=None,
            ))
            folders = db.get_child_folders(None, owner)
        except Exception as exc:
            log.warning("SYSTEM: Failed to ensure default folder: %s", exc)

    return [
        {
            "id": f.id,
            "name": f.name,
            "channel_id": f.channel_id,
            "parent_id": f.parent_id,
        }
        for f in folders
    ]


@router.get("/folders/{folder_id:int}/path")
async def get_folder_path(folder_id: int, request: Request):
    """Return the breadcrumb path from root to this folder."""
    _, owner, db = _get_context(request)

    path = db.get_folder_path(folder_id, owner)
    return [
        {
            "id": f.id,
            "name": f.name,
            "channel_id": f.channel_id,
            "parent_id": f.parent_id,
        }
        for f in path
    ]


@router.post("/folders")
async def create_folder(request: Request):
    """Create a new folder, optionally as a child of parent_id."""
    storage, owner, db = _get_context(request)

    body = await request.json()
    name = body.get("name", "").strip()
    parent_id = body.get("parent_id", None)  # None = root folder

    if not name:
        raise HTTPException(status_code=400, detail="Folder name required")

    existing = db.get_folder(name, owner, parent_id=parent_id)
    if existing:
        raise HTTPException(status_code=409, detail="Folder already exists")

    try:
        result = await storage.create_folder(name)
        folder_id = db.upsert_folder(FolderRecord(
            name=name,
            channel_id=result["channel_id"],
            owner=owner,
            parent_id=parent_id,
        ))

        # If this is a sub-folder, post a link message in the parent channel
        if parent_id is not None:
            parent = db.get_folder_by_id(parent_id, owner)
            if parent:
                try:
                    link = await storage.get_channel_link(name)
                    await storage.send_message(
                        parent.name,
                        f"📁 Sub-folder: {name}\n🔗 {link}"
                    )
                except Exception as link_err:
                    log.warning(
                        "SYSTEM: Could not post sub-folder link in parent channel: %s",
                        link_err,
                    )

        return {
            "message": f"Folder '{name}' created",
            "id": folder_id,
            "name": name,
            "channel_id": result["channel_id"],
            "parent_id": parent_id,
        }
    except Exception as exc:
        log.exception("Failed to create folder %s", name)
        raise HTTPException(status_code=500, detail=f"Failed to create folder: {exc}")


@router.put("/folders/{folder_id:int}")
async def rename_folder(folder_id: int, request: Request):
    """Rename a folder by its ID."""
    storage, owner, db = _get_context(request)

    body = await request.json()
    new_name = body.get("name", "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="New folder name required")

    existing = db.get_folder_by_id(folder_id, owner)
    if not existing:
        raise HTTPException(status_code=404, detail="Folder not found")

    try:
        await storage.rename_folder(existing.name, new_name)
        db.rename_folder(existing.name, new_name, owner)
        return {"message": f"Folder renamed to '{new_name}'"}
    except Exception as exc:
        log.exception("Failed to rename folder %s", existing.name)
        raise HTTPException(status_code=500, detail=f"Failed to rename: {exc}")


@router.delete("/folders/{folder_id:int}")
async def delete_folder(folder_id: int, request: Request):
    """Delete a folder and all its files by ID."""
    storage, owner, db = _get_context(request)

    from config.settings import DEFAULT_FOLDER_NAME

    existing = db.get_folder_by_id(folder_id, owner)
    if not existing:
        raise HTTPException(status_code=404, detail="Folder not found")

    if existing.name == DEFAULT_FOLDER_NAME and existing.parent_id is None:
        raise HTTPException(status_code=400, detail="Cannot delete the default folder")

    # Also delete all child sub-folders recursively
    children = db.get_child_folders(folder_id, owner)
    for child in children:
        try:
            child_files = db.get_files_in_folder(child.name, owner)
            for cf in child_files:
                await storage.delete_file(child.name, cf.msg_ids)
                
            await storage.delete_folder(child.name)
            db.delete_files_in_folder(child.name, owner)
            db.delete_folder(child.name, owner)
        except Exception as child_err:
            log.warning("Failed to delete child folder %s: %s", child.name, child_err)

    try:
        await storage.delete_folder(existing.name)
        db.delete_files_in_folder(existing.name, owner)
        db.delete_folder(existing.name, owner)
        return {"message": f"Folder '{existing.name}' deleted"}
    except Exception as exc:
        log.exception("Failed to delete folder %s", existing.name)
        raise HTTPException(status_code=500, detail=f"Failed to delete: {exc}")
