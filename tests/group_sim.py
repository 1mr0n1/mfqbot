"""Group mentions through the real group reply flow on a fake client (real model, nothing sent)."""
import asyncio, json, sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS
from userbot import simulate as SIM
from userbot import app, wording, drafting, replies, groups, commands, trace, config as C
class _U:
    def __getattr__(self, k):
        for m in (app, wording, drafting, replies, groups, commands):
            if hasattr(m, k): return getattr(m, k)
        raise AttributeError(k)
    def __setattr__(self, k, v):
        for m in (app, wording, drafting, replies, groups, commands):
            if hasattr(m, k): setattr(m, k, v); return
        setattr(app, k, v)
U = _U()
from telethon.tl.types import User
C.NAME_WORDS = ["kamrono", "камроно"]
out = []
async def main():
    fake = SIM.FakeClient(); U.client = fake
    U.me = User(id=1, first_name="Kamron", last_name="Valiev", username="me_x"); U._name_re = None
    events = []
    trace.emit = lambda kind, chat="", text="", **d: events.append((kind, text))
    async def nc(d): return False
    async def ds(d): return {}
    trace.draft_cancelled = nc; trace.draft_state = ds
    cases = json.load(open(sys.argv[1]))
    for i, c in enumerate(cases):
        chat_id = -1000 - i
        people = {}
        hist = []
        for who, text in c["chat"]:
            people.setdefault(who, User(id=50 + len(people), first_name=who))
            hist.insert(0, SIM.make(text, out=(who == "You"), sender=people[who], date=datetime.now(timezone.utc)))
        fake.histories[chat_id] = hist
        msg = hist[0]; msg.chat_id = chat_id; msg.mentioned = c.get("mentioned", False)
        async def get_chat(): return NS(title=c.get("group", "9 класс"))
        msg.get_chat = get_chat
        events.clear(); before = len(fake.sent.get(chat_id, []))
        called = U.addressed_to_me(msg)
        if called: await U.group_reply_flow(msg, msg.sender)
        sent = fake.sent.get(chat_id, [])[before:]
        why = [t for k, t in events if k == "warning"]
        print(f"{'CALLED ' if called else 'ignored'} | {c['chat'][-1][0]}: {c['chat'][-1][1][:70]}\n          → {' / '.join(sent) or '(no reply)'}" + (f"   ⟨{why[0][:90]}⟩" if why else ""), flush=True)
        out.append({"case": c, "called": called, "sent": sent, "why": why}); json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
        await asyncio.sleep(3)
asyncio.run(main())
