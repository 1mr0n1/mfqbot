"""Learn your texting style from Telegram Desktop chat exports (HTML) instead of a live account.

  .venv/bin/python -m userbot.import_export "chat-histories" ImrOnO

Scans every messages*.html under the folder, keeps only messages written by the given author name
(forwarded messages skipped), and builds the same style files as learn_style.py. Other people's
messages are only used locally, to measure how you split replies into bursts.
"""
import asyncio
import html
import re
import sys
from collections import Counter
from pathlib import Path

from .learn_style import URL_RE, build_style, compute_stats, usable

BLOCK_RE = re.compile(r'<div class="message (default clearfix(?: joined)?|service)" id="message\d+">')
FROM_RE = re.compile(r'<div class="from_name">\s*(.*?)\s*</div>', re.S)
TEXT_RE = re.compile(r'<div class="text">\s*(.*?)\s*</div>', re.S)
MEDIA_RE = re.compile(r'class="media clearfix pull_left media_(\w+)"')
TAG_RE = re.compile(r"<[^>]+>")


def parse_export(path: Path) -> list[dict]:
    """-> [{author, text, media}] in chat order. 'joined' blocks continue the previous author."""
    raw = path.read_text(encoding="utf-8")
    starts = list(BLOCK_RE.finditer(raw))
    messages, author = [], None
    for i, m in enumerate(starts):
        block = raw[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(raw)]
        if m.group(1) == "service":
            continue
        if "joined" not in m.group(1):
            name = FROM_RE.search(block)
            author = html.unescape(TAG_RE.sub("", name.group(1))).strip() if name else author
        if 'class="forwarded_from' in block:
            continue
        text = TEXT_RE.search(block)
        text = html.unescape(TAG_RE.sub("", text.group(1).replace("<br>", "\n"))).strip() if text else ""
        media = MEDIA_RE.search(block)
        messages.append({"author": author, "text": text, "media": media.group(1) if media else None})
    return messages


def burst_stats(dialogs: list[list[dict]], me: str) -> dict:
    """How many messages in a row you send before the other person answers."""
    bursts = []
    for dialog in dialogs:
        run = 0
        for msg in dialog:
            if msg["author"] == me:
                run += 1
            elif run:
                bursts.append(run)
                run = 0
        if run:
            bursts.append(run)
    counts = Counter(min(b, 4) for b in bursts)
    return {"messages_per_turn_pct": {("4+" if k == 4 else str(k)): round(100 * v / len(bursts))
                                      for k, v in sorted(counts.items())}}


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    folder, me = Path(sys.argv[1]), sys.argv[2]
    files = sorted(folder.rglob("messages*.html"))
    if not files:
        raise SystemExit(f"No messages*.html found under {folder}")

    texts, per_chat, media, dialogs = [], Counter(), Counter(), []
    for f in files:
        dialog = parse_export(f)
        dialogs.append(dialog)
        authors = Counter(m["author"] for m in dialog)
        mine = [m for m in dialog if m["author"] == me]
        print(f"  {f.parent.name}/{f.name}: {len(dialog)} messages, authors {dict(authors)}")
        for m in mine:
            text = URL_RE.sub("", m["text"]).strip()
            if usable(text):
                texts.append(text)
                per_chat[f.parent.name] += 1
            if m["media"]:
                media[m["media"]] += 1

    if not texts:
        raise SystemExit(f"No messages by author {me!r}. Check the exact name shown in the export.")
    stats = compute_stats(texts, per_chat) | burst_stats(dialogs, me) | {"media_sent": dict(media)}
    asyncio.run(build_style(texts, stats))


if __name__ == "__main__":
    main()
