"""
base.py – Abstract storage provider interface for Telegram Drive.

Any storage backend (Telegram, S3, local disk) must implement this
interface to be used by the application.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional


class StorageProvider(ABC):
    """
    Abstract interface for blob storage backends.

    The application never talks to Telegram (or any other backend) directly.
    All file operations go through this interface, making the storage layer
    completely swappable.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the storage backend."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Cleanly shut down the connection."""
        ...

    @abstractmethod
    async def is_ready(self) -> bool:
        """Return True if the backend is connected and operational."""
        ...

    # ── Folder operations ────────────────────────────────────
    @abstractmethod
    async def create_folder(self, name: str) -> dict:
        """
        Create a new folder.

        Returns a dict with at least:
            { "name": str, "channel_id": int }
        """
        ...

    @abstractmethod
    async def list_folders(self) -> List[dict]:
        """
        List all folders.

        Each dict has at least:
            { "name": str, "channel_id": int }
        """
        ...

    @abstractmethod
    async def get_folder(self, name: str) -> Optional[object]:
        """
        Get a folder handle by name.

        Returns a backend-specific entity (e.g., Channel for Telegram)
        or None if the folder does not exist.
        """
        ...

    @abstractmethod
    async def rename_folder(self, old_name: str, new_name: str) -> None:
        """Rename a folder."""
        ...

    @abstractmethod
    async def delete_folder(self, name: str) -> None:
        """Delete a folder and all its contents."""
        ...

    # ── File operations ──────────────────────────────────────
    @abstractmethod
    async def upload_file(
        self,
        folder_name: str,
        chunk_paths: List[Path],
        filename: str,
        file_hash: str,
    ) -> List[int]:
        """
        Upload file chunks to the given folder.

        Returns an ordered list of backend-specific message/object IDs.
        """
        ...

    @abstractmethod
    async def download_file(
        self,
        folder_name: str,
        msg_ids: List[int],
        dest_dir: Path,
    ) -> List[Path]:
        """
        Download file chunks from the given folder.

        Returns an ordered list of local chunk paths.
        """
        ...

    @abstractmethod
    async def delete_file(
        self,
        folder_name: str,
        msg_ids: List[int],
    ) -> None:
        """Delete a file's chunks from the backend."""
        ...

    # ── Messaging (sub-folder pointers) ────────────────────
    @abstractmethod
    async def send_message(self, folder_name: str, text: str) -> int:
        """
        Send a text message to the given folder's channel.

        Returns the message ID of the sent message.
        Used to post sub-folder link pointers in parent channels.
        """
        ...

    # ── Rebuild support ──────────────────────────────────────
    @abstractmethod
    async def scan_folder_messages(self, folder_name: str) -> List[dict]:
        """
        Scan all messages in a folder for DB rebuild purposes.

        Returns a list of dicts, each representing a message with media:
            {
                "msg_id": int,
                "caption": str,
                "file_name": str | None,
                "file_size": int,
            }
        """
        ...
