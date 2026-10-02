"""What the account did today, and the evening summary of it for you.

Every reply, reaction, skip, hand-off and note is appended to userbot/daylog.json (git-ignored, kept 3 days).
At SUMMARY_TIME a digest is posted to Saved Messages; `.ai summary` posts it on demand.
"""
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta

from . import config as C

KEEP_SECONDS = 3 * 86400


def _load() -> list[dict]:
    return json.loads(C.DAYLOG_PATH.read_text()) if C.DAYLOG_PATH.exists() else []


def record(kind: str, who: str, text: str = "", **extra):
    """kind: replied | reacted | skipped | handoff | ignored | note | profile | failed"""
    entries = [e for e in _load() if time.time() - e["ts"] < KEEP_SECONDS]
    entries.append({"ts": time.time(), "kind": kind, "who": who, "text": text[:300], **extra})
    C.DAYLOG_PATH.write_text(json.dumps(entries, ensure_ascii=False))


def summary(since: float | None = None) -> str:
    """Digest of today's activity (or since the given time)."""
    start = since or datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    entries = [e for e in _load() if e["ts"] >= start]
    if not entries:
        return "🗒 Today: nobody wrote, nothing to report."
    people: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        people[e["who"]].append(e)
    lines = [f"🗒 Today — {len(people)} chat(s), {sum(e['kind'] == 'replied' for e in entries)} replies sent"]
    waiting = [e for e in entries if e["kind"] in ("handoff", "failed")]
    if waiting:
        lines.append("\n🚨 Waiting for YOU:")
        for e in waiting:
            what = "left to you" if e["kind"] == "handoff" else "couldn't write a good reply"
            lines.append(f"• {e['who']} — {what}: {e['text'][:120]}")
    for who, items in sorted(people.items(), key=lambda kv: -len(kv[1])):
        if not who:
            continue
        counts = defaultdict(int)
        for e in items:
            counts[e["kind"]] += 1
        parts = [f"{counts['replied']} replies"] if counts["replied"] else []
        parts += [f"{counts[k]} {label}" for k, label in (("reacted", "reactions"), ("skipped", "left without reply"),
                                                          ("ignored", "identity questions ignored")) if counts[k]]
        lines.append(f"\n👤 {who}: {', '.join(parts) or 'no replies'}")
        for e in [e for e in items if e["kind"] == "replied"][-3:]:
            lines.append(f"   {datetime.fromtimestamp(e['ts']):%H:%M} they: {e.get('them', '')[:70]}\n         you:  {e['text'][:90]}")
        for e in [e for e in items if e["kind"] == "note"]:
            lines.append(f"   🧠 noted: {e['text'][:100]}")
    other = [e for e in entries if e["kind"] == "profile"]
    if other:
        lines.append("\n✏️ Profile: " + "; ".join(e["text"][:60] for e in other))
    return "\n".join(lines)[:3900]


# ---------- the morning report ----------
# what the account decided along the way, counted from the lines it writes to the decision log
TALLY = [
    ("Second look rejected", "drafts rewritten (wrong language or a made-up word)"),
    ("Draft made a", "promises or claims about your day caught and put off"),
    ("A rewrite still made", "promises or claims about your day caught and put off"),
    ("Draft repeats", "repeated lines caught"),
    ("Draft too long", "drafts shortened"),
    ("Looked it up", "facts looked up on the web"),
    ("Writing first", "chats it opened itself"),
    ("Dry answer", "times it kept a dying chat going"),
    ("No answer to", "questions asked again after no answer"),
    ("Not in your contacts", "unknown people asked who they are"),
    ("Now known as", "people who said who they are"),
    ("Couldn't write a good reply", "messages it gave up on"),
    ("No model answered", "times no model answered"),
    ("Order from your other account", "orders from your other account"),
    ("Taught a rule", "rules you taught it"),
    ("Learned from your correction", "drafts you corrected (learned from)"),
    ("The userbot was not running", "outages"),
]


def tally(text: str):
    """Called for every decision-log line: counts the kinds of things worth reporting."""
    for prefix, label in TALLY:
        if text.startswith(prefix):
            record("tally", "", label)
            return


def report(day: datetime | None = None, cost: str = "") -> str:
    """What the account did on one day (default: yesterday) — the morning report."""
    day = day or datetime.now() - timedelta(days=1)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    entries = [e for e in _load() if start <= e["ts"] < start + 86400]
    title = f"☀️ Report for {day:%A %d.%m}"
    if not entries:
        return f"{title}\nNothing happened: nobody wrote, or the account was not running."
    kinds = defaultdict(int)
    for e in entries:
        kinds[e["kind"]] += 1
    people = defaultdict(lambda: defaultdict(int))
    for e in entries:
        if e["who"] and e["kind"] != "tally":
            people[e["who"]][e["kind"]] += 1
    lines = [title,
             f"{len(people)} chats · {kinds['replied']} replies · {kinds['reacted']} reactions · "
             f"{kinds['skipped']} left without a reply · {kinds['ignored']} \"who is answering\" ignored"]
    waiting = [e for e in entries if e["kind"] in ("handoff", "failed")]
    if waiting:
        lines.append(f"\n🚨 Left to you ({len(waiting)}):")
        lines += [f"• {e['who']}: {e['text'][:110]}" for e in waiting[-8:]]
    counted = defaultdict(int)
    for e in entries:
        if e["kind"] == "tally":
            counted[e["text"]] += 1
    if counted:
        lines.append("\n🔧 Along the way:")
        lines += [f"• {n} × {label}" for label, n in sorted(counted.items(), key=lambda kv: -kv[1])]
    busiest = sorted(people.items(), key=lambda kv: -sum(kv[1].values()))[:8]
    if busiest:
        lines.append("\n👥 Busiest chats:")
        lines += [f"• {who}: {c['replied']} replies" + (f", {c['reacted']} reactions" if c["reacted"] else "")
                  + (f", {c['handoff'] + c['failed']} left to you" if c["handoff"] + c["failed"] else "") for who, c in busiest]
    notes = [e for e in entries if e["kind"] == "note"]
    if notes:
        lines.append("\n🧠 Learned about people:")
        lines += [f"• {e['who']}: {e['text'][:90]}" for e in notes[-6:]]
    if cost:
        lines.append(f"\n💳 {cost}")
    return "\n".join(lines)[:3900]
