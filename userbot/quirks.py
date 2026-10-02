"""Small human touches: quoting the message you're answering, and the occasional typo that gets fixed."""
import itertools
import random
import re

from . import config as C

FORMAL_RE = re.compile(r"здравствуйте|уважаем|до\s+свидания|\bвы\b|\bвас\b|\bвам\b|\bваш\w*"
                       r"|\b(зайдите|подойдите|передайте|принесите|сдайте|напишите|ответьте|сообщите|позвоните|придите|извините)\b"
                       r"|assalomu\s+alaykum|ассалому\s+ала?йкум|\bsiz\b|\bsizga\b|\bsizni\b", re.I)
THEY_GREET_RE = re.compile(r"\b(привет\w*|здравств\w*|здаров\w*|добр(ое|ый)\s+(утро|день|вечер)|ку|хай|салам\w*|салом\w*|"
                           r"ассалом\w*|hi|hey|hello|yo|sup|salom|assalomu)\b", re.I)
# greeting word (any case), optionally followed by a Capitalized name / name + patronymic
LEADING_GREETING_RE = re.compile(r"^\s*((?i:здравствуйте|привет(?:ик)?|салом|salom|hi|hey|hello|yo|доброе утро|добрый (?:день|вечер)))"
                                 r"(\s+[А-ЯЁA-Z][а-яёa-z]+(\s+[А-ЯЁA-Z][а-яёa-z]+)?)?[\s,!.]+")


def fix_greeting(reply: str, their_text: str, formal: bool) -> str:
    """No greeting unless they greeted; never "Здравствуйте" to someone who writes casually."""
    salam_start = re.match(r"^\s*(в?а\s+)?(ас+ал[ао]м\w*|assalom\w*|salom)\s+(ал[ае]йкум|alaykum)?[\s,!.]*", reply, re.I)
    if salam_start and salam_start.group(0).strip() and not re.search(r"ас+ал[ао]м|assalom|salom|салом|салам", their_text, re.I):
        rest = reply[salam_start.end():].strip()
        if rest:
            return rest[0].upper() + rest[1:]
    match = LEADING_GREETING_RE.match(reply) or LEADING_GREETING_RE.match(reply.strip() + " ")
    if not match:
        return reply
    rest = reply[match.end():].strip()
    greeted = bool(THEY_GREET_RE.search(their_text))
    if not greeted and not formal and rest:
        return rest[0].upper() + rest[1:]
    if not greeted and not formal and their_text.strip() and not match.group(1).lower().startswith("yo"):
        return "?"  # "ой раскладка" — "Привет" answers nothing
    if not formal and match.group(1).lower().startswith("здравствуйте"):
        return ("Привет, " + rest) if greeted and rest else (rest[0].upper() + rest[1:] if rest else "Привет")
    return reply
WORD_RE = re.compile(r"[^\W\d_]{5,}")


ASKING_RE = re.compile(r"\?|^\W*(кто|что|чё|че|чо|где|куда|когда|почему|зачем|как|какой|какая|какие|сколько|"
                       r"who'?s|what'?s|who|what|where|when|why|how|which|and\s+(who|what|where|when|how)|а\s+(кто|что|где|когда|как|сколько)|kim|nima|qayer\w*|qachon|nega|qanday|necha|qancha)\b", re.I)


def questions_in(history, limit: int = 3, after_id: int = 0, skip=None) -> list:
    """Their unanswered messages that each ask something, oldest first — only when there are at least two
    different ones. Then every question gets its own answer, sent as a reply to that message."""
    asked, seen = [], set()
    for msg in reversed(list(itertools.takewhile(lambda m: not m.out and getattr(m, "id", 0) > after_id, history))):
        text = (msg.raw_text or "").strip()
        if skip and skip(text):
            continue  # e.g. a "who is answering?" that is being ignored
        key = re.sub(r"[\W_]+", " ", text.lower()).strip()
        if not key or key in seen or not ASKING_RE.search(text):
            continue
        seen.add(key)
        asked.append(msg)
    return asked[-limit:] if len(asked) >= 2 else []


MULTI_HINT = ("\nThey sent {n} separate questions:\n{listing}\nAnswer every one of them: exactly {n} lines, one short "
              "answer per line, in the same order, nothing else. Each line is sent as a reply to its question, so "
              "don't repeat the question and don't number the lines.\n")


def reply_target(history):
    """Which of their messages to quote (swipe-reply), or None for a plain message.

    Quote when they sent several things and the question isn't the last one, or when the message is old."""
    unanswered = list(itertools.takewhile(lambda m: not m.out, history))  # newest first
    if not unanswered:
        return None
    questions = [m for m in unanswered if "?" in (m.raw_text or "")]
    if len(unanswered) >= 2 and questions:
        return questions[0]  # several messages, one of them a question: answer that one, as a reply to it
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
    if not C.TYPOS_ON or len(text) < 12 or "http" in text or random.random() >= C.TYPO_CHANCE:
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


SPLIT_AT = re.compile(r"(?<=[.!?…])\s+|,\s+(?=(?:а|но|и|потом|кстати|короче|просто|так что|though|but|and|so|btw|lekin|keyin)\b)|\s+(?=(?:а ты|а у тебя|кстати|короче)\b)", re.I)


def split_two(part: str) -> list[str]:
    """One message -> the two you would have sent: people hit send at the end of a thought, not of a paragraph.
    Splits at a sentence end or before "а / но / кстати…", only when both halves can stand alone."""
    if len(part) < 18 or len(part.split()) < 4:
        return [part]
    best = None
    for match in SPLIT_AT.finditer(part):
        left, right = part[:match.start()].rstrip(" ,"), part[match.end():].strip()
        if len(left.split()) < 1 or len(right.split()) < 2 or len(left) < 3:
            continue
        balance = abs(len(left) - len(right))
        if best is None or balance < best[0]:
            best = (balance, left, right)
    if not best:  # no clear break: a plain comma will do ("круто, скинь скрин") — but a list stays in one piece
        for match in re.finditer(r",\s+", part) if part.count(",") == 1 else ():
            left, right = part[:match.start()].strip(), part[match.end():].strip()
            if len(left) >= 3 and len(right.split()) >= 2:
                return [left, right]
        return [part]
    left, right = best[1], best[2]
    return [left.rstrip("."), right[:1].upper() + right[1:] if left[-1:] in ".!?…" or part[0].isupper() else right]
