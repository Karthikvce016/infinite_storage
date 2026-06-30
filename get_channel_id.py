"""
get_channel_id.py — Quick script to find the correct channel ID.

Run this to see all channels/groups your bot is in.
Usage: python get_channel_id.py
"""
import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")


async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)

    me = await client.get_me()
    print(f"\n✅ Connected as @{me.username} (id={me.id})\n")

    # Try to get updates — bots learn about channels when they receive messages
    print("Checking for recent updates...\n")
    
    # The bot needs to have received at least one message in the channel.
    # Let's try resolving the channel from the env
    channel_id_str = os.getenv("STORAGE_CHANNEL_ID", "")
    if channel_id_str:
        print(f"Attempting to resolve STORAGE_CHANNEL_ID={channel_id_str}...")
        try:
            entity = await client.get_entity(int(channel_id_str))
            print(f"  ✅ Resolved: {entity.title} (id={entity.id})")
        except Exception as e:
            print(f"  ❌ Failed: {e}")
    
    print("\n" + "=" * 50)
    print("To get your channel ID:")
    print("1. Create a private channel on Telegram")
    print("2. Add @Infiamadeusbot as an admin")
    print("3. Send any message in the channel")
    print("4. Forward that message to @userinfobot")
    print("5. @userinfobot will reply with the channel ID")
    print("6. Update STORAGE_CHANNEL_ID in .env with that ID")
    print("=" * 50)

    await client.disconnect()


asyncio.run(main())
