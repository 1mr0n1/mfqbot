"""Score a simulation run (see simulate.py) so changes can be compared by numbers.

  .venv/bin/python -m userbot.simscore run.json [older_run.json ...]

Checks every bot message for the things that give a bot away: wrong language, textbook punctuation, emoji,
greetings nobody asked for, echoing, assistant phrases, agreeing to plans, yes/no claims about the owner's day,
over-long messages, the same stock phrase everywhere. For scenarios with a real reference reply (built from
chat exports) it also measures how close the bot's reply is to what the owner actually wrote.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

from . import judge, lang, quirks

EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿]")
DODGE_RE = re.compile(r"^\W*(хз|не знаю|idk|bilmasam|bilmadim|потом скажу|гляну и напишу|не помню|посмотрим)\W*$", re.I)
BOTLIKE_RE = re.compile(r"чем могу помочь|как я могу|обращай|i'?m here to|как ии|as an ai|не буду отвечать|не могу ответить на"
                        r"|yordam bera|к сожалению, я|я всего лишь", re.I)


def trigrams(text: str) -> Counter:
    t = re.sub(r"[\W_]+", " ", text.lower()).strip()
    return Counter(t[i:i + 3] for i in range(max(len(t) - 2, 1)))


def similarity(a: str, b: str) -> float:
    x, y = trigrams(a), trigrams(b)
    common = sum((x & y).values())
    return 2 * common / max(sum(x.values()) + sum(y.values()), 1)


def flags(them: str, bot: list[str], formal_expected: bool) -> list[str]:
    texts = [b.lstrip("↩ ").strip() for b in bot if not b.startswith("[")]
    said = " ".join(texts)
    out = []
    if not said:
        return out
    their_lang, bot_lang = lang.base(lang.detect(them)), lang.base(lang.detect(said))
    if their_lang in ("ru", "en", "uz") and bot_lang in ("ru", "en", "uz") and their_lang != bot_lang \
            and len(them.split()) >= 2 and len(said.split()) >= 2:
        out.append("wrong-language")
    if any(t.endswith(".") and not t.endswith("..") for t in texts):
        out.append("final-period")
    if EMOJI_RE.search(said):
        out.append("emoji")
    if any(len(t) > 70 for t in texts) and not quirks.EXPLAIN_RE.search(them):
        out.append("too-long")
    if quirks.LEADING_GREETING_RE.match(said + " ") and not quirks.THEY_GREET_RE.search(them):
        out.append("unasked-greeting")
    if re.search(r"здравствуйте", said, re.I) and not formal_expected:
        out.append("formal-to-friend")
    if judge._norm(said) == judge._norm(them.splitlines()[-1]) and not judge.GREETING_RE.match(them.strip()) \
            and len(judge._norm(said).split()) >= 2:
        out.append("echo")
    if BOTLIKE_RE.search(said):
        out.append("assistant-speak")
    over = judge.overreach(them, said)
    if over:
        out.append(over)
    if judge.unknown_words(them, said) or judge.foreign_word(them, said):
        out.append("odd-word")
    if DODGE_RE.match(said):
        out.append("dodge")
    return out


def score(path: Path) -> dict:
    results = json.loads(path.read_text())
    turns = [(r, t) for r in results for t in r["turns"]]
    counts, replies, sims, len_ratio = Counter(), Counter(), [], []
    silent_expected = {"sensitive", "identity"}
    answered = handed = wrong_silence = 0
    for r, t in turns:
        them = "\n".join(t["them"])
        texts = [b for b in t["bot"] if not b.startswith("[")]
        if t["bot"]:
            answered += 1
        elif t.get("notes"):
            handed += 1
        elif r["tag"] not in silent_expected:
            wrong_silence += 1
        for f in flags(them, t["bot"], r["tag"] in ("formal",)):
            counts[f] += 1
        for b in texts:
            replies[judge._norm(b.lstrip("↩ "))] += 1
        ref = t.get("reference")
        if ref and texts:
            sims.append(similarity(" ".join(texts), ref))
            len_ratio.append(len(" ".join(texts)) / max(len(ref), 1))
    n = max(len(turns), 1)
    top = replies.most_common(1)[0] if replies else ("", 0)
    return {"turns": len(turns), "answered": answered, "handed_to_owner": handed, "unexplained_silence": wrong_silence,
            "flags": dict(counts.most_common()), "flagged_share": round(sum(counts.values()) / n, 3),
            "most_repeated_reply": f"{top[0]!r} x{top[1]}",
            "similarity_to_real": round(sum(sims) / len(sims), 3) if sims else None,
            "length_vs_real": round(sorted(len_ratio)[len(len_ratio) // 2], 2) if len_ratio else None,
            "compared_with_real": len(sims)}


def main():
    rows = [(Path(p).stem, score(Path(p))) for p in sys.argv[1:]]
    keys = ["turns", "answered", "handed_to_owner", "unexplained_silence", "flagged_share", "similarity_to_real",
            "length_vs_real", "most_repeated_reply"]
    all_flags = sorted({f for _, s in rows for f in s["flags"]})
    width = max(len(name) for name, _ in rows) + 2
    print(" " * 24 + "".join(f"{name:>{max(width, 14)}}" for name, _ in rows))
    for k in keys:
        print(f"{k:24}" + "".join(f"{str(s[k]):>{max(width, 14)}}" for _, s in rows))
    for f in all_flags:
        print(f"  {f:22}" + "".join(f"{s['flags'].get(f, 0):>{max(width, 14)}}" for _, s in rows))


if __name__ == "__main__":
    main()
