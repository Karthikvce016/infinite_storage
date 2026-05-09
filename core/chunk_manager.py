"""
chunk_manager.py – File splitting, merging, and hashing for Telegram Drive.

Telegram imposes a 2 GB upload limit; we chunk at 1.9 GB to stay safe.
"""

import hashlib
import math
from pathlib import Path
from typing import List

from config.settings import CHUNK_SIZE, TEMP_DIR


def compute_hash(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    """Return the hex-encoded SHA-256 hash of *path*."""
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            data = f.read(block_size)
            if not data:
                break
            sha.update(data)
    return sha.hexdigest()


def split_file(path: Path, chunk_size: int = CHUNK_SIZE) -> List[Path]:
    """
    Split *path* into sequentially numbered chunks inside TEMP_DIR.

    Returns a list of chunk file paths in order.
    """
    file_size = path.stat().st_size
    num_chunks = max(1, math.ceil(file_size / chunk_size))
    chunk_paths: List[Path] = []

    with open(path, "rb") as src:
        for i in range(num_chunks):
            chunk_name = f"{path.stem}.chunk{i}{path.suffix}"
            chunk_path = TEMP_DIR / chunk_name
            with open(chunk_path, "wb") as dst:
                remaining = chunk_size
                while remaining > 0:
                    block = src.read(min(remaining, 8 * 1024 * 1024))
                    if not block:
                        break
                    dst.write(block)
                    remaining -= len(block)
            chunk_paths.append(chunk_path)

    return chunk_paths


def merge_chunks(chunk_paths: List[Path], output_path: Path) -> None:
    """Concatenate *chunk_paths* in order and write to *output_path*."""
    with open(output_path, "wb") as dst:
        for cp in chunk_paths:
            with open(cp, "rb") as src:
                while True:
                    block = src.read(8 * 1024 * 1024)
                    if not block:
                        break
                    dst.write(block)


def cleanup_chunks(chunk_paths: List[Path]) -> None:
    """Remove temporary chunk files."""
    for cp in chunk_paths:
        try:
            cp.unlink(missing_ok=True)
        except OSError:
            pass

