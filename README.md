# Telegram Drive

A desktop application that provides Google-Drive-like folder synchronization using a private Telegram channel as encrypted backend storage.

## Features

- **AES-256-GCM encryption** — files are encrypted before leaving your machine
- **Automatic chunking** — large files are split into ≤ 1.9 GB chunks to respect Telegram limits
- **Parallel uploads** — chunks are uploaded concurrently (semaphore-limited) for speed
- **Two-step upload optimisation** — `upload_file()` + `send_file()` for faster throughput
- **watchdog folder monitoring** — creation, modification, deletion, and rename events
- **SHA-256 change detection** — only changed files are re-uploaded
- **SQLite index** — maps local files to Telegram message IDs
- **Restore system** — download, merge, and decrypt all files on a new machine
- **FloodWait handling** — automatic sleep & retry on Telegram rate limits
- **Dark-themed PyQt6 UI** — progress bar, file list, storage stats

## Project Structure

Use a project root folder **without spaces** (e.g. `infinite_storage`). If your folder is named with spaces, rename it for reliable Python imports.

```
infinite_storage/
├── main.py
├── requirements.txt
├── README.md
├── config/
│   ├── __init__.py
│   └── settings.py        # API_ID, API_HASH, paths, etc.
├── core/
│   ├── __init__.py
│   ├── telegram_client.py
│   ├── uploader.py
│   ├── downloader.py
│   ├── chunk_manager.py
│   ├── crypto_manager.py
│   ├── file_watcher.py
│   └── sync_manager.py
├── storage/
│   ├── __init__.py
│   └── database.py
└── ui/
    ├── __init__.py
    ├── main_window.py     # Main window & drop zone
    ├── dialogs.py         # Login, passphrase dialogs
    └── styles.py          # Stylesheet & theme constants
```

## Setup

### 1. Get Telegram API credentials

1. Visit <https://my.telegram.org> and log in.
2. Go to **API development tools** → create a new application.
3. Note your **API ID** (integer) and **API Hash** (string).

### 2. Install dependencies

```bash
cd infinite_storage
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure

Open `config/settings.py` and set your credentials:

```python
API_ID  = 12345678          # your api_id
API_HASH = "abcdef1234..."  # your api_hash
```

### 4. Run

From the `infinite_storage` directory:

```bash
python main.py
```

1. A login dialog appears — enter your Telegram phone number and the OTP code.
2. Set an encryption passphrase (remember it — you need it to decrypt files).
3. The main window opens. Click **Browse** to choose a sync folder, then **Start Sync**.
4. Any file placed in the sync folder is automatically encrypted, chunked, and uploaded to a private channel called **TelegramDriveStorage**.

### 5. Restore on a new machine

1. Copy `~/.telegram_drive/index.db` and `~/.telegram_drive/salt.bin` to the new machine.
2. Run `python main.py`, log in, enter the **same passphrase**.
3. Click **Restore All** — files are downloaded, merged, and decrypted.

## Libraries

| Library        | Purpose                         |
|----------------|----------------------------------|
| telethon       | Telegram MTProto client          |
| cryptography   | AES-256-GCM encryption          |
| watchdog       | Filesystem event monitoring      |
| PyQt6          | Desktop UI                       |
| aiofiles       | Async file I/O                   |
| sqlite3        | Local index database (stdlib)    |
| hashlib        | SHA-256 hashing (stdlib)         |
| asyncio        | Async orchestration (stdlib)     |
