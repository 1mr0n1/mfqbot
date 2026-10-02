"""Every dashboard action against the live userbot, with the result checked in what the bot reports back.
Only your own other account's chat receives messages; nothing is posted to other people or groups."""
import json, time, sys, urllib.request
B = "http://127.0.0.1:8000"
def get(p): return json.load(urllib.request.urlopen(B + p, timeout=10))
def post(p, body=None):
    r = urllib.request.Request(B + p, data=json.dumps(body or {}).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=10))
def cmd(**k): post("/admin/commands", k)
def status(): return get("/admin/status")
def wait(pred, secs=12):
    end = time.time() + secs
    while time.time() < end:
        s = status()
        if pred(s): return s
        time.sleep(0.7)
    return None
res = []
def ok(name, cond, detail=""): res.append((bool(cond), name, detail)); print(("ok    " if cond else "FAIL  ") + name + ("" if cond else f"   [{detail}]"), flush=True)
def events_after(i): return get(f"/admin/events?after={i}")["events"]
def last_id(): ev = get("/admin/events?after=0")["events"]; return ev[-1]["id"] if ev else 0

s0 = status(); ME = sys.argv[1]
ok("userbot is reporting", s0.get("age") is not None and s0["age"] < 15, s0.get("age"))
# pause / resume
cmd(type="pause"); ok("Pause pauses the bot", wait(lambda s: s["paused"]))
cmd(type="resume"); ok("Resume un-pauses it", wait(lambda s: not s["paused"]))
# approve
cmd(type="approve", value="on"); ok("Approve-before-sending turns on", wait(lambda s: s["approve"]))
cmd(type="approve", value="off"); ok("…and off", wait(lambda s: not s["approve"]))
# every switch: flip, check, flip back
for t in s0["toggles"]:
    key, was = t["key"], t["on"]
    cmd(type="toggle", value=key, text="off" if was else "on")
    flipped = wait(lambda s: next(x["on"] for x in s["toggles"] if x["key"] == key) != was)
    cmd(type="toggle", value=key, text="on" if was else "off")
    back = wait(lambda s: next(x["on"] for x in s["toggles"] if x["key"] == key) == was)
    ok(f"switch '{t['label']}' flips and flips back", flipped and back)
# chat mode
mode = lambda s: next((c["mode"] for c in s["chats"] if c["name"] == ME), None)
ok("your other account's chat is listed", mode(s0) is not None, [c["name"] for c in s0["chats"]][:6])
for m in ("manual", "off", "auto"):
    cmd(type="mode", chat=ME, value=m); ok(f"chat mode → {m}", wait(lambda s: mode(s) == m))
# groups
if s0.get("groups"):
    g = s0["groups"][0]; gon = lambda s: next(x["on"] for x in s["groups"] if x["id"] == g["id"])
    cmd(type="group", chat=str(g["id"]), value="off"); ok("group switch → ignored", wait(lambda s: not gon(s)))
    cmd(type="group", chat=str(g["id"]), value="on"); ok("group switch → back on", wait(lambda s: gon(s)))
# people
if s0.get("people"):
    p = next((x for x in s0["people"] if x["telegram"] == ME or x["name"] == ME), s0["people"][0]); was = p["closeness"]
    lvl = lambda s: next(x["closeness"] for x in s["people"] if x["id"] == p["id"])
    new = "close" if was != "close" else "known"
    cmd(type="person", chat=str(p["id"]), value=new); ok(f"closeness → {new}", wait(lambda s: lvl(s) == new, 20))
    cmd(type="person", chat=str(p["id"]), value=was); ok(f"closeness → back to {was}", wait(lambda s: lvl(s) == was, 20))
# an order (read-only)
i = last_id(); cmd(type="do", text="сколько у меня непрочитанных личных чатов? только посчитай")
end = time.time() + 60; done = None
while time.time() < end and not done:
    done = next((e for e in events_after(i) if e["chat"] == "Pilot" and e["kind"] == "system"), None); time.sleep(1)
ok("order box: a read-only order is carried out and reported", done, "no Pilot result")
# unknown chat
i = last_id(); cmd(type="say", chat="No Such Chat 123", text="x"); time.sleep(3)
ok("an action for an unknown chat is refused with a warning", any("don't know that chat" in e["text"] for e in events_after(i)))
# say → your other account
i = last_id(); text = "проверка панели: это сообщение отправлено кнопкой Send"
cmd(type="say", chat=ME, text=text); end = time.time() + 30; sent = None
while time.time() < end and not sent:
    sent = next((e for e in events_after(i) if e["kind"] == "sent" and e["chat"] == ME and e["text"] == text), None); time.sleep(1)
ok("Send: your own text goes out word for word", sent)
# Answer now + approve: the draft waits, is edited, and the edited text is what is sent
cmd(type="approve", value="on"); wait(lambda s: s["approve"])
def draft_after(i, secs=60):
    end = time.time() + secs
    while time.time() < end:
        d = next((e for e in events_after(i) if e["kind"] == "draft" and e["chat"] == ME), None)
        if d: return d
        time.sleep(1)
i = last_id(); cmd(type="answer", chat=ME); d = draft_after(i)
ok("Answer now writes a draft and holds it (approve on)", d and d["data"].get("approve"), d and d["text"])
if d:
    did = d["data"]["draft_id"]; time.sleep(4)
    ok("the held draft was not sent on its own", not any(e["kind"] == "sent" and e["chat"] == ME and e["id"] > d["id"] for e in events_after(i)))
    edited = "проверка панели: это отредактированный черновик"
    post(f"/admin/drafts/{did}/edit", {"parts": [edited], "editing": True}); post(f"/admin/drafts/{did}/send", {"parts": [edited]})
    end = time.time() + 30; got = None
    while time.time() < end and not got:
        got = next((e for e in events_after(i) if e["kind"] == "sent" and e["chat"] == ME and e["text"] == edited), None); time.sleep(1)
    ok("Send now sends the edited text, not the model's", got)
i = last_id(); cmd(type="answer", chat=ME); d = draft_after(i)
if d:
    post(f"/admin/drafts/{d['data']['draft_id']}/cancel"); time.sleep(6); ev = events_after(i)
    ok("Cancel stops the draft", any(e["kind"] == "cancelled" and e["chat"] == ME for e in ev), [e["kind"] for e in ev][-6:])
    ok("…and nothing is sent after Cancel", not any(e["kind"] == "sent" and e["chat"] == ME and e["id"] > d["id"] for e in ev))
else: ok("second Answer now produced a draft", False, "no draft (nothing new to answer?)")
cmd(type="approve", value="off"); ok("approve switched back off", wait(lambda s: not s["approve"]))
s1 = status()
ok("everything is back as it was", [(t["key"], t["on"]) for t in s1["toggles"]] == [(t["key"], t["on"]) for t in s0["toggles"]] and s1["paused"] == s0["paused"] and mode(s1) == mode(s0))
bad = [r for r in res if not r[0]]; print(f"\n{len(res) - len(bad)} of {len(res)} checks passed")
