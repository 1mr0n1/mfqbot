"""Punctuation the way you actually type it: measured from your messages, then applied to every reply.

measure() turns a list of your messages into a few rates (how often a message ends with a period, how often a
longer message has a comma, how often a question really gets its "?", …). apply() rewrites a model reply so
its punctuation follows those rates — models punctuate like a textbook, people don't.
"""
import random
import re

QUESTION_START = re.compile(
    r"^(как|что|чё|че|шо|где|куда|когда|почему|зачем|кто|сколько|какой|какая|какие|можно|а\s|what|when|where|why|how|who|"
    r"which|can|do|does|did|is|are|will|nima|nega|qachon|qayerda|qanday|qancha|kim)\b", re.I)
DEFAULT = {"period_end": 0.03, "comma_long": 0.25, "question_mark": 0.6, "exclaim": 0.03, "upper_start": 0.9,
           "dash": 0.01, "ellipsis": 0.02}


def measure(messages: list[str]) -> dict:
    msgs = [m.strip() for m in messages if m.strip() and "\n" not in m and "http" not in m]
    if len(msgs) < 50:
        return dict(DEFAULT)
    letters = [m for m in msgs if m[0].isalpha()]
    long_ = [m for m in msgs if len(m.split()) >= 5]
    questions = [m for m in msgs if QUESTION_START.match(m) or m.endswith("?")]
    rate = lambda hits, total: round(hits / max(total, 1), 3)
    return {
        "period_end": rate(sum(m.endswith(".") and not m.endswith("..") for m in msgs), len(msgs)),
        "comma_long": rate(sum("," in m for m in long_), len(long_)),
        "question_mark": rate(sum(m.endswith("?") for m in questions), len(questions)),
        "exclaim": rate(sum("!" in m for m in msgs), len(msgs)),
        "upper_start": rate(sum(m[0].isupper() for m in letters), len(letters)),
        "dash": rate(sum("—" in m or " – " in m or " - " in m for m in msgs), len(msgs)),
        "ellipsis": rate(sum("..." in m or "…" in m for m in msgs), len(msgs)),
    }


def apply(text: str, p: dict | None = None) -> str:
    """Phone-typed punctuation: commas stay, sentences are joined with a comma, no period at the end."""
    p = p or DEFAULT
    if not text or text.startswith("["):
        return text
    out = text.strip()
    out = re.sub(r"\s*[—–]\s*", ", ", out)
    out = out.replace(";", ",").replace("«", "").replace("»", "")
    if random.random() >= p["exclaim"] * 3:          # "!" is rare
        out = re.sub(r"!+\s+([^\W\d_])", lambda m: ", " + m.group(1).lower(), out)
        out = re.sub(r"!+", "", out)
    out = re.sub(r"\?{2,}", "?", out)
    # "Нет. Сделаю позже." -> "Нет, сделаю позже"
    out = re.sub(r"(?<=[^\W\d_])\.\s+([^\W\d_])", lambda m: ", " + m.group(1).lower(), out)
    if out.endswith(".") and not out.endswith("..") and random.random() >= p["period_end"]:
        out = out[:-1]
    if random.random() >= p["ellipsis"] * 3:
        out = re.sub(r"\.{2,}|…", "", out)
    out = re.sub(r"\s+,", ",", re.sub(r",\s*,", ",", out))
    out = re.sub(r"\s{2,}", " ", out).strip(" ,")
    if out and out[0].isalpha():                     # phone keyboards capitalize the first letter; you mostly leave it
        out = (out[0].upper() if random.random() < p["upper_start"] else out[0].lower()) + out[1:]
    return out
