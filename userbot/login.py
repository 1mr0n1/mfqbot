"""One-time interactive login. Run it yourself: it asks for your phone, the code Telegram sends you, and 2FA password.

  .venv/bin/python -m userbot.login          # the account the userbot runs on
  .venv/bin/python -m userbot.login main     # an extra session, e.g. your main account for learn_style
"""
import sys

from telethon.sync import TelegramClient

from .config import API_HASH, API_ID, HERE, SESSION_PATH

session = str(HERE / sys.argv[1]) if len(sys.argv) > 1 else SESSION_PATH

with TelegramClient(session, API_ID, API_HASH) as client:
    me = client.get_me()
    print(f"Logged in as {me.first_name} (@{me.username}, id={me.id}). Session saved to {session}.session")
