"""Learn your texting style from Telegram Desktop chat exports (HTML) instead of a live account.

  .venv/bin/python -m userbot.import_export "chat-histories" "YourName"
  .venv/bin/python -m userbot.import_export "chat-histories" "YourName" ChatExport_A,ChatExport_B   # only these

Scans every messages*.html under the folder, keeps only messages written by the given author name
(forwarded messages skipped), and builds the same style files as learn_style.py. Other people's
messages are only used locally, to measure how you split replies into bursts.
"""
import asyncio
import html
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

from . import config as C
from . import lang
from .learn_style import URL_RE, build_style, compute_stats, usable

MAX_PAIRS = 800
PRIVATE_RE = re.compile(r"\d[\d\s\-()]{5,}\d|\d{5,}")  # phone numbers, card numbers, codes

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


def exchange_pairs(dialog: list[dict], me: str) -> list[dict]:
    """Turn-level examples: what the other person wrote, and what you answered right after."""
    turns: list[tuple[str, list[str]]] = []
    for msg in dialog:
        text = URL_RE.sub("", msg["text"]).strip()
        if not text:
            continue
        if turns and turns[-1][0] == msg["author"]:
            turns[-1][1].append(text)
        else:
            turns.append((msg["author"], [text]))
    pairs = []
    for (a1, t1), (a2, t2) in zip(turns, turns[1:]):
        them, mine = "\n".join(t1[-3:]), "\n".join(t2[:3])
        if a1 != me and a2 == me and len(them) <= 250 and len(mine) <= 250 and usable(them) and usable(mine) \
                and not PRIVATE_RE.search(them + " " + mine):
            pairs.append({"with": a1, "them": them, "me": mine, "lang": lang.detect(mine)})
    return pairs


def main():
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    folder, me = Path(sys.argv[1]), sys.argv[2]
    only = set(sys.argv[3].split(",")) if len(sys.argv) == 4 else None  # e.g. just the chats with friends
    files = sorted(f for f in folder.rglob("messages*.html") if not only or f.parent.name in only)
    if not files:
        raise SystemExit(f"No messages*.html found under {folder}")

    texts, per_chat, media, dialogs, pairs = [], Counter(), Counter(), [], []
    for f in files:
        dialog = parse_export(f)
        dialogs.append(dialog)
        pairs += exchange_pairs(dialog, me)
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
    by_lang = Counter(lang.base(lang.detect(t)) for t in texts)
    print(f"  your messages by language: {dict(by_lang)} | exchanges collected: {len(pairs)}")
    stats = (compute_stats(texts, per_chat) | burst_stats(dialogs, me)
             | {"media_sent": dict(media), "messages_by_language": dict(by_lang)})
    asyncio.run(build_style(texts, stats))
    random.shuffle(pairs)
    (C.STYLE_DIR / "pairs.json").write_text(json.dumps(pairs[:MAX_PAIRS], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
