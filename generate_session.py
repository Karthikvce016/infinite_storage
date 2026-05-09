"""
generate_session.py – Generate a Telegram StringSession for server authentication.

Reads API_ID and API_HASH from environment variables (or .env file).
Prompts for phone number and OTP, then prints the session string.
Add the printed string to your .env file as SESSION_STRING=<value>.
"""

import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

if not API_ID or not API_HASH:
    print("Error: API_ID and API_HASH must be set in .env or as environment variables.")
    exit(1)


async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start()

    session_string = client.session.save()
    print("\n✅ Telegram session created successfully!\n")
    print("Add this to your .env file or Render dashboard:\n")
    print(f"SESSION_STRING={session_string}")
    print()

    await client.disconnect()


asyncio.run(main())
