"""Change your Telegram profile from the command line (works while the userbot is running).

  .venv/bin/python -m userbot.profile show
  .venv/bin/python -m userbot.profile name "John"
  .venv/bin/python -m userbot.profile surname "Smith"         # "-" clears it
  .venv/bin/python -m userbot.profile bio "just vibing 😭"     # "-" clears it
  .venv/bin/python -m userbot.profile photo path/to/image.jpg
"""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

from telethon import TelegramClient, errors, functions

from . import config as C


async def run(cmd: str, value: str | None):
    # Use a copy of the session so we don't fight the running userbot over its session file.
    with tempfile.TemporaryDirectory() as tmp:
        session = Path(tmp) / "profile"
        shutil.copy(f"{C.SESSION_PATH}.session", f"{session}.session")
        client = TelegramClient(str(session), C.API_ID, C.API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            raise SystemExit("Not logged in. Run once: .venv/bin/python -m userbot.login")
        try:
            clear = value == "-"
            if cmd == "name":
                await client(functions.account.UpdateProfileRequest(first_name=value[:64]))
            elif cmd == "surname":
                await client(functions.account.UpdateProfileRequest(last_name="" if clear else value[:64]))
            elif cmd == "bio":
                await client(functions.account.UpdateProfileRequest(about="" if clear else value))
            elif cmd == "photo":
                path = Path(value).expanduser()
                if not path.is_file():
                    raise SystemExit(f"No such file: {path}")
                await client(functions.photos.UploadProfilePhotoRequest(file=await client.upload_file(str(path))))
            elif cmd != "show":
                raise SystemExit(__doc__)

            me = await client.get_me()
            full = await client(functions.users.GetFullUserRequest("me"))
            if cmd != "show":
                print(f"✅ {cmd} updated")
            print(f"name:    {me.first_name or ''}\nsurname: {me.last_name or '—'}\n"
                  f"bio:     {full.full_user.about or '—'}\nphoto:   {'set' if me.photo else 'none'}")
        except errors.AboutTooLongError:
            raise SystemExit("Bio too long (70 characters max, 140 with Premium)")
        except errors.RPCError as e:
            raise SystemExit(f"Telegram refused: {e.__class__.__name__}")
        finally:
            await client.disconnect()


def main():
    if len(sys.argv) < 2 or (sys.argv[1] != "show" and len(sys.argv) < 3):
        raise SystemExit(__doc__)
    asyncio.run(run(sys.argv[1], " ".join(sys.argv[2:]) if len(sys.argv) > 2 else None))


if __name__ == "__main__":
    main()
