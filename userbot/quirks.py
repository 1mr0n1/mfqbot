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
