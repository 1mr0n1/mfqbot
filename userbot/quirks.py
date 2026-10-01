"""Small human touches: quoting the message you're answering, and the occasional typo that gets fixed."""
import itertools
import random
import re

from . import config as C

FORMAL_RE = re.compile(r"здравствуйте|уважаем|\bвы\b|\bвас\b|\bвам\b|assalomu\s+alaykum|\bsiz\b|\bsizga\b|\bsizni\b", re.I)
WORD_RE = re.compile(r"[^\W\d_]{5,}")


def reply_target(history):
    """Which of their messages to quote (swipe-reply), or None for a plain message.

    Quote when they sent several things and the question isn't the last one, or when the message is old."""
    unanswered = list(itertools.takewhile(lambda m: not m.out, history))  # newest first
    if not unanswered:
        return None
    questions = [m for m in unanswered if "?" in (m.raw_text or "")]
    if len(unanswered) >= 2 and questions and questions[0] is not unanswered[0]:
        return questions[0]
    newest = unanswered[0]
    import time
    if time.time() - newest.date.timestamp() > C.QUOTE_IF_OLDER_THAN:
        return newest  # answering hours later: people quote what they're answering
    if len(unanswered) >= 3 and random.random() < 0.3:
        return newest
    return None


EXPLAIN_RE = re.compile(r"почему|зачем|объясни|расскажи|как\s+(сделать|это|работает)|что\s+такое|why|explain|how\s+(do|does|to)|what\s+is|"
                        r"nega|tushuntir|qanday\s+qil", re.I)


def length_limits(stats: dict, their_text: str) -> tuple[int, int]:
    """(max characters per message, max messages) for a reply, from how long your real messages are."""
    p90 = (stats.get("length_chars") or {}).get("p90", 30)
    per_message = max(45, int(p90 * 2))
    if EXPLAIN_RE.search(their_text):     # they asked for an explanation: a bit more room
        per_message = int(per_message * 2)
    return per_message, 2


def shorten(part: str, limit: int) -> str:
    """Cut an over-long message at the last clause boundary that fits."""
    if len(part) <= limit:
        return part
    cut = part[:limit]
    boundary = max(cut.rfind(", "), cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    cut = cut[:boundary] if boundary >= limit * 0.4 else cut[:cut.rfind(" ")] if " " in cut else cut
    return cut.rstrip(" ,.")


def is_formal(history) -> bool:
    return any(FORMAL_RE.search(m.raw_text or "") for m in itertools.takewhile(lambda m: not m.out, history))


def typo(text: str) -> tuple[str, str] | None:
    """-> (text with one typo, the correctly spelled word) or None if this message isn't a candidate."""
    if len(text) < 12 or "http" in text or random.random() >= C.TYPO_CHANCE:
        return None
    words = [m for m in WORD_RE.finditer(text)]
    if not words:
        return None
    m = random.choice(words)
    word = m.group(0)
    i = random.randrange(1, len(word) - 2)
    if random.random() < 0.6:   # swap two neighbouring letters
        if word[i] == word[i + 1]:
            return None
        wrong = word[:i] + word[i + 1] + word[i] + word[i + 2:]
    else:                       # drop a letter
        wrong = word[:i] + word[i + 1:]
    return text[:m.start()] + wrong + text[m.end():], word
