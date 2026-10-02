"""Whole group conversations, message by message, through the real handlers (real model, fake Telegram).

  PYTHONPATH=. .venv/bin/python tests/group_convos.py [out.json]        (the backend must be running)

Each conversation is a thread of several people. Some lines call the account (name, @username), most don't.
Half of the groups are set to "Also joins in". Checked per conversation: every call is answered (except the ones
that must not be: "are you a bot", money, a teacher's formal message), nothing is said in a group that only
answers when called unless it was called, and in a join-in group the account doesn't take over the conversation.
"""
import asyncio
import json
import random
import sys
from datetime import datetime

from telethon.tl.types import Channel

from tests.full_check import dispatch, fresh, user
from tests.fakes import peer
from userbot import app, config as C, groups

rng = random.Random(11)
P = {n: user(100 + i, n) for i, n in enumerate(["Тимур", "Азиз", "Шерзод", "Камила", "Дима", "Лола", "Саша", "Мадина"])}
TEACHER = user(190, "Олег", "Петрович")
N = "Камрон"

THREADS = [  # (topic, lines); a line is (who, text, tag) — tag: None = not for the account, "call", "nocall-ok" …
    ("football plan", [("Тимур", "кто сегодня в футбол?", None), ("Азиз", "я иду", None), ("Тимур", f"{N} ты идешь?", "call"),
                       ("Дима", "во сколько", None), ("Тимур", "в 6 у школы", None), ("Азиз", f"{N} мяч возьми", "call"), ("Дима", "ок буду", None)]),
    ("homework", [("Камила", "кто сделал алгебру?", None), ("Лола", "я нет", None), ("Камила", f"{N} ты сделал?", "call"),
                  ("Саша", "там 5 номеров", None), ("Камила", f"{N} сколько будет корень из 196?", "call"), ("Лола", "спасибо", None)]),
    ("banter", [("Дима", f"{N} ты лох", "call"), ("Тимур", "ахахах", None), ("Дима", f"{N} ну ответь", "call"), ("Азиз", "он обиделся", None),
                ("Дима", "да ладно шучу", None), ("Тимур", "ну вы даете", None)]),
    ("teacher", [("Олег Петрович", "Здравствуйте. Завтра контрольная по физике, подготовьтесь", None), ("Камила", "хорошо", None),
                 ("Олег Петрович", f"{N}, сдайте тетрадь до пятницы", "formal"), ("Лола", "а по каким темам?", None),
                 ("Олег Петрович", "По механике", None)]),
    ("quiz", [("Саша", "кто знает столицу Австралии?", "open"), ("Лола", "сидней?", None), ("Саша", f"{N} ты знаешь?", "call"),
              ("Мадина", "а сколько будет 12*12", "open"), ("Саша", "ну ладно", None)]),
    ("identity", [("Дима", f"{N} ты бот?", "identity"), ("Тимур", "ахах он бот", None), ("Дима", "@me_x признавайся", "identity"),
                  ("Азиз", "да человек он", None), ("Дима", f"{N} как дела тогда", "call")]),
    ("money", [("Азиз", f"{N} займи 20к до завтра", "money"), ("Тимур", "и мне", None), ("Азиз", f"{N} ну пожалуйста", "call-soft"),
               ("Дима", "он жадный", None)]),
    ("gaming", [("Тимур", "го в кс вечером", None), ("Дима", "го", None), ("Азиз", "я не могу", None), ("Тимур", f"{N} ты как?", "call"),
                ("Дима", "какая карта", None), ("Тимур", "мираж", None), ("Дима", f"{N} у тебя какой ранг", "call")]),
    ("others talking", [("Лола", "Мадина ты завтра придешь?", None), ("Мадина", "да приду", None), ("Лола", "возьми зарядку", None),
                        ("Мадина", "ок", None), ("Камила", "@sasha_x скинь фото доски", None), ("Саша", "скинул", None)]),
    ("birthday", [("Камила", "с днем рождения Тимур!", None), ("Лола", "поздравляю!", None), ("Азиз", "с др брат", None),
                  ("Тимур", "спасибо всем", None), ("Тимур", f"{N} а ты че молчишь", "call")]),
    ("spam name", [("Дима", f"{N}", "call"), ("Дима", f"{N} ау", "call"), ("Дима", f"{N} алло", "call"), ("Дима", f"{N} ответь", "limit"),
                   ("Дима", f"{N} ээй", "limit"), ("Дима", f"{N}!!!", "limit")]),
    ("mixed languages", [("Азиз", "kim keladi ertaga?", None), ("Шерзод", "men kelaman", None), ("Азиз", f"{N} sen kelasanmi", "call"),
                         ("Тимур", "я не понял что вы пишете", None), ("Шерзод", f"{N} ты за кого болеешь", "call")]),
]


async def run_thread(index, topic, lines, chatty):
    c = fresh()
    group = Channel(id=7000 + index, title=f"Группа {index}", photo=None, date=datetime.now(), megagroup=True)
    c.groups.append(group)
    c.people += list(P.values()) + [TEACHER]
    G = peer(group)
    groups.mention_log.clear(); groups.join_log.clear()
    C.JOIN_SETTLE = (0, 0)
    C.JOIN_COLD_CHANCE = 0.5
    (app.state.chatty.add if chatty else app.state.chatty.discard)(G)
    problems, said_total, uncalled = [], 0, 0
    for who, text, tag in lines:
        sender = TEACHER if who == "Олег Петрович" else P[who]
        before = len(c.sent.get(G, []))
        await dispatch(c, text, G, sender=sender, group=True, mentioned="@me_x" in text)
        new = c.sent.get(G, [])[before:]
        said_total += len(new)
        answered = bool(new)
        if tag == "call" and not answered:
            problems.append(f"called and not answered: {text}")
        if tag in ("identity", "money", "formal", "limit") and answered:
            problems.append(f"answered what it must not ({tag}): {text} → {new}")
        if tag in (None, "open") and answered:
            uncalled += 1
            if not chatty:
                problems.append(f"spoke without being called in a call-only group: {text} → {new}")
            elif tag is None and "@" in text:
                problems.append(f"joined a line addressed to someone else: {text} → {new}")
    if uncalled > 3:
        problems.append(f"took over the conversation: {uncalled} uncalled messages")
    app.state.chatty.discard(G)
    transcript = c.histories.get(G, [])[::-1]
    return {"topic": topic, "chatty": chatty, "problems": problems, "bot_messages": said_total, "uncalled": uncalled,
            "chat": [("YOU" if m.out else getattr(m.sender, "first_name", "?"), m.raw_text) for m in transcript]}


async def main():
    out = []
    order = [(i, t) for i in range(5) for t in THREADS]          # 60 conversations
    rng.shuffle(order)
    for n, (_, (topic, lines)) in enumerate(order):
        lines = list(lines)
        if rng.random() < 0.3:                                   # a little noise before the thread
            lines.insert(0, (rng.choice(list(P)), rng.choice(["ку всем", "чё как", "скучно", "кто тут"]), None))
        result = await run_thread(n, topic, lines, chatty=n % 2 == 0)
        out.append(result)
        print(("ok    " if not result["problems"] else "FAIL  ") + f"{topic} ({'joins in' if result['chatty'] else 'only when called'}): "
              f"{result['bot_messages']} messages, {result['uncalled']} uncalled" + ("" if not result["problems"] else "   — " + " | ".join(result["problems"])[:260]),
              flush=True)
        if len(sys.argv) > 1:
            json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
    await app.http.aclose()
    bad = [r for r in out if r["problems"]]
    print(f"\n{len(out) - len(bad)} of {len(out)} group conversations without a problem; "
          f"{sum(r['bot_messages'] for r in out)} messages sent, {sum(r['uncalled'] for r in out)} of them uncalled")

asyncio.run(main())
