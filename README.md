# Telegram Drive

A self-hosted, Google-Drive-style file storage web app that uses **one private Telegram channel** as its storage backend.

## How it works

- All files are stored as documents in a **single private Telegram channel** (the bot must be an admin there).
- Files larger than `CHUNK_SIZE` (20 MB) are split into chunks; each chunk is uploaded as a separate message with a structured caption:
  `TGDrive|<filename>|<chunk_index>|<total_chunks>|<sha256_hash>`
- Folders are **logical only** (rows in the index DB) — they do *not* create separate Telegram channels. Every folder's chunks live in the same storage channel, tagged by caption.
- A SQLite/PostgreSQL index maps each file (per folder + owner) to its ordered list of Telegram message IDs.
- On startup (and via the "Rebuild Index" button) the app rescans the channel and reconstructs the index from captions — so a wiped/ephemeral disk loses nothing but the DB, which rebuilds itself.

## Project structure

```
infinite_storage/
├── main.py                  # Entry point: pre-flight checks, lifespan, uvicorn
├── requirements.txt
├── Procfile                 # web: python main.py
├── .env.example             # Copy to .env and fill in
├── api/
│   ├── server.py            # FastAPI app, CORS, static frontend mount
│   ├── auth_routes.py       # Password login → JWT cookie session
│   ├── folder_routes.py     # Folder CRUD (hierarchical, logical folders)
│   ├── routes.py            # Upload / download / preview / delete endpoints
│   └── debug_routes.py      # /api/debug/status, /api/debug/rebuild, download-test
├── config/
│   └── settings.py          # Env-var driven configuration
├── core/
│   ├── chunk_manager.py     # Split / merge / SHA-256 hashing
│   ├── uploader.py          # Rate-limited chunk upload + caption format
│   ├── downloader.py        # Rate-limited chunk download
│   ├── rate_limiter.py      # Token-bucket limiter + FloodWait handling
│   ├── db_rebuild.py        # Reconstruct index from channel captions
│   └── storage/
│       ├── base.py          # StorageProvider interface
│       └── telegram_provider.py  # Telegram (Telethon/MTProto) implementation
├── storage/
│   └── database.py          # SQLAlchemy models + Database wrapper
└── frontend/                # Single-page UI (served at /)
    ├── index.html
    ├── app.js
    └── styles.css
```

## Setup

### 1. Get Telegram credentials

1. Visit <https://my.telegram.org> → **API development tools** → create an app. Note the **API_ID** and **API_HASH**.
2. Talk to **@BotFather** → `/newbot` → copy the **BOT_TOKEN**.
3. Create a **private channel** in Telegram (this is your storage).
4. Add the bot to the channel **as an admin** (with post/delete permissions).
5. Get the channel's numeric ID: forward any message from the channel to **@userinfobot** (IDs look like `-1001234567890`).

### 2. Install dependencies

```bash
cd infinite_storage
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# then edit .env — required keys: API_ID, API_HASH, BOT_TOKEN, STORAGE_CHANNEL_ID
```

| Variable | Required | Description |
|---|---|---|
| `API_ID` | ✅ | Telegram API ID from https://my.telegram.org |
| `API_HASH` | ✅ | Telegram API Hash |
| `BOT_TOKEN` | ✅ | Bot token from @BotFather (bot must be channel admin) |
| `STORAGE_CHANNEL_ID` | ✅ | Numeric ID of the private storage channel (e.g. `-1001234567890`) |
| `APP_PASSWORD` | No | Web UI password (**default: `admin`** — set your own!) |
| `DATABASE_URL` | No | PostgreSQL URL; omit for local SQLite (`index.db`) |
| `ALLOWED_ORIGINS` | No | Comma-separated origins for CORS (only if UI is served from another origin) |
| `RATE_LIMIT_DELAY` | No | Min seconds between Telegram API calls (default `2.0`) |
| `MAX_REQUESTS_PER_MINUTE` | No | Token-bucket cap (default `20`) |
| `PORT` | No | Server port (default `8000`; hosting platforms set it automatically) |

> **⚠ Never commit your `.env`** — it holds your bot token and account credentials.

### 4. Run

```bash
python main.py
```

Open <http://localhost:8000>, log in with `APP_PASSWORD`, create a folder, and upload.

### 5. Deploy (Railway / Render)

1. Push the repo to GitHub (`.gitignore` already excludes `venv/`, `.env`, `index.db`, `tmp/`, sessions).
2. Connect the repo on your hosting platform.
3. Set the required env vars (`API_ID`, `API_HASH`, `BOT_TOKEN`, `STORAGE_CHANNEL_ID`, `APP_PASSWORD`, optionally `DATABASE_URL`) in the dashboard.
4. The `Procfile` (`web: python main.py`) starts the app; it binds to the platform-provided `PORT`.
5. On ephemeral free tiers, set `DATABASE_URL` — otherwise the index DB resets per deploy (files stay safe in Telegram; hit **Rebuild Index** to restore the index).

## API overview

All `/api` endpoints except `/api/auth/*` require the session cookie (login via `POST /api/auth/login` with `{"password": "..."}`).

| Method & path | Purpose |
|---|---|
| `POST /api/auth/login` · `POST /api/auth/logout` · `GET /api/auth/check` | Session management |
| `GET /api/folders?parent_id=` · `POST /api/folders` | List / create (hierarchical) folders |
| `GET /api/folders/{id}/path` | Breadcrumb path |
| `PUT /api/folders/{id}` · `DELETE /api/folders/{id}` | Rename / delete folder (recursive) |
| `GET /api/folders/{id}/files` | List files in folder |
| `POST /api/folders/{id}/upload` | Multipart upload (`file`, optional `alias`) |
| `GET /api/folders/{id}/download/{file_id}` | Download (streams merged chunks) |
| `GET /api/folders/{id}/preview/{file_id}` | Inline preview (images/video/audio/PDF/text) |
| `DELETE /api/folders/{id}/files/{file_id}` | Delete file (Telegram messages + DB row) |
| `GET /api/debug/status` · `POST /api/debug/rebuild` | Diagnostics / manual index rebuild |

## Libraries

| Library | Purpose |
|---|---|
| telethon | Telegram MTProto client (bot login, chunk upload/download) |
| FastAPI + uvicorn | REST API + ASGI server |
| SQLAlchemy (+ asyncpg / psycopg2-binary) | Postgres index; SQLite fallback |
| PyJWT | Signed session cookies |
| python-dotenv | Load `.env` |
| aiofiles, python-multipart | Async I/O and multipart uploads |
