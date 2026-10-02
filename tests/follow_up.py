"""After "щас" the account has to come back with something (real model, fake Telegram).

  PYTHONPATH=. .venv/bin/python tests/follow_up.py        (the backend must be running)
"""
import asyncio

from telethon.tl.types import User

from userbot import simulate as SIM
from userbot import app, config as C, replies, trace

CASES = [  # (what they wrote, what the account said, what the follow-up must look like)
    ("кто изобрел телефон?", "ща гляну", "an answer (Bell)"),
    ("скинь дз по алгебре", "ок щас", "an honest 'can't' — it has no homework to send"),
    ("ты где?", "не знаю, ща гляну", "an honest 'don't know' — not a made-up place"),
    ("what's the capital of Canada?", "lemme check", "an answer (Ottawa)"),
]


async def main():
    fake = SIM.FakeClient(); app.client = fake
    app.me = User(id=1, first_name="Kamron")
    trace.emit = lambda *a, **k: None
    C.FOLLOW_UP = (0, 0)
    C.LOOKUP_ON = True
    for n, (them, said, want) in enumerate(CASES):
        chat_id = 700 + n
        mine = SIM.make(said, out=True)
        fake.histories[chat_id] = [mine, SIM.make(them), SIM.make("привет", out=True)]
        await replies.come_back(chat_id, User(id=chat_id, first_name="Timur", contact=True), "Timur", mine.id, them, said)
        got = fake.sent.get(chat_id, [])
        again = bool(got) and bool(replies.DEFER_RE.search(got[-1]))
        print(("ok    " if got and not again else "FAIL  ") + f"{them}  /  “{said}”  →  {got[-1] if got else '(silence)'}     [{want}]", flush=True)
    await app.http.aclose()

asyncio.run(main())
