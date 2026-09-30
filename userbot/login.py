"""One-time interactive login. Run it yourself: it asks for your phone, the code Telegram sends you, and 2FA password."""
from telethon.sync import TelegramClient

from .config import API_HASH, API_ID, SESSION_PATH

with TelegramClient(SESSION_PATH, API_ID, API_HASH) as client:
    me = client.get_me()
    print(f"Logged in as {me.first_name} (@{me.username}, id={me.id}). Session saved to {SESSION_PATH}.session")
