"""Joining in: group conversations where nobody calls the account (real model, fake Telegram).
For each case: should it be allowed to consider speaking at all, and if so, what does it decide?

  PYTHONPATH=. .venv/bin/python tests/group_join.py        (the backend must be running)
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from telethon.tl.types import User

from userbot import simulate as SIM
from userbot import app, config as C, groups, trace

CASES = [  # (name, conversation oldest→newest as (who, text[, minutes ago]), expected: "consider" or "never")
    ("a question to everyone, you are in the conversation", [("You", "я дома сижу", 2), ("Timur", "кто шарит как решать квадратные уравнения?")], "consider"),
    ("two others talking to each other", [("You", "ахах", 3), ("Timur", "Азиз ты завтра придешь?"), ("Aziz", "да приду"), ("Timur", "ок, возьми мяч")], "consider"),
    ("they talk about you", [("You", "я вчера не пришел", 4), ("Timur", "он опять проспал походу"), ("Aziz", "как всегда ахах")], "consider"),
    ("a factual question you know", [("You", "привет всем", 5), ("Aziz", "какая столица у Канады?")], "consider"),
    ("just a filler", [("You", "ну да", 2), ("Timur", "ок")], "consider"),
    ("continues your exchange", [("Timur", "ты за кого болеешь?"), ("You", "за реал", 1), ("Timur", "а почему не барса")], "consider"),
    ("a teacher writes formally", [("You", "хорошо", 3), ("Oleg Petrovich", "Здравствуйте, сдайте работы до пятницы")], "never"),
    ("addressed to someone by @name", [("You", "ок", 2), ("Timur", "@aziz_x ты где?")], "never"),
    ("you were not in the conversation and it is not a question", [("Timur", "я пошел спать"), ("Aziz", "давай")], "never"),
    ("you already spoke twice in a row", [("Timur", "кто идет?"), ("You", "я иду", 1), ("You", "в 6", 1)], "never"),
]


async def main():
    fake = SIM.FakeClient(); app.client = fake
    app.me = User(id=1, first_name="Kamron", username="me_x")
    log = []
    trace.emit = lambda kind, chat="", text="", **d: log.append((kind, text))

    async def never(d): return False
    async def nothing(d): return {}
    trace.draft_cancelled, trace.draft_state = never, nothing
    good = 0
    for n, (name, convo, expect) in enumerate(CASES):
        chat_id, people, hist = -2000 - n, {}, []
        for who, text, *ago in convo:
            people.setdefault(who, User(id=60 + len(people), first_name=who))
            hist.insert(0, SIM.make(text, out=(who == "You"), sender=people[who],
                                    date=datetime.now(timezone.utc) - timedelta(minutes=ago[0] if ago else 0)))
        last = hist[0] if not hist[0].out else None
        fake.histories[chat_id] = hist
        groups.join_log.clear()
        C.JOIN_COLD_CHANCE = 0.0
        allowed = bool(last) and groups.may_join(chat_id, last, hist[1:])
        said = []
        if allowed:
            last.chat_id = chat_id
            async def get_chat(): return NS(title="Friends")
            last.get_chat = get_chat
            before = len(fake.sent.get(chat_id, []))
            await groups.group_reply_flow(last, last.sender, joining=True)
            said = fake.sent.get(chat_id, [])[before:]
        ok = allowed == (expect == "consider")
        good += ok
        print(("ok    " if ok else "FAIL  ") + f"{name}: " + ("not even considered" if not allowed else f"considered → {' / '.join(said) or 'stayed out'}"), flush=True)
    await app.http.aclose()
    print(f"\n{good} of {len(CASES)} gate checks passed (what it then says is the model's judgment — read it)")

asyncio.run(main())
