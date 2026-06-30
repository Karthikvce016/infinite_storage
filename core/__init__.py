"""
core – Business logic for Telegram Drive.

Modules:
    storage/            – Pluggable storage provider interface and implementations
    rate_limiter        – Async token-bucket rate limiter
    chunk_manager       – File splitting, merging, and hashing
    uploader            – Rate-limited chunk uploader (Telegram)
    downloader          – Rate-limited chunk downloader (Telegram)
    db_rebuild          – Reconstruct file index from storage backend
"""
