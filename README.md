# Telegram Drive

A web application that provides Google-Drive-like file storage using a private Telegram channel as encrypted backend storage.

## Features

- **AES-256-GCM encryption** — files are encrypted before leaving your machine
- **Automatic chunking** — large files are split into ≤ 1.9 GB chunks to respect Telegram limits
- **Parallel uploads** — chunks are uploaded concurrently (semaphore-limited) for speed
- **Two-step upload optimisation** — `upload_file()` + `send_file()` for faster throughput
- **SHA-256 change detection** — only changed files are re-uploaded
- **SQLite index** — maps local files to Telegram message IDs
- **Restore system** — download, merge, and decrypt all files on a new machine
- **FloodWait handling** — automatic sleep & retry on Telegram rate limits
- **FastAPI Web Backend** — REST API with upload, download, list, and delete endpoints
- **Responsive Web UI** — works on desktop and mobile browsers

## Project Structure

```
infinite_storage/
├── main.py
├── requirements.txt
├── Procfile
├── .env.example
├── README.md
├── api/
│   ├── __init__.py
│   ├── server.py          # FastAPI app setup & static file mount
│   └── routes.py          # REST endpoints
├── config/
│   ├── __init__.py
│   └── settings.py        # Env-var driven configuration
├── core/
│   ├── __init__.py
│   ├── telegram_client.py
│   ├── uploader.py
│   ├── downloader.py
│   ├── chunk_manager.py
│   ├── crypto_manager.py
│   ├── file_watcher.py
│   └── sync_manager.py
├── frontend/
│   ├── index.html
│   ├── upload.js
│   └── styles.css
├── storage/
│   ├── __init__.py
│   └── database.py
└── ui/                    # Legacy desktop UI (not used by web backend)
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

### 3. Configure Environment Variables

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Then edit `.env`:

```
API_ID=12345678
API_HASH=your_api_hash_here
CHANNEL_NAME=TelegramDriveStorage
SESSION_NAME=telegram_drive_session
```

| Variable        | Required | Description                                       |
|-----------------|----------|---------------------------------------------------|
| `API_ID`        | ✅       | Telegram API ID from https://my.telegram.org      |
| `API_HASH`      | ✅       | Telegram API Hash                                  |
| `CHANNEL_NAME`  | No       | Channel name for storage (default: `TelegramDriveStorage`) |
| `SESSION_NAME`  | No       | Telethon session file name (default: `telegram_drive_session`) |
| `PORT`          | No       | Server port (default: `8000`)                      |
| `PASSPHRASE`    | No       | AES encryption passphrase                          |

> **⚠ Never commit your `.env` file.** It is already listed in `.gitignore`.

### 4. Run

```bash
python main.py
```

Open <http://localhost:8000> in your browser to access the web UI.

### 5. Deploy to Cloud (Railway / Render)

1. Push your repository to GitHub.
2. Connect the repository on your hosting platform.
3. Set the required environment variables (`API_ID`, `API_HASH`, etc.) in the platform dashboard.
4. The `Procfile` (`web: python main.py`) tells the platform how to start the app.
5. The server automatically binds to the `PORT` provided by the platform.

## Libraries

| Library          | Purpose                         |
|------------------|----------------------------------|
| telethon         | Telegram MTProto client          |
| cryptography     | AES-256-GCM encryption          |
| watchdog         | Filesystem event monitoring      |
| fastapi          | REST API framework               |
| uvicorn          | ASGI server                      |
| python-dotenv    | Load `.env` files                |
| aiofiles         | Async file I/O                   |
| sqlite3          | Local index database (stdlib)    |
| hashlib          | SHA-256 hashing (stdlib)         |
| asyncio          | Async orchestration (stdlib)     |

