"""Rules about the text of a reply: what may never be sent, questions about who is answering, cleaning up
what a model wrote, splitting it into messages, and spotting repeats."""
import itertools
import random
import re
from . import config as C
from . import judge, lang, media, memory
from . import app
from .app import COMMAND_RE, our_ids, our_texts


# Last line of defense: never send something that looks like the model's reasoning or instructions.
LEAK_RE = re.compile(r"\b(the user|we need to|we must|the instruction|system prompt|as an ai|language model"
                     r"|impossible to infer|adhering to|rule \d|final check)\b"
                     r"|\{(name|contact|style|now)\}", re.I)


MAX_REPLY_CHARS = 700


def looks_safe(reply: str) -> bool:
    # A text that starts with ".ai" would be executed as YOUR command the moment the account sends it, so nothing
    # written by a model or copied from another person may ever look like one.
    return (len(reply) <= MAX_REPLY_CHARS and not LEAK_RE.search(reply) and not re.search(r"@[A-Za-z]\w{3,}", reply)
            and not re.search(r"\+?\d[\d\s\-()]{7,}\d", reply)  # no phone / card / code-like numbers, ever
            and not COMMAND_RE.search(reply))


def typed_by_bot(event) -> bool:
    """An outgoing message the account sent on its own (not typed by you): never a command."""
    return (event.raw_text in our_texts.get(event.chat_id, []) or event.id in our_ids
            or bool(getattr(event.message, "fwd_from", None)))  # a forwarded ".ai …" is someone else's text


# Lines that make it sound like a customer-support bot get dropped.
ASSISTANT_RE = re.compile(
    r"\b(assist|let me know if you need|anything else|how can i help|feel free|happy to help)\b"
    r"|чем\s+(я\s+)?(могу|можно)\s+помочь|обращай(ся|тесь)|если\s+что[-\s]*то\s+нужно|буду\s+ждать,?\s+когда\s+появится"
    r"|yordam\s+bera\s+ola|qanday\s+yordam|доступ\s+к\s+просмотру"
    r"|спасибо\s+за\s+(рассказ|совет|напоминание|информаци\w+|понимание|вопрос|ответ|помощь\s+в|то,?\s+что)"
    r"|thanks?\s+for\s+(sharing|letting\s+me\s+know|the\s+(info|reminder|advice|update))|рад\s+(был\s+)?помочь|"
    r"хорошего\s+(дня|вечера)|have\s+a\s+(nice|great|good)\s+(day|night|one)", re.I)


# Questions about who or what is answering ("are you a bot?", "who are you?", "is this really you?") are ignored:
# no confirmation, no denial. Lines where the model claims to be human are dropped, so ignoring never becomes lying.
BOT_QUESTION_RE = re.compile(r"\b(bot|robot|ai|a\.i\.|chat ?gpt|gpt|neural|автоответчик|бот|робот|ии|нейросеть|"
                             r"нейронка|чатгпт)\b", re.I)


ADDRESSED_RE = re.compile(r"\?|\b(u|you|ur|you'?re|youre|r u|are|is this|ты|вы|тебя|это|sen|san|siz)\b", re.I)


WHO_RE = re.compile(
    r"\bwho\s+(are|r)\s+(you|u)\b|\bis\s+(this|that|it)\s+(really\s+|actually\s+)?(you|u)\b|\bare\s+(you|u)\s+(even\s+)?(real|human|a\s+(real\s+)?person)\b"
    r"|\bты\s+кто\b|\bкто\s+ты\b|\bэто\s+(точно\s+|правда\s+|реально\s+|вообще\s+)?ты\b|\bты\s+(настоящий|реальный|человек|живой)\b"
    r"|\b(sen\s+)?kimsan\b|\b(rostdan|haqiqatan)\s+(ham\s+)?senmi\b|\bsenmisan\b|\bodammisan\b", re.I)


# "who is this?" is only about identity when it stands alone (otherwise it's about a photo, a person, a video…)
WHO_ALONE_RE = re.compile(r"^\W*(who(['’]s|\s+is)\s+this|кто\s+это|а?\s*это\s+кто|bu\s+kim)\W*$", re.I)


IDENTITY_CLAIM_RE = re.compile(
    r"\b(i['’]?m|i\s+am|im)\s+(a\s+|an\s+)?(real|human|person|not\s+a\s+bot|no\s+bot|not\s+an?\s+ai)\b|\bnot\s+a\s+bot\b"
    r"|\bя\s+(не\s+бот|настоящий|реальный|живой|человек|не\s+ии)\b|\bне\s+бот\b|\bbot\s+emasman\b|\bodamman\b"
    r"|auto-?reply|автоответ", re.I)


# refusing out loud ("I won't answer that") sounds like a bot too — such lines are dropped
REFUSAL_RE = re.compile(
    r"не\s+буду\s+(отвечать|обсуждать|говорить)|не\s+хочу\s+(отвечать|обсуждать|вступать|говорить об этом)|без\s+комментариев"
    r"|(won'?t|not\s+going\s+to|refuse\s+to|rather\s+not)\s+(answer|say|discuss|talk)|no\s+comment|javob\s+bermayman", re.I)


# words that belong to the accusation itself ("I know you're a bot, admit it") — not something else to answer
ACCUSE_RE = re.compile(
    r"\b(знаю|признай\w*|признавай\w*|честно|правд\w*|серь[её]зно|точно|докажи\w*|скажи|колись|окей|ок|ладно|ну"
    r"|know|admit|confess|honest\w*|seriously|really|prove|tell|truth|ok|okay|bilaman|tan\s+ol|rostini|ayt)\b|\bа\s+не\s+\w+|\bnot\s+\w+", re.I)


IDENTITY_HINT = ("\nPart of their message is about who or what you are (a bot, an AI, a real person, whether it's really "
                 "you). Act as if that part wasn't written: don't confirm, don't deny, don't mention it, and don't say "
                 "that you won't answer. Reply only to the rest of what they wrote.\n")


REALLY_RE = re.compile(r"\b(точно|правда|реально|really|actually|rostdan)\b|\bэто\b|\bis\s+(this|that|it)\b", re.I)


identity_ignored: dict[int, int] = {}   # chat_id -> newest message id of an identity question that was ignored


def is_identity_question(sentence: str, about_media: bool = False) -> bool:
    """about_media: a photo or video was just sent in the chat — then "who is this?" asks about the picture."""
    if (BOT_QUESTION_RE.search(sentence) and ADDRESSED_RE.search(sentence)) or WHO_RE.search(sentence) \
            or (WHO_ALONE_RE.match(sentence) and not about_media):
        return True
    # "ты точно <имя>?", "is this really <name>?" — the same question with your name in it
    return bool(app.me and "?" in sentence and REALLY_RE.search(sentence) and name_re().search(sentence))


def identity_question(history, after_id: int = 0) -> str | None:
    """-> 'only' (nothing else was said), 'mixed' (there is also something to answer) or None.
    after_id: messages up to this id were already ignored for it — they don't colour what comes later."""
    found, rest_words = False, 0
    about_media = any(getattr(m, "photo", None) or getattr(m, "video", None) or getattr(m, "gif", None) for m in history[:6])
    for msg in itertools.takewhile(lambda m: not m.out and getattr(m, "id", 0) > after_id, history):
        if getattr(msg, "photo", None) or getattr(msg, "voice", None):
            rest_words += 3  # media counts as something to answer
        for sentence in re.split(r"(?<=[.?!,;\n])\s*", msg.raw_text or ""):
            if not sentence.strip():
                continue
            if is_identity_question(sentence, about_media):
                found = True
            else:  # count only words that say something beyond the accusation itself
                rest_words += len(re.findall(r"[^\W\d_]{2,}", ACCUSE_RE.sub(" ", sentence)))
    if not found:
        return None
    return "mixed" if rest_words >= 3 else "only"


HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]{0,40}>|\*\*|__|`")  # leftover markup: <b>, </blockquote>, **bold**


EMPTY_TAG_RE = re.compile(r"\[(sticker|gif|voice|video)\s*\]", re.I)  # a media tag with nothing in it
PLACEHOLDER_RE = re.compile(r"\[(sticker|gif|voice|video)\s+[^\]]*(search words|emoji|tag|\.\.\.|…|<)[^\]]*\]", re.I)  # the instruction copied back


FAKE_TAG_RE = re.compile(r"\[(?!(?:sticker|gif|voice|video)\s)[^\]]*\]", re.I)  # e.g. echoed "[photo]"


REPEAT_RE = re.compile(r"(.)\1{12,}")  # "YOOOOOOOOOOOOOO…" -> capped


EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF\uFE0F\u200D\u2764]+")


def strip_emoji(line: str, keep_one: bool) -> str:
    """Almost no emoji: remove them all, or (rarely) keep just the first one."""
    if media.MEDIA_LINE_RE.match(line.strip()) or judge.parse_model_choice(line):
        return line  # [sticker 😂] / [react 👍] are commands, not text
    first = EMOJI_RE.search(line)
    cleaned = EMOJI_RE.sub("", line)
    if keep_one and first:
        cleaned = cleaned.rstrip() + " " + first.group(0)[0]
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def clean_reply(reply: str) -> str:
    first = (app.me.first_name or "").strip() if app.me else ""
    keep_one = random.random() < C.EMOJI_KEEP_CHANCE
    lines = []
    reply = re.sub(r"\s+/\s+|\s+⏎\s+", "\n", reply)  # the examples' line-break marker, copied into the answer
    for line in reply.splitlines():
        line = line.strip().lstrip("/|").strip()
        if ASSISTANT_RE.search(line) or IDENTITY_CLAIM_RE.search(line) or REFUSAL_RE.search(line):
            continue
        line = FAKE_TAG_RE.sub("", HTML_TAG_RE.sub("", PLACEHOLDER_RE.sub("", EMPTY_TAG_RE.sub("", line))))
        line = re.sub(r"^\s*\d{1,2}[.)]\s+(?=\D)", "", line)  # "1) …" list numbering
        if first:  # drop a "Name:" speaker label
            line = re.sub(rf"^\s*{re.escape(first)}\s*:\s*", "", line, flags=re.I)
        line = REPEAT_RE.sub(lambda m: m.group(1) * 8, line).strip()
        line = masculine(strip_emoji(line, keep_one))
        if line:
            lines.append(line)
    return "\n".join(lines)


# You are a guy: a model sometimes writes first-person verbs in the feminine ("поняла", "была занята").
_MASC = {"поняла": "понял", "сделала": "сделал", "хотела": "хотел", "думала": "думал", "забыла": "забыл", "устала": "устал",
         "рада": "рад", "готова": "готов", "должна": "должен", "согласна": "согласен", "занята": "занят", "пришла": "пришёл",
         "видела": "видел", "знала": "знал", "смогла": "смог", "уверена": "уверен", "написала": "написал",
         "сказала": "сказал", "была": "был", "пошла": "пошёл", "спала": "спал", "ела": "ел", "взяла": "взял"}


_FEM_RE = re.compile(r"\b(" + "|".join(_MASC) + r")\b", re.I)


_SHE_RE = re.compile(r"\b(она|мама|мам|сестра|бабушка|т[её]тя|девушка|учительница|подруга|\w+[ая]\s+(сказала|написала|была))\b", re.I)


def masculine(line: str) -> str:
    if not C.OWNER_MALE or _SHE_RE.search(line):
        return line  # the sentence is about a woman: leave it
    def fix(match):
        word = _MASC[match.group(1).lower()]
        return word.capitalize() if match.group(1)[0].isupper() else word
    return _FEM_RE.sub(fix, line)


MEDIA_SPLIT_RE = re.compile(r"(\[(?:sticker|gif|voice|video)\s+[^\]]+\])", re.I)


def split_reply(reply: str, wanted: int = 0) -> list[str]:
    """One part per line (media tags on their own). Text beyond MAX_PARTS messages is dropped, not glued together:
    when the model emits a pile of short lines it is imitating bursts badly, and only the start makes sense."""
    parts = [p.strip() for line in reply.splitlines() for p in MEDIA_SPLIT_RE.split(line) if p.strip()]
    kept, texts = [], 0
    for p in parts:
        if media.MEDIA_LINE_RE.match(p):
            if not any(media.MEDIA_LINE_RE.match(k) for k in kept):
                kept.append(p)  # at most one media item
        elif texts < max(C.MAX_PARTS, wanted):  # wanted: they asked that many separate questions
            if any(re.sub(r"[\W_]+", " ", k.lower()).strip() == re.sub(r"[\W_]+", " ", p.lower()).strip() for k in kept):
                continue  # the model wrote the same line twice
            kept.append(p)
            texts += 1
    return kept


def answer_each(several: list, parts: list[str], fixed: str | None) -> bool:
    """Several questions, one answer line each: check every pair on its own, so a made-up "я дома" is put off
    without throwing away the correct answer to the other question. -> False if lines and questions don't match up."""
    lines = [i for i, p in enumerate(parts) if p != fixed and not media.MEDIA_LINE_RE.match(p)]
    if len(several) < 2 or len(lines) != len(several):
        return False
    for i, question in zip(lines, several):
        kind = judge.overreach(question.raw_text or "", parts[i], memory.today_note())
        if kind:
            parts[i] = judge.dodge(kind, lang.base(lang.detect(question.raw_text or "")))
    return True


def stale_parts(history, parts: list[str]) -> list[str]:
    """Lines of a draft that were already said in this chat: by you (the model copies its own earlier
    messages from the history and gets stuck on them) or just now by them (parroting)."""
    recent = [m.raw_text for m in history if m.raw_text][:C.REPEAT_LOOKBACK]
    said = {judge._norm(t) for t in recent} | {judge._norm(line) for t in recent for line in t.splitlines()}
    return [p for p in parts if not media.MEDIA_LINE_RE.match(p)
            and len(judge._norm(p).split()) >= 2 and judge._norm(p) in said]


_LAT2CYR = dict(zip("abvgdezijklmnoprstufhcyq", "абвгдезийклмнопрстуфхцик")) | {"w": "в", "x": "кс"}


_name_re: re.Pattern | None = None


def name_re() -> re.Pattern:
    """Your first name (Latin and Cyrillic, with case endings), your username, and the names from USERBOT_NAMES."""
    global _name_re
    if _name_re is None:
        first = (app.me.first_name or "").split()[0].lower() if app.me and app.me.first_name else ""
        words = {w for w in [first, "".join(_LAT2CYR.get(ch, ch) for ch in first), *C.NAME_WORDS] if len(w) >= 3}
        forms = [re.escape(w) + (r"(?:а|у|е|ом|ы|чик)?" if re.search("[а-яё]", w) else r"(?:'?s)?") for w in sorted(words)]
        if app.me and app.me.username:
            forms.append("@?" + re.escape(app.me.username.lower()))
        _name_re = re.compile(r"(?<![\w@])(?:" + "|".join(forms or ["\\b\\B"]) + r")(?!\w)", re.I)
    return _name_re
