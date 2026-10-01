"""What the account did today, and the evening summary of it for you.

Every reply, reaction, skip, hand-off and note is appended to userbot/daylog.json (git-ignored, kept 3 days).
At SUMMARY_TIME a digest is posted to Saved Messages; `.ai summary` posts it on demand.
"""
import json
import time
from collections import defaultdict
from datetime import datetime

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
