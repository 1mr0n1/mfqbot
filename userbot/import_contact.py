"""Learn how you talk to ONE specific person from a Telegram Desktop export of your chat with them.

  .venv/bin/python -m userbot.import_contact "chat-histories/ChatExport_X" "YourName" their_username

Runs entirely on this machine (no model call). Writes userbot/style/contacts/<username>.json with your
messages to them, real "they wrote → you answered" exchanges, and a few statistics. When the userbot
talks to that username it uses ONLY this file as its style, not the general profile.
Messages with links, long numbers (phones, cards, codes) or slurs are left out.
"""
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

from . import config as C
from . import lang
from .import_export import burst_stats, exchange_pairs, parse_export
from .learn_style import URL_RE, compute_stats, usable

MAX_EXAMPLES, MAX_PAIRS = 800, 2000
PRIVATE_RE = re.compile(r"\d[\d\s\-()]{5,}\d|\d{5,}")  # phone numbers, card numbers, codes


def keep(text: str) -> bool:
    return bool(text) and usable(text) and not URL_RE.search(text) and not PRIVATE_RE.search(text) and len(text) <= 250


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    folder, me, username = Path(sys.argv[1]), sys.argv[2], sys.argv[3].lstrip("@").lower()
    files = sorted(folder.glob("messages*.html"), key=lambda p: (len(p.name), p.name))
    if not files:
        raise SystemExit(f"No messages*.html in {folder}")
    dialog = [m for f in files for m in parse_export(f)]
    authors = Counter(m["author"] for m in dialog)
    if me not in authors:
        raise SystemExit(f"No messages by {me!r}; authors in this export: {dict(authors)}")
    other = next(a for a, _ in authors.most_common() if a != me)

    mine = [m["text"] for m in dialog if m["author"] == me and keep(m["text"])]
    pairs = [p for p in exchange_pairs(dialog, me) if keep(p["them"]) and keep(p["me"])]
    for p in pairs:
        p.pop("with", None)
        p["lang"] = lang.base(lang.detect(p["me"]))
        p["them_lang"] = lang.base(lang.detect(p["them"]))
    by_lang = Counter(lang.base(lang.detect(t)) or "other" for t in mine)
    stats = compute_stats(mine, Counter({other: len(mine)})) | burst_stats([dialog], me)
    stats["languages_pct"] = {k: round(100 * v / len(mine)) for k, v in by_lang.most_common()}

    random.shuffle(pairs)
    examples = random.sample(list(set(mine)), min(MAX_EXAMPLES, len(set(mine))))
    out = C.STYLE_DIR / "contacts" / f"{username}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"name": other, "stats": stats, "examples": examples, "pairs": pairs[:MAX_PAIRS]},
                              ensure_ascii=False, indent=1))
    print(f"@{username} ({other}): {len(dialog)} messages read, kept {len(examples)} of your messages and "
          f"{min(len(pairs), MAX_PAIRS)} exchanges.\nYour languages with them: {stats['languages_pct']}\nSaved {out}")


if __name__ == "__main__":
    main()
