"""
stream_buffer.py – Sparse-file streaming buffer with live range fulfillment
and automatic web-optimized MP4 faststart remuxing.

Provides seamless HTTP 206 Partial Content video and media streaming
from Telegram without saturating rate limits, zero-filling unread ranges,
or desynchronizing audio/video tracks in modern browsers (Chrome/Brave/Safari).
"""

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional, Set
from telethon import TelegramClient

from config.settings import TEMP_DIR

log = logging.getLogger(__name__)

CACHE_DIR = TEMP_DIR / "stream_cache"
CHUNK_SIZE = 524288  # 512 KB Telegram chunk


def remux_to_web_mp4(src_path: Path, dest_path: Path) -> bool:
    """
    Remux a video (especially Apple QuickTime .mov or non-faststart MP4) into a
    fast-start MP4 with moov atom at the front and standard ISO MPEG-4 AAC audio.
    Does NOT re-encode video/audio packets; completes in a few seconds with zero quality loss.
    """
    if not src_path.exists() or src_path.stat().st_size == 0:
        return False

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dest = dest_path.with_suffix(".tmp.mp4")

    # 1. macOS native avconvert (built into all Macs)
    if shutil.which("avconvert"):
        try:
            res = subprocess.run(
                ["avconvert", "-s", str(src_path), "-p", "PresetPassthrough", "-o", str(temp_dest), "--replace"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if res.returncode == 0 and temp_dest.exists() and temp_dest.stat().st_size > 0:
                temp_dest.replace(dest_path)
                log.info("SYSTEM: remux_to_web_mp4 via avconvert succeeded → %s (%d bytes)", dest_path.name, dest_path.stat().st_size)
                return True
        except Exception as exc:
            log.warning("SYSTEM: avconvert remux failed: %s", exc)

    # 2. ffmpeg fallback (Linux / server environments)
    if shutil.which("ffmpeg"):
        try:
            res = subprocess.run(
                ["ffmpeg", "-y", "-i", str(src_path), "-c", "copy", "-movflags", "+faststart", str(temp_dest)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if res.returncode == 0 and temp_dest.exists() and temp_dest.stat().st_size > 0:
                temp_dest.replace(dest_path)
                log.info("SYSTEM: remux_to_web_mp4 via ffmpeg succeeded → %s (%d bytes)", dest_path.name, dest_path.stat().st_size)
                return True
        except Exception as exc:
            log.warning("SYSTEM: ffmpeg remux failed: %s", exc)

    temp_dest.unlink(missing_ok=True)
    return False


class FileStreamBuffer:
    """
    Manages a sparse file cache for a single file stored in Telegram.
    Allows concurrent, random-access byte range reading while prefetching
    tail metadata (e.g. MP4 moov atom) and streaming content on-demand.
    """

    def __init__(
        self,
        client: TelegramClient,
        entity,
        msg_or_msgs,
        path: Path,
        file_size: int,
        chunk_size: int = CHUNK_SIZE,
    ):
        self.client = client
        self.entity = entity
        self.msgs = msg_or_msgs if isinstance(msg_or_msgs, list) else [msg_or_msgs]
        self.path = path
        self.file_size = file_size
        self.chunk_size = chunk_size
        self.num_chunks = (file_size + chunk_size - 1) // chunk_size if file_size > 0 else 0
        self.cached_chunks: Set[int] = set()
        self.in_flight: Dict[int, asyncio.Future] = {}
        self.lock = asyncio.Lock()
        self.download_lock = asyncio.Lock()  # Serializes Telegram MTProto downloads to prevent connection reset
        self.prefetch_task: Optional[asyncio.Task] = None

        # Corresponding web MP4 path
        clean_stem = path.stem
        self.remux_path = path.parent / f"{clean_stem}.mp4"

        # Build chunk offset map for multi-chunk (or single) messages
        self.chunk_map: List[dict] = []
        curr = 0
        for m in self.msgs:
            sz = m.file.size
            self.chunk_map.append({
                "msg": m,
                "start": curr,
                "end": curr + sz - 1,
                "size": sz,
            })
            curr += sz

        # Initialize sparse file on disk (APFS / ext4 allocate 0 blocks until written)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.stat().st_size != file_size:
            with open(path, "wb") as f:
                f.truncate(file_size)

        # Trigger prefetch of tail (moov atom) and head
        if self.file_size > 0:
            self.start_prefetch()

    def start_prefetch(self):
        """Starts background prefetching of metadata and initial chunks."""
        if self.prefetch_task is None or self.prefetch_task.done():
            self.prefetch_task = asyncio.create_task(self._prefetch_loop())

    async def _prefetch_loop(self):
        """Prefetch metadata (head and tail moov atom) for instant media start."""
        try:
            # 1. Prefetch chunk 0 (container header)
            if 0 not in self.cached_chunks:
                await self.get_chunk(0)

            # 2. Prefetch tail chunks (where MOOV atom lives in non-faststart MP4/MOV)
            tail_count = min(6, self.num_chunks)
            for idx in range(self.num_chunks - 1, self.num_chunks - 1 - tail_count, -1):
                if idx not in self.cached_chunks:
                    await self.get_chunk(idx)

            # 3. If file is small (< 30 MB), prefetch the rest in background
            if self.file_size < 30 * 1024 * 1024:
                for idx in range(self.num_chunks):
                    if idx not in self.cached_chunks:
                        await self.get_chunk(idx)
                        await asyncio.sleep(0.02)

            # If all chunks are cached, trigger faststart web-MP4 remux
            if len(self.cached_chunks) >= self.num_chunks and self.file_size > 0:
                self._check_remux()

        except (asyncio.CancelledError, GeneratorExit):
            return
        except Exception as exc:
            log.debug("SYSTEM: Prefetch loop paused/finished: %s", exc)

    def _check_remux(self):
        """If completely cached and is a video, remux to web-optimized MP4."""
        ext = self.path.suffix.lower()
        if ext in (".mov", ".mp4", ".m4v") and not self.remux_path.exists():
            asyncio.get_event_loop().run_in_executor(
                None, remux_to_web_mp4, self.path, self.remux_path
            )

    async def get_chunk(self, idx: int) -> bool:
        """Ensure chunk  is downloaded and written into the sparse file."""
        if idx < 0 or idx >= self.num_chunks:
            return False
        if idx in self.cached_chunks:
            return True

        async with self.lock:
            if idx in self.cached_chunks:
                return True
            if idx in self.in_flight:
                fut = self.in_flight[idx]
            else:
                loop = asyncio.get_running_loop()
                fut = loop.create_future()
                self.in_flight[idx] = fut
                asyncio.create_task(self._fetch_chunk(idx, fut))

        try:
            await fut
            return idx in self.cached_chunks
        except Exception:
            return False

    async def _fetch_chunk(self, idx: int, fut: asyncio.Future):
        """Fetch chunk  from Telegram and write to sparse file."""
        offset = idx * self.chunk_size
        needed = min(self.chunk_size, self.file_size - offset)
        if needed <= 0:
            self.cached_chunks.add(idx)
            if not fut.done():
                fut.set_result(True)
            return

        # Find which message contains this offset
        target_msg = self.msgs[0]
        rel_offset = offset
        for cm in self.chunk_map:
            if cm["start"] <= offset <= cm["end"]:
                target_msg = cm["msg"]
                rel_offset = offset - cm["start"]
                break

        # Acquire download_lock so only one iter_download runs at a time over MTProto
        try:
            async with self.download_lock:
                if idx in self.cached_chunks:
                    if not fut.done():
                        fut.set_result(True)
                    return

                buf = bytearray()
                async for chunk in self.client.iter_download(
                    target_msg.media,
                    offset=rel_offset,
                    request_size=self.chunk_size,
                    file_size=target_msg.file.size,
                ):
                    buf.extend(chunk)
                    if len(buf) >= needed:
                        break

                data_to_write = buf[:needed]
                if len(data_to_write) > 0:
                    with open(self.path, "r+b") as f:
                        f.seek(offset)
                        f.write(data_to_write)
                        f.flush()

                self.cached_chunks.add(idx)
                if not fut.done():
                    fut.set_result(True)
        except Exception as exc:
            log.warning("SYSTEM: Failed to fetch chunk %d for %s: %s", idx, self.path.name, exc)
            if not fut.done():
                fut.set_exception(exc)
        finally:
            async with self.lock:
                self.in_flight.pop(idx, None)

    async def stream_range(self, start: int, end: int, chunk_step: int = 262144) -> AsyncIterator[bytes]:
        """
        Stream exact bytes [start, end] from the buffer file.
        Ensures chunks are verified and downloaded prior to reading,
        preventing empty-hole sparse zeros from corrupting the media decoder.
        """
        if self.file_size == 0 or start > end:
            return

        curr = start
        while curr <= end:
            chunk_idx = curr // self.chunk_size
            ok = await self.get_chunk(chunk_idx)
            if not ok and chunk_idx not in self.cached_chunks:
                log.warning("SYSTEM: Chunk %d unavailable, ending stream range at %d", chunk_idx, curr)
                break

            chunk_boundary = min((chunk_idx + 1) * self.chunk_size - 1, end, self.file_size - 1)
            read_len = chunk_boundary - curr + 1

            try:
                with open(self.path, "rb") as f:
                    f.seek(curr)
                    data = f.read(read_len)
            except Exception as exc:
                log.warning("SYSTEM: Error reading cache file at %d: %s", curr, exc)
                break

            if not data:
                break

            # Yield in smaller steps if needed for smooth streaming
            pos = 0
            while pos < len(data):
                step = data[pos : pos + chunk_step]
                yield step
                pos += len(step)

            curr += len(data)


class StreamBufferManager:
    """Manages active FileStreamBuffer instances with automatic cleanup."""

    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.buffers: Dict[str, FileStreamBuffer] = {}
        self.lock = asyncio.Lock()

    def get_existing_buffer(self, file_hash: str, filename: str) -> Optional[FileStreamBuffer]:
        """Return an existing buffer if cached, without any async/lock overhead."""
        key = f"{file_hash}_{filename}"
        buf = self.buffers.get(key)
        if buf and buf.path.exists() and buf.path.stat().st_size == buf.file_size:
            return buf
        return None

    def get_web_mp4_path(self, file_hash: str, filename: str) -> Optional[Path]:
        """Return the path to a converted web-optimized MP4 if it exists."""
        clean_stem = Path(filename).stem.encode("ascii", "ignore").decode("ascii").replace("/", "_").replace(" ", "_") or "file"
        p = self.cache_dir / f"sb_{file_hash[:16]}_{clean_stem}.mp4"
        if p.exists() and p.stat().st_size > 0:
            return p
        return None

    async def get_buffer(
        self,
        client: TelegramClient,
        entity,
        msg_or_msgs,
        file_hash: str,
        filename: str,
        file_size: int,
    ) -> FileStreamBuffer:
        async with self.lock:
            key = f"{file_hash}_{filename}"
            if key in self.buffers:
                buf = self.buffers[key]
                if buf.path.exists() and buf.path.stat().st_size == file_size:
                    return buf

            # Clean name for filesystem
            clean_name = filename.encode("ascii", "ignore").decode("ascii").replace("/", "_").replace(" ", "_") or "file"
            cache_path = self.cache_dir / f"sb_{file_hash[:16]}_{clean_name}"
            buf = FileStreamBuffer(client, entity, msg_or_msgs, cache_path, file_size)
            self.buffers[key] = buf
            return buf

    def cleanup_old_buffers(self):
        """Clean up finished or unused buffer files if storage gets full."""
        try:
            for p in self.cache_dir.glob("sb_*"):
                if p.is_file():
                    p.unlink(missing_ok=True)
        except Exception:
            pass


stream_buffer_manager = StreamBufferManager()
