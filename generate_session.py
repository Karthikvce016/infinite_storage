"""
generate_session.py – Generate a Telegram session file for server authentication.

Reads API_ID and API_HASH from environment variables (or .env file).
Prompts for phone number and OTP, then saves telegram.session and exits.
"""

import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

if not API_ID or not API_HASH:
    print("Error: API_ID and API_HASH must be set in .env or as environment variables.")
    exit(1)


async def main():
    client = TelegramClient("telegram", API_ID, API_HASH)
    await client.start()
    print("Telegram session created successfully")
    await client.disconnect()


asyncio.run(main())
