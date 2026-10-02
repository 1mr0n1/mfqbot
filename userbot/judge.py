"""Two judgment calls a person makes before answering: "does this even need a reply?" and "is this one for me?"

- closers: "ok", "👍", a lone sticker after YOUR message don't need a text reply — skip them or just react.
- sensitive: money, emergencies, someone upset, codes/passwords… are not answered by the bot at all;
  the owner is pinged in Saved Messages and the bot stays out of that chat for a while.
"""
import itertools
import logging
import random
import re

import httpx

from . import config as C

log = logging.getLogger("userbot.judge")

# ---------- messages that don't need a reply ----------
ACK_WORDS = set("""ok okay okey oki k kk ок окей оке окк ага угу ладно лан понял поняла понятно ясно хорошо хоп хор норм
 нормально договорились отлично супер круто класс xop hop mayli bo'ldi boldi tushunarli ha yes yep yeah yea sure got it
 alr alright aight bet fine cool nice good да даа ну и all right""".split())
THANKS_WORDS = set("""спс спасибо пасиб спасибки благодарю rahmat raxmat рахмат thx thanks thank you ty tysm большое
 катта katta огромное выручил выручила помог помогла от души душевно красава красавчик лучший""".split())
BYE_WORDS = set("""пока покеда пакеда давай до завтра встречи связи свидания увидимся спокойной ночи споки сладких снов
 доброй bye byee goodbye gn night good see you ya cya later ttyl take care xayr hayr ko'rishguncha korishguncha
 yaxshi dam ol oling tun tuning хайр""".split())
LAUGH_RE = re.compile(r"^(lo+l|lma+o+|lmfa+o+|п?[ахaxh]{4,}|\)+)$", re.I)
# how people address each other — doesn't change what kind of message it is
VOCATIVE = set("""bro бро брат братан братишка чел друг dude man aka uka opa opajon oyijon dadajon мам мама пап папа
 дядя тётя jigar jiga do'stim dostim""".split())
EMOJI_ONLY_RE = re.compile(r"^[\W\d_]*$")  # no letters at all: emoji, punctuation
# fillers that say nothing ("idk", "ааа", "ого", "хм"): nothing to answer, and no reaction either
FILLER_RE = re.compile(r"^(а+|о+|э+|м+|у+|хм+|гм+|ну+|ого+|ух+|эх+|ясн\w*|понятн\w*|idk|uh+|um+|hm+|oh+|ah+|mm+|eh+|aa+|oo+)$", re.I)
REACTIONS = ["👍", "❤"]  # the only reactions the account uses


def _closer_kind(text: str) -> str | None:
    """-> 'thanks' | 'bye' | 'ack' | 'laugh' | 'emoji' if the whole message is just that, else None."""
    text = text.strip()
    if "?" in text or re.search(r"\d\s*[+\-*/x×]\s*\d", text):
        return None  # "?" / "??" means "hello, answer me", not "bye"; "а 391/17" is a question
    if not text or EMOJI_ONLY_RE.match(text):
        return "emoji"
    words = [w for w in re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*", text.lower()) if w not in VOCATIVE]
    if "?" in text or len(words) > 6:
        return None
    if not words:
        return "ack"
    if all(LAUGH_RE.match(w) for w in words):
        return "laugh"
    if all(FILLER_RE.match(w) or w in ("бля", "блин", "капец", "жесть", "damn", "bruh") for w in words) and len(words) <= 3:
        return "filler"
    if not all(w in ACK_WORDS or w in THANKS_WORDS or w in BYE_WORDS or LAUGH_RE.match(w) for w in words):
        return None
    if any(w in BYE_WORDS for w in words) and not all(w in ACK_WORDS for w in words):
        return "bye"
    if any(w in THANKS_WORDS for w in words):
        return "thanks"
    return "ack"


NIGHT_RE = re.compile(r"спокойной|сладких\s+снов|\bспок\w*|доброй\s+ночи|good\s*night|\bgn\b|xayrli\s+tun|хайрли\s+тун|yaxshi\s+(dam|uxla)", re.I)


def closer_action(history, after_id: int = 0) -> str | None:
    """-> 'react:<emoji>' or None (= answer normally). Only when they're closing after YOUR message.

    Someone wrapping up ("ok", "спасибо", "пока", "спокойной ночи") gets a reaction instead of more text."""
    # after_id: messages up to this id already got their reaction — a reaction is not a message, so without this
    # every "ок" you reacted to would still count as waiting, and the fourth one would look like a real burst
    unanswered = list(itertools.takewhile(lambda m: not m.out and getattr(m, "id", 0) > after_id, history))
    if not unanswered or len(unanswered) > 3:
        return None  # nothing new, or a real burst
    from . import salam
    if all(salam.is_response(m.raw_text or "") and len(salam.remainder(m.raw_text or "").split()) < 3 for m in unanswered):
        return "skip"  # they answered your greeting; nothing to add
    mine = next((m for m in history if m.out), None)
    if any(NIGHT_RE.search(m.raw_text or "") for m in unanswered) and not (mine and NIGHT_RE.search(mine.raw_text or "")):
        return None  # "спокойной ночи" is wished back, once
    kinds = []
    for msg in unanswered:
        if msg.photo or msg.voice or msg.video or msg.video_note or (msg.document and not msg.sticker):
            return None
        kind = "emoji" if msg.sticker else _closer_kind(msg.raw_text or "")
        if not kind:
            return None
        kinds.append(kind)
    if all(k == "filler" for k in kinds):
        return "skip"
    if "thanks" in kinds or "bye" in kinds:
        return "react:❤" if "thanks" in kinds or random.random() < 0.4 else "react:👍"
    return "react:👍"


# one-word answers that say nothing more and close nothing ("how are you?" — "норм")
DRY_WORDS = set("""норм нормально норма ничего ниче ничо нечего да нет не неа ага угу хз незнаю так себе пойдет пойдёт сойдет
    хорошо плохо отлично супер класс круто скучно тоже также и я ну вот всё все ок окей ладно ясно понятно понял поняла
    nm nothing nth good fine ok okay yeah yep nah nope same idk bored cool nice alr aight bet lol
    yaxshi zor ha yoq yo'q hech narsa bilmadim mayli xop boladi tuzuk""".split())


def dry(history, after_id: int = 0) -> bool:
    """They answer with next to nothing ("ок", "да", "норм", a laugh, a sticker) but haven't said goodbye:
    the conversation is running out, not ending."""
    unanswered = list(itertools.takewhile(lambda m: not m.out and getattr(m, "id", 0) > after_id, history))
    if not unanswered or len(unanswered) > 3:
        return False
    worded = False
    for msg in unanswered:
        if msg.photo or msg.voice or msg.video or msg.video_note or (msg.document and not msg.sticker):
            return False
        if msg.sticker:
            continue
        text = (msg.raw_text or "").strip()
        kind = _closer_kind(text)
        if "?" in text or kind in ("bye", "thanks") or GREETING_RE.match(text):
            return False
        words = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*", text.lower())
        if kind is None and not (words and len(words) <= 3 and all(w in DRY_WORDS or w in VOCATIVE for w in words)):
            return False  # anything with content — a short question, a request, news — is not "dry"
        worded = worded or kind != "emoji"
    return worded  # a lone 👍, ❤ or sticker ends an exchange; it isn't an invitation to keep talking


KEEP_GOING_HINT = (
    "\nThey are answering dryly and the conversation is running out. Don't let it die and don't just acknowledge: "
    "keep it going the way a friend would. Write ONE short casual line that gives them something to answer — ask how "
    "their day went, what they are doing right now, what the plans are for today or the weekend, or bring up "
    "something you know about them or something from earlier in this chat. It is {clock} now, {weekday}: pick what "
    "fits the time (no \"how was your day\" in the morning). Don't ask anything that was already asked in this chat, "
    "don't invent news about yourself, no [react …]. This overrides the rule about answering only what was asked.\n")


def parse_model_choice(reply: str) -> str | None:
    """The model may answer [react 👍] (e.g. when asked to "like" something) instead of text."""
    match = re.fullmatch(r"\[react\s+(\S+)\]", reply.strip(), re.I)
    if match:
        emoji = match.group(1).replace("\ufe0f", "")
        return f"react:{emoji if emoji in REACTIONS else '👍'}"
    return None


REACT_HINT = ("\nIf they ask you to like or react to their message, answer with exactly [react 👍] or [react ❤] and "
              "nothing else.\n")


# ---------- messages the owner should handle personally ----------
ASK = r"(скинь|скинешь|кинь|переведи|перевед[её]шь|отправь|дай|дашь|займи|одолжи|нужн[оы]|надо|tashla|tashab|o'tkaz|yubor|ber|send|give|lend|transfer|pay)"
AMOUNT = r"(деньг\w*|денег|на\s+карт\w*|kartaga|\bpul\b|\$\s?\d{2,}|\d{2,}\s?(k\b|к\b|тыс\w*|млн\w*|mln|ming|сум\w*|sum\b|so'm|руб\w*|\$|usd))"
# Someone in real trouble. These are never answered by the account, whatever the switches say: a person in a
# crisis must get you, not an auto-reply. You are told at once.
CRISIS_RE = re.compile(
    r"не\s+хочу\s+(больше\s+)?жить|хочу\s+умереть|покончить\s+с\s+собой|суицид\w*|убью\s+себя|никому\s+не\s+нуж\w+|"
    r"вс[её]\s+бессмысленн\w*|не\s+вижу\s+смысла|не\s+хочу\s+больше\s+ничего|"
    r"меня\s+(бьют|бь[её]т|избива\w+|избил\w*|побил\w*|насилу\w+|шантажиру\w+|преследу\w+)|шантаж\w*|угрожа\w+\s+(мне|выложить|слить)|"
    r"хочу\s+сбежать\s+из\s+дома|сбегу\s+из\s+дома|"
    r"kill\s+myself|want\s+to\s+die|don'?t\s+want\s+to\s+live|no\s+reason\s+to\s+live|suicid\w*|self[-\s]?harm|"
    r"(he|she|they|dad|mom)\s+(hits?|beats?)\s+me|being\s+blackmailed|blackmail\w*|"
    r"yashagim\s+kelmay\w*|o'?lgim\s+kel\w*|meni\s+ur(adi|ishadi|yapti)|"
    r"скор(ую|ая)\s+(вызвал\w*|едет|приехал\w*|увезл\w*)|вызвал\w*\s+скор\w+|в\s+реанимаци\w*|"
    r"(бабушк|дедушк|мам|пап|брат|сестр)\w*\s+(стало\s+|очень\s+)?плохо|плохо\s+(стало\s+)?(с\s+)?(бабушк|дедушк|мам|пап)\w*|"
    r"приезжай\s+срочно|срочно\s+приезжай|tez\s+yordam\s+chaqir\w*|(buving|bobong|oying|dadang)\w*\s+(ahvoli\s+)?yomon", re.I)


def crisis(history) -> bool:
    return any(CRISIS_RE.search(m.raw_text or "") for m in itertools.takewhile(lambda m: not m.out, history))


STRONG = [  # unmistakable cases, decided without a model
    ("a verification code or password",
     r"\b(otp|password|passcode)\b|парол\w*|\bparol\w*"
     r"|(sms|смс|verification|login|confirm\w*|подтвержд\w*|tasdiq\w*)\W+(\w+\W+){0,3}(code|код|kod)\b"
     r"|\b(code|код|kod)\b\W+(\w+\W+){0,3}(sms|смс|приш[её]л\w*|прислал\w*|отправ\w*|скин\w*|keldi|yubor\w*|ayt\w*|came|sent)"),
    # asking for money or a transfer — not merely mentioning money or a price
    ("money", rf"\b(lend|borrow|loan)\b|\bowe\s+(me|you|u)\b|\bзайм\w*\b(?!\s+(мне\s+)?(место|очередь|стол))|\bзаня(ть|л|ла)\b(?!\s+(мне\s+)?(место|очередь|стол))"
              rf"|\bодолж\w*|\bв\s+долг\b|\bqarz\w*|ты\s+мне\s+(\d\S*\s+)?долж(ен|на)\b(?!\s+\w+(ть|ться|ти|чь)\b)|мне\s+долж(ен|на)\s+\d|сколько\s+(ты\s+)?(мне\s+)?долж\w+|ты\s+(же\s+)?занимал|верни\s+(мне\s+)?(деньги|долг|\d+)|когда\s+(отдашь|верн[её]шь)\s+(деньги|долг)|номер\w*\s+карт\w*|card\s+number|karta\s+raqam\w*|реквизит\w*"
              rf"|\b{ASK}\b[^.?!\n]{{0,40}}{AMOUNT}|{AMOUNT}[^.?!\n]{{0,25}}\b{ASK}\b"),
    # something happening right now, not a word that just sounds urgent
    ("an emergency", r"\b(emergency|ambulance)\b|\b(in|at)\s+(the\s+)?hospital\b|\b(car\s+)?accident\b|\bcall\s+the\s+police\b"
                     r"|\bв\s+больниц\w*|скор(ая|ую)\s+помощ\w*|попал\w*\s+в\s+авари\w*|\bавария\b"
                     r"|срочно\s+(позвони|приезжай|приходи)|у\s+меня\s+умер\w*|\bумерла?\s+(мама|папа|бабушка|дедушка|брат|сестра)"
                     r"|kasalxona\w*|tez\s+yordam|avariya|vafot\s+et\w*"),
]
CLASSIFY = (
    "Below are the latest messages someone sent to their friend or relative {name} in a private chat. Decide whether "
    "{name} must answer PERSONALLY instead of sending a quick casual reply.\n"
    "PERSONAL only when the person is sincerely telling something serious about THEIR OWN life right now: they are "
    "crying, panicking or say they feel terrible; they sincerely want to end the friendship or have a serious talk "
    "about the relationship; real bad news (illness, injury, a death); trouble with police, the school "
    "administration or the law.\n"
    "NORMAL for everything else, including: insults and swearing aimed at {name} ('иди нахуй', 'ты дурак'), teasing, "
    "banter, trolling, provocations, sarcasm, complaints or reproaches ('you didn't reply'), jokes and pranks — even "
    "ones that mention dead relatives or other serious things as part of a joke or a request to make {name} say "
    "something; embarrassing or silly stories; plans, favors, questions, greetings; asking {name} to write or do "
    "something. When in doubt, answer NORMAL.\n"
    "Answer with one word, PERSONAL or NORMAL, then a dash and the reason in at most 6 words.\n\nMESSAGES:\n{messages}"
)


async def sensitive_reason(http: httpx.AsyncClient, name: str, history, keywords_only: bool = False) -> str | None:
    """-> why the owner should take this one, or None. keywords_only skips the model's judgment call."""
    texts = [m.raw_text for m in itertools.takewhile(lambda m: not m.out, history) if m.raw_text]
    joined = "\n".join(reversed(texts))
    if not joined.strip():
        return None
    for reason, pattern in STRONG:
        if re.search(pattern, joined, re.I):
            return reason
    if keywords_only or not C.HANDOFF_JUDGE or len(joined.split()) < 4:
        return None  # only the unmistakable cases, or too short to be worth a model call
    try:
        resp = await http.post("/complete", json={
            "messages": [{"role": "user", "content": CLASSIFY.format(name=name, messages=joined[:1500])}],
            "models": C.JUDGE_MODELS, "max_tokens": 30, "temperature": 0})
    except httpx.HTTPError:
        return None
    if resp.is_error:
        return None
    verdict = resp.json()["reply"].strip()
    if verdict.upper().startswith("PERSONAL"):
        return re.sub(r"^PERSONAL\W*", "", verdict, flags=re.I).strip()[:80] or "needs a personal answer"
    return None


# ---------- a second look at the draft before it is sent ----------
# Rule-based on purpose: a model judging a model rejects perfectly good replies ("Привет", a name, a school).
# The model is only asked one narrow thing — whether specific unfamiliar words are real.
GREETING_RE = re.compile(r"^(привет\w*|здравствуй\w*|здаров\w*|доброе утро|добрый (день|вечер)|ку|хай|салам\w*|салом\w*|"
                         r"hi|hey|hello|yo|sup|salom|assalomu alaykum)\W*$", re.I)
_english: set[str] | None = None
_vocab: set[str] | None = None
CHAT_ENGLISH = {
    "ok", "okay", "lol", "lmao", "bruh", "bro", "chill", "chillin", "vibe", "vibing", "gonna", "wanna", "gotta", "nah",
    "yeah", "yep", "nope", "idk", "btw", "omg", "wtf", "imo", "rn", "pls", "plz", "thx", "ty", "sry", "cuz", "tho", "fr",
    "ngl", "sus", "cringe", "nice", "cool", "wow", "yo", "hey", "hi", "bye", "aight", "wsg", "gg", "ez", "noob", "skill",
    "iphone", "ipad", "macbook", "airpods", "telegram", "youtube", "tiktok", "instagram", "whatsapp", "discord", "steam",
    "google", "chatgpt", "xiaomi", "samsung", "android", "windows", "wifi", "bluetooth", "online", "offline", "stream",
    "pubg", "minecraft", "roblox", "fortnite", "valorant", "csgo", "python", "olx", "uzum", "yandex", "click", "payme",
    "codm", "tmrw", "lyk", "hw", "haha", "hahaha", "dunno", "kinda", "sorta", "lemme", "gimme", "imma", "ya", "yea",
}


_uz_words: set[str] | None = None   # an Uzbek dictionary, if you downloaded one (userbot/get_uz_dictionary.py)


def in_uz_dictionary(word: str, min_stem: int = 3) -> bool:
    """Is this a real Uzbek word — the dictionary form, or that form with endings added (kitob → kitoblarimizda)?"""
    global _uz_words
    if _uz_words is None:
        path = C.STYLE_DIR / "uz_dictionary.txt"
        _uz_words = set(path.read_text().split()) if path.exists() else set()
    if not _uz_words:
        return False
    word = re.sub("[ʻ‘’`ʼ]", "'", word.lower())
    for form in (word, word.replace("'", "")):
        for cut in range(len(form), 2, -1):  # Uzbek stacks endings on the stem: try the word, then ever shorter stems
            if cut < min_stem and cut != len(form):
                break
            if form[:cut] in _uz_words and (cut == len(form) or cut >= 4 or len(form) >= 6):
                return True
    return False


def _load_words():
    global _english, _vocab
    if _english is None:
        try:
            with open("/usr/share/dict/words") as f:
                _english = {w.strip().lower() for w in f}
        except OSError:
            _english = set()
    if _vocab is None:
        path = C.STYLE_DIR / "vocab.txt"  # every word that appears in your exported chats
        _vocab = set(path.read_text().split()) if path.exists() else set()


def _is_english(word: str) -> bool:
    w = word.lower().strip("'")
    stems = {w, w.rstrip("s"), w[:-2] if w.endswith("ed") else w, w[:-3] if w.endswith("ing") else w,
             w[:-3] + "e" if w.endswith("ing") else w, w[:-1] if w.endswith("n") else w}
    return bool(stems & (_english or set())) or w in CHAT_ENGLISH


def foreign_word(them: str, draft: str) -> str | None:
    """In a Cyrillic reply: a Latin-letter word that isn't English, chat slang, a brand, or something they wrote."""
    _load_words()
    if not re.search("[а-яё]", draft, re.I) or not _english:
        return None
    theirs = set(re.findall(r"[a-z']+", them.lower()))
    for word in re.findall(r"[A-Za-z][A-Za-z']{3,}", draft):
        if not (_is_english(word) or word.lower() in theirs or word.lower() in (_vocab or set())):
            return word
    return None


VOWELS = set("аеёиоуыэюяйьъўaeiouy'ʻ‘’")  # й, ь, ъ break up consonant runs too ("майнкрафт" is a real word)


def looks_random(word: str) -> bool:
    """Random-letter strings have long consonant runs or almost no vowels; real words (even rare ones) don't."""
    run = longest = 0
    for ch in word:
        run = 0 if ch in VOWELS else run + 1
        longest = max(longest, run)
    vowels = sum(ch in VOWELS for ch in word)
    return longest >= 4 or vowels / len(word) < 0.2


def unknown_words(them: str, draft: str) -> list[str]:
    """Words that look like random letters AND never appear in your chats, in English, or in their message."""
    _load_words()
    theirs = set(re.findall(r"[^\W\d_]+(?:['ʻ‘’][^\W\d_]+)*", them.lower()))
    out = []
    for word in re.findall(r"[^\W\d_]+(?:['ʻ‘’][^\W\d_]+)*", draft.lower()):
        if len(word) < 6 or word in (_vocab or set()) or word in theirs or _is_english(word) or word in out:
            continue
        if looks_random(word):
            out.append(word)
    return out


def invented_uzbek(them: str, draft: str) -> str | None:
    """In an Uzbek reply: a word that never appears in your chats (nor in their message, nor in English or
    Russian-typed-in-Latin slang). Models make up plausible-looking Uzbek; your real vocabulary is the test."""
    from . import lang

    _load_words()
    if not _vocab or lang.base(lang.detect(draft)) != "uz":
        return None
    theirs = set(re.findall(r"[^\W\d_]+(?:['ʻ‘’][^\W\d_]+)*", them.lower().replace("‘", "'").replace("’", "'").replace("ʻ", "'")))
    for word in re.findall(r"[^\W\d_]+(?:['ʻ‘’][^\W\d_]+)*", draft.lower().replace("‘", "'").replace("’", "'").replace("ʻ", "'")):
        plain = word.replace("'", "")
        if len(plain) < 5 or word in theirs or word in _vocab or plain in _vocab or _is_english(word) \
                or in_uz_dictionary(word):
            continue
        # everyday spelling drops apostrophes and endings vary: accept if a known word shares most of it
        stem = plain[:max(4, len(plain) - 3)]
        if any(v.startswith(stem) for v in _vocab if v[:1] == plain[:1]):
            continue
        return word
    return None


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


async def review(http: httpx.AsyncClient, them: str, draft: str, expected: str | None = None) -> str | None:
    """-> None if the draft may be sent, otherwise why not. If a check itself fails, the draft passes."""
    from . import lang

    text = "\n".join(line for line in draft.splitlines() if not re.match(r"^\[(sticker|gif|voice|video)\s", line.strip(), re.I))
    if not text.strip():
        return None  # only media
    last_theirs = them.strip().splitlines()[-1] if them.strip() else ""
    if _norm(text) and _norm(text) == _norm(last_theirs) and not GREETING_RE.match(last_theirs.strip()) \
            and not NIGHT_RE.search(last_theirs) \
            and len(_norm(text).split()) >= 2:
        return "it repeats their message"
    if re.search(r"перевед\w*|перевод\w*|translat\w*|tarjima\w*|на\s+(узбекск|английск|русск)\w*|по[-\s](узбекски|английски|русски)|"
                 r"\bin\s+(english|russian|uzbek)\b|(inglizcha|o'zbekcha|ruscha)", them, re.I):
        return None
    their_lang, draft_lang = lang.base(lang.detect(them)), lang.base(lang.detect(text))
    their_cyrillic = bool(re.search("[а-яё]", them, re.I))
    # Only clear mismatches count. A Russian answer to Latin-script text (transliterated Russian, Uzbek, mixed)
    # is how you often write, so it passes; Uzbek or English out of nowhere does not.
    # "x = 5", "2x = 10", "391": numbers and symbols are no language at all
    worded = len(re.findall(r"[^\W\d_]{3,}", text)) >= 2
    if expected is None and worded and len(them.split()) >= 2 and len(text.split()) >= 2:
        if draft_lang == "uz" and their_lang != "uz":
            # only when they clearly wrote Russian or English: a short or slangy Uzbek message ("qalesan", "ишлар калай")
            # is often not recognised as Uzbek, and answering it in Uzbek is exactly right
            their_words = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*", them.lower())
            clearly_other = their_lang in ("ru", "en") and len(their_words) >= 3 \
                and not any(lang._dictionary_uzbek(w) or w in lang.UZ_WORDS for w in their_words)
            if clearly_other:
                return f"wrong language (uz instead of {their_lang})"
        latin = re.findall(r"[A-Za-z]{3,}", text)
        a_name = bool(latin) and all(w[0].isupper() for w in latin) and len(text.split()) <= 6  # "Call of Duty Mobile"
        if draft_lang == "en" and their_lang == "ru" and their_cyrillic and not re.search("[а-яё]", text, re.I) and not a_name:
            return "wrong language (en instead of ru)"  # a Russian reply with a game or app name in it is fine
    odd = foreign_word(them, text)
    if odd:
        return f"strange word '{odd}'"
    # they wrote in Cyrillic, the draft has no Cyrillic at all and isn't just a word or two (a name, "ok", a translation)
    if expected is None and worded and re.search("[а-яё]", them, re.I) and not re.search("[а-яё]", text, re.I) \
            and len(re.findall(r"[A-Za-z]{2,}", text)) >= 3 \
            and not all(w[0].isupper() or len(w) < 3 for w in re.findall(r"[A-Za-z]{2,}", text)):
        return "wrong language (Latin letters instead of Russian)"
    suspects = unknown_words(them, text)
    if suspects:
        return f"nonsense word '{suspects[0]}'"
    made_up = invented_uzbek(them, text)
    if made_up:
        return f"Uzbek word you never use: '{made_up}'"
    return None


# ---------- things the account must not decide or claim on its own ----------
PLAN_RE = re.compile(
    r"\bго\b|\bв\s+деле\b|участвуешь|скидыва\w+|скинешься|\bare\s+(you|u)\s+in\b|\bдай(те)?\b|убери\w*|покажи\w*|помой\w*|вынеси\w*|сделай\w*|напиши\s+(мне|потом|когда)|перезвони\w*|\bsend\b|\bcall\s+me\b|зайди\w*|залетай\w*|подключайся|\bскинь\b|скинешь|\b(ты\s+)?с\s+нами\b|пойд[её]шь|ид[её]шь|прид[её]шь|зайд[её]шь|приедешь|когда\s+(буд|прид|приед|вый|зайд)\w+|через\s+сколько|"
    r"set\s+(me|up)|can\s+(you|u)\s+(set|send|give|buy|get)|встрет\w*|давай\s+(в|на|завтра|сегодня|после)|поможешь|принес\w*|"
    r"отдашь|ждём|ждем|выходи|подойд[её]шь|переночу\w*|купи\w*|позвони\w*|забери\w*|сходи\w*|съезди\w*|приезжай\w*|"
    r"приходи\w*|заходи\w*|отнеси\w*|верни\w*|оплати\w*|закажи\w*|во\s+сколько\s+(встрет|прид|буд|выйд|зайд|приед|увид)\w*|"
    r"\b(wanna|coming|come\s+(over|to)|meet|bring|let'?s)\b|kelasan\w*|borasan\w*|chiqasan\w*|uchrash\w*|olib\s+kel|"
    r"\b\w{3,}(asanmi|asizmi|asilami|asila|aymi|amizmi|olasanmi)\b|\bborib\s+kel|\bkelib\s+ket|\b(bor|kel|ol|ber|ayt)(ing|gin)?\b|"
    r"\b(och|qil|yoz|yubor|tashla|chiq|yop|o['ʻ‘’]?chir)(ing|gin)?\b|верн[её]шь|вернуть|отдашь|отдать|верни\b", re.I)
# a promise said flat, whatever they wrote: "скоро буду", "уже иду", "ща приду"
FLAT_PROMISE_RE = re.compile(
    r"\b(скоро\s+буду|буду\s+через|ща[сз]?\s+(приду|буду|выйду|зайду|открою|принесу)|уже\s+(иду|еду|выхожу|бегу|открываю)|"
    r"(иду|еду|выхожу|бегу)\s+уже|выезжаю|on\s+my\s+way|omw|kelyapman|boryapman|chiqyapman)\b"
    r"|^\W*(иду|еду|бегу|выхожу|открываю|открыл|coming|ochyapman)\W*$"
    r"|^\W*(xo['ʻ‘’]?p|mayli|хоп|хўп|майли)\W+(\w+\s+){0,2}\w{2,}(aman|аман)\b", re.I)
SOON_RE = re.compile(r"\W*(завтра|сегодня|вечером|утром|скоро|ertaga|bugun|kechqurun|tomorrow|today|tonight|soon)\W*", re.I)
COMMIT_RE = re.compile(
    r"\b(уберу|покажу|помою|вынесу|перезвоню|наберу|напишу|напомню|sending|on\s+it|will\s+do)\b|\b(приду|буду|выйду|зайду|подойду|приеду|принесу|отдам|помогу|скину|сделаю|договорились|переночую|куплю|"
    r"позвоню|заберу|схожу|съезжу|отнесу|верну|оплачу|закажу|поеду|пойду|"
    r"го|погнали|заходи|выхожу|иду|еду)\b|\bв\s+\d{1,2}([:.]\d\d)?\b|\bчерез\s+(час|пол\w*|минут\w*|\d+)|\bжду\b|\b(sure|ok|okay|yeah),?\s+(do|i'?ll|will|done)\b|\b(давай|ок|окей|хорошо|да|конечно)\b[\s,]+\b(приду|буду|зайду|го|давай|помогу)\b|"
    r"\b(i'?ll\s+(come|be|bring|help)|coming|on\s+my\s+way|let'?s\s+go|sure\s+let'?s|yeah\s+let'?s|im\s+down)\b|"
    r"\b(kelaman|boraman|chiqaman|olib\s+kelaman|xop\s+kelaman|\w{3,}(ayapman|aman|amiz|yman)|hozir\s+\w+man)\b", re.I)
DID_RE = re.compile(
    r"\b(сделал\w*|сдал\w*|прив[её]з(ла|ли)?|прин[её]с(ла|ли)?|подготовил\w*|написал\w*|выучил\w*|поел\w*|покушал\w*|кушал\w*|"
    r"взял\w*|купил\w*|забрал\w*|был\w*\s+(на|в|у)|ходил\w*|почему\s+(тебя|вас)\s+не\s+было)\b|"
    r"\bdid\s+(u|you)\b|\bhave\s+(u|you)\b|\b\w{2,}(dingmi|dingizmi|ganmisan|ganmisiz|ibmi|dimi)\b", re.I)
# yes/no questions about you right now that only you can answer: "ты выпил таблетки?", "папа дома?", "температура есть?"
STATE_Q_RE = re.compile(
    r"\bу\s+тебя\s+есть\b|\bесть\s+у\s+тебя\b|\bdo\s+(you|u)\s+have\b|\bsenda\s+\w+\s+bormi\b|"
    r"\bты\b[^?]*\b\w{2,}(ил|ал|ел|ял|ул|ыл|ёл)(а|и)?(ся|сь)?\b[^?]*\?|\b\w{2,}(ил|ал|ел|ял|ул|ыл)(а|и)?(ся|сь)?\s*\?"
    r"|\b(температура|деньги|время|еда|зарядка|ключи)\s+есть\s*\?|\bесть\s+(температура|деньги|время)\s*\?"
    r"|\b(дома|там|рядом|свободен|свободна|занят|занята|идешь|идёшь|едешь|готов|готова)\s*\?"
    r"|\b\w{3,}(mi|misan|misiz|ми|мисан|мисиз)\s*\?", re.I)
UZ_Q_RE = re.compile(r"\b\w{3,}(misan|misiz|мисан|мисиз)\b|\b[a-z'ʻ‘’]{3,}mi\b(?!\s*-)", re.I | re.M)
CLAIM_RE = re.compile(r"^\W*(?:(?:а|ну|э+|хм+|не)\W+)?(да|нет|нету|есть|не|неа|ага|угу|ещё\s+нет|еще\s+нет|пока\s+нет|уже|yes|yeah|yep|no|nope|nah|not\s+yet|"
                      r"ha|haa|yo['ʻ‘’]?q|yoq|xa|ха|йўқ|йук|ҳа|hali\s+yo['ʻ‘’]?q|"
                      r"\w{2,}(dim|madim|ganman|maganman))\b", re.I)
AFFIRM_RE = re.compile(r"^\W*(да|ага|угу|ок|окей|оке\w*|хорошо|конечно|давай|го|погнали|sure|yeah|yes|yep|ok|okay|bet|"
                       r"mayli|xop|ha)\b", re.I)
UNSURE_RE = re.compile(r"don'?t\s+(know|remember)|не\s+знаю|не\s+помню|не\s+уверен|посмотр|может|хз|потом|позже|idk|not\s+sure|maybe|later|dunno|"
                       r"bilma|keyin", re.I)
DODGE = {
    "commitment": {"ru": ["не знаю ещё", "посмотрим", "не знаю, напишу", "пока не знаю"], "en": ["idk yet", "not sure yet", "will lyk"],
                   "uz": ["bilmasam", "hali bilmayman", "keyin aytaman"]},
    "claim": {"ru": ["потом скажу", "потом расскажу"], "en": ["tell u later"], "uz": ["keyin aytaman"]},
    "situation": {"ru": ["не знаю, ща гляну", "ща посмотрю", "пока не знаю"], "en": ["idk yet, lemme check", "not sure rn"],
                  "uz": ["bilmadim, qarayman", "hali bilmayman"]},
}


# ---------- facts about your real life that nobody told the account ----------
# Rule-based: a small model asked "is this made up?" answers "fine" to everything.
SITUATION_RE = re.compile(
    r"\b(ты|вы)\s+(где|куда)\b(?!\s+(жив|учи|работа|род|был|была|были))|\b(где|куда)\s+(ты|вы)\b(?!\s+(жив|учи|работа|род|был|была|были))"
    r"|\b(где|куда)\s+(щас|сейчас)\b|^\W*(где|куда)\W*$"
    r"|\bкогда\s+(ты\s+)?(прид[её]шь|приедешь|будешь|верн[её]шься|выйдешь|закончишь|освободишься)\b"
    r"|\bкогда\s+(еда|курьер|доставка|заказ)\b|\bкогда\s+\w+\s+(приедет|привезут|принесут|придет|придёт)\b"
    r"|\b(долго|скоро)\s+(ещ[её]|ты|будешь|там)\b|\bчерез\s+сколько\b"
    r"|\b(что|чё|че|чо|сколько|как(ую|ой|ое|ие))\s+(ты\s+|тебе\s+|вам\s+)?(ел|ела|ели|кушал\w*|поел\w*|заказал\w*|купил\w*|взял\w*|"
    r"получил\w*|поставили|задали)\b"
    r"|\bс\s+кем\s+(ты|вы|гуля|сид|игра|ид|пойд)\w*|\bкто\s+(с\s+тобой|там|у\s+тебя)\b"
    r"|\bwhere\s+(are|r)\s+(you|u)\b|\bwya\b|\bwhen\s+(will|are|r)\s+(you|u)\b|\bhow\s+long\b|\bwhat\s+did\s+(you|u)\s+(eat|get|order|buy)\b"
    r"|\bwho('?s|\s+is|\s+are)?\s+(you\s+|u\s+)?(with|there)\b|\bwhat('?s|\s+is)\s+the\s+(hw|homework)\b"
    r"|\bqayer\w*|\bqatta\w*|\bqachon\s+(kel|chiq|bor|qayt)\w*|\bkim\s+bilan\b|\bnima\s+(yeding|olding|berdi)\w*"
    r"|^\W*с\s+кем\W*$|\bты\s+с\s+кем\b|^\W*когда\s+домой\W*$|\bкогда\s+(ты\s+)?домой\s*\?|\bкогда\s+дома\s+будешь\b"
    # marks and tests: only you know
    r"|\bкак(ая|ую|ие)\s+(у\s+тебя\s+)?(оценк|отметк)\w*|\bчто\s+(получил|поставили)\b|\bсколько\s+(получил|баллов)\b|\bnecha\s+(olding|baho)\w*"
    r"|\b(контрольн\w+|контрош\w+|кр|экзамен\w*|сор|соч|зач[её]т\w*|тест\w*)\s+когда\b|\bкогда\s+(контрольн\w+|контрош\w+|кр|экзамен\w*|сор|соч|зач[её]т\w*|тест\w*)\b"
    r"|\bпо\s+какой\s+теме\b|\bкакой\s+кабинет\b|\bкто\s+дежурит\b"
    r"|\bкто\s+(у\s+(вас|тебя)\s+)?(классрук\w*|классн\w+\s+руководител\w+|директор\w*|ведёт|ведет)|\bкак\s+(его|е[её])\s+зовут\b"
    r"|\bкак\s+зовут\s+(тво\w+|ваш\w+)\s+(учител\w+|классн\w+|директор\w*|тренер\w*)"
    # things about THEM that the account was never told
    r"|\bкогда\s+у\s+меня\s+(др|день\s+рождени\w+)\b|\bкак\s+зовут\s+мо\w+|\bкакого\s+цвета\s+(у\s+меня|мо\w+)|\bсколько\s+мне\s+лет\b"
    r"|\bчто\s+я\s+тебе\s+(вчера\s+|сегодня\s+)?(дал|давал|говорил|писал|сказал|обещал)\b|\bwhen('?s|\s+is)\s+my\s+(birthday|bday)\b",
    re.I | re.M)
QWORD_RE = re.compile(r"^\W*(а\s+)?(когда|где|куда|что|чё|че|чо|с\s+кем|кто|сколько|во\s+сколько|qachon|qayer\w*|kim|nima|necha|when|where|"
                      r"what|who|how)\b", re.I | re.M)
# a draft that reports something only you could know: what you did, where you are, numbers, times
REPORT_RE = re.compile(
    r"\b(получил|купил|заказал|поел|съел|сдал|взял|выиграл|проиграл|принес|забрал|сходил|съездил)[аи]?\b"
    r"|\bкурьер\w*|\bуже\s+(выхожу|иду|еду|дома|близко|тут|у)\b|\bчерез\s+(\d+|пару|минут\w*|час\w*|пол\w*)"
    r"|\bi\s+(just\s+)?(got|bought|ordered|ate)\s+\w+|\bon\s+my\s+way\b|\bin\s+\d+\s*(min|h)", re.I)
NOT_KNOWN_HINT = (
    "\nYour previous draft stated things about your real life right now that you have no way of knowing here "
    "(where you are, what you ordered or ate, when something arrives, who is with you, what you got…). Do NOT make "
    "such things up. Answer like someone who hasn't checked yet: in a few words, in your usual style, say you don't "
    "know yet or will look and tell them — or ask them back. No invented details.\n")


# "я дома", "ha, uydaman", "i'm at school": where you are, stated flat — nobody told the account
WHERE_I_AM_RE = re.compile(
    r"^\W*(?:(?:да|ага|угу|ну|ha|xa|yes|yeah|yep)\W+)?(?:я\s+)?(?:уже\s+|щас\s+|сейчас\s+)?(дома|в\s+школе|на\s+уроке|на\s+улице|в\s+пути|в\s+дороге)\W*$"
    r"|\bя\s+(уже\s+|щас\s+|сейчас\s+)?(дома|в\s+школе|на\s+уроке|на\s+улице)\b(?!\s+(посижу|останусь|буду|был|не\b))|\b(один|одна)\s+дома\b"
    r"|^\W*(?:(?:да|ага|ну)\W+)?(?:я\s+)?(дома|doma)\b(?!\s+(посижу|останусь|буду|был|не\b|никого|нет\b))"
    r"|\bya\s+doma\b|^\W*(уйда|uyda)\b|\bjust\s+got\s+home\b|\bi'?m\s+(at\s+)?home\b|\bтолько\s+(пришёл|пришел|зашёл|зашел)\b"
    r"|\b(дома\s+(сижу|лежу|валяюсь)|(сижу|лежу|валяюсь)\s+дома|doma\s+si[dzj]\w+)\b"
    r"|\b(uyda|maktabda|darsda|yo['ʻ‘’]?lda|ko['ʻ‘’]?chada|ishda)man\b|^\W*(?:(?:yes|yeah|yep)\W+)?i'?m\s+(at\s+)?(home|school)\W*$", re.I)
# an amount of money: "50$", "300-350$", "275.000 сум", "20к"
AMOUNT_RE = re.compile(r"\$\s?\d+|\d[\d.,\s-]*\s?(\$|usd|сум\w*|so['ʻ‘’]?m|sum\b|ming\b|тыс\w*|руб\w*|доллар\w*|бакс\w*|[кk]\b)", re.I)
# offering to send or give money: a decision that is yours
PAY_RE = re.compile(r"\b(скину|кину|переведу|отправлю|одолжу|дам(?!\s+знать)|tashl?ay(man)?|tashl?ab\s+beraman|beraman|yuboraman|"
                    r"o['ʻ‘’]?tkazaman|i'?ll\s+(send|give|pay|lend))\b", re.I)
MONEY_WORD_RE = re.compile(r"деньг|денег|бабк|бабл|\bpul\w*|\bmoney\b|\bcash\b", re.I)


BOUNCE_RE = re.compile(r"^\W*(а\s+)?(у\s+тебя|ты|тебе|тво[йяёе]|and\s+(you|u)|urs|yours|sen-?chi|o['ʻ‘’]?zing(-?chi)?)\W*$", re.I)


def _in_facts(draft: str, them: str) -> bool:
    """Every real word of the draft is in your facts file, and so is what they asked about."""
    try:
        facts = C.FACTS_PATH.read_text().lower()
    except OSError:
        return False
    words = re.findall(r"[^\W\d_]{4,}", draft.lower())
    asked = [w[:6] for w in re.findall(r"[^\W\d_]{6,}", them.lower())]
    return bool(words) and all(w in facts for w in words) and any(w in facts for w in asked)


def made_up(them: str, draft: str, known_today: str = "", heard: str = "") -> bool:
    """They asked about your situation right now and the draft answers with specifics nobody gave the account."""
    text = draft.strip()
    if known_today or not text or text.endswith("?") or UNSURE_RE.search(text):
        return False
    words = re.findall(r"[^\W\d_]{3,}", text.lower())
    if heard and words and all(w in heard.lower() for w in words):
        return False  # they said it themselves earlier in this chat ("её Рекс зовут")
    if SITUATION_RE.search(them):
        return not _in_facts(text, them)  # your form teacher's name, your timetable: written down, so not made up
    return ("?" in them or bool(QWORD_RE.search(them))) and bool(REPORT_RE.search(text))


RELAY_RE = re.compile(r"передай\w*|скажи\s+(ему|ей|им|маме|папе|\w+е)\b|\bayt\b|aytib\s+qo|\btell\s+(him|her|them|your)\b", re.I)
RELAY_OK_RE = re.compile(r"передам|скажу|aytaman|aytib\s+qo|i'?ll\s+tell|will\s+tell|xop\b", re.I)


CRUDE_RE = re.compile(r"\b(сос[аи]\w*|[её]б\w*|дроч\w*|трах\w*|suck\w*|fuck\w*)\b", re.I)  # crude banter is not a question about your day


# "Отправил", "Готово, поставил": a chat reply can't have DONE anything — only an order that really ran may say so
DONE_RE = re.compile(r"^\W*(?:(?:ок(?:ей)?|хорошо|да|ладно|понял|вот|держи|лови|всё|все|ok(?:ay)?|yes|sure|here)[\s,.!]+)?(?:уже\s+)?(?:отправил|отправлено|"
                     r"скинул|переслал|поставил|удалил|сохранил|написал\s+(?:ему|ей|им)|сделал|готово|сделано|добавил|зашёл|зашел|"
                     r"вступил|done|sent|saved|deleted|added|joined|yubordim|qildim)\b", re.I)


def overreach(them: str, draft: str, known_today: str = "", heard: str = "") -> str | None:
    """-> 'commitment' (agreeing to come/meet/bring/help), 'claim' (yes/no about what you did) or 'situation'
    (details about where you are / what you ordered / when you arrive that nobody gave the account) — or None."""
    text = draft.lower()
    if DONE_RE.match(text) and not known_today:
        return "claim"
    # a whole reply that is one past-tense verb about yourself ("Открыл", "Купил", "Пришёл") reports something you did
    if not known_today and re.fullmatch(r"\W*(?:уже\s+|да,?\s+|я\s+)?(?:не\s+)?[а-яё]{2,}(?:ил|ал|ыл|ел|ул|ял|[её]л|ёс|ес)(?:ся)?\W*", text) \
            and not re.search(r"\b(понял|узнал|слышал|видел|знал|думал|забыл|устал|нравил\w*|хотел)\b", text):
        return "claim"
    if re.fullmatch(r"\W*(держи|лови|вот|here|take\s+it)\W*", text) and not known_today:
        return "claim"  # handing over something that isn't there
    if not known_today and (DID_RE.search(them) or STATE_Q_RE.search(them)) and not CRUDE_RE.search(them) and re.match(
            r"^\W*(ещё\s+нет|еще\s+нет|пока\s+нет|да|нет|уже|ага|угу|yes|yeah|no|nope|not\s+yet|ha|yo['ʻ‘’]?q)\b"
            r"(?!\W*(не\s+знаю|не\s+помню|наверн\w*|вроде|может|idk))", text) \
            and not re.search(r"\b(понял|поняла|слышал|слышала|знал|знала|видел|видела|заметил|помнишь)\W*$", them.strip(), re.I):
        return "claim"  # "ещё нет, позвоню позже"
    if UNSURE_RE.search(text):
        return None  # already non-committal
    if PAY_RE.search(text) and (AMOUNT_RE.search(text) or MONEY_WORD_RE.search(text) or re.search(r"\d", text)):
        return "commitment"  # "50 tashay", "скину 20к"
    if RELAY_RE.search(them) and RELAY_OK_RE.search(text):
        return None  # "tell your dad…" → "ok, I'll tell him" is fine
    if PLAN_RE.search(them) and (COMMIT_RE.search(text) or AFFIRM_RE.match(text) or SOON_RE.fullmatch(text)):
        return "commitment"
    if FLAT_PROMISE_RE.search(text) and not known_today:
        return "commitment"
    if (DID_RE.search(them) or STATE_Q_RE.search(them) or UZ_Q_RE.search(them)) and not known_today and not CRUDE_RE.search(them) \
            and not re.search(r"\b(понял|поняла|слышал|слышала|знал|знала|видел|видела|заметил|помнишь)\W*$", them.strip(), re.I):
        # "yes"/"no", or the question's own word handed back as the answer ("ты сделал?" — "сделал", "дома?" — "дома")
        first = re.match(r"\W*([^\W\d_]+)", text)
        asked = set(re.findall(r"[^\W\d_]{3,}", them.lower())) - {"ты", "вы", "это", "что", "как", "the", "you"}
        uzbek_q = UZ_Q_RE.search(them) or re.search(r"\w(dingmi|дингми|ganmisan|ганмисан)\b", them, re.I)
        if CLAIM_RE.match(text) or re.match(r"\W*ok\W*$", text) and UZ_Q_RE.search(them) \
                or uzbek_q and re.search(r"\b\w{2,}(dim|madim|дим|мадим|ganman|ганман)\b", text) \
                or (first and first.group(1) in asked and "?" in them):
            return "claim"
    if not known_today and C.GROUNDED:
        if WHERE_I_AM_RE.search(text):
            return "situation"
        digits = lambda s: set(re.findall(r"\d+", s))
        if AMOUNT_RE.search(text) and "?" not in them and not (digits(text) & digits(them)):
            return "situation"  # a sum of money nobody asked about or mentioned
    if not known_today and C.GROUNDED and BOUNCE_RE.match(them.strip()) and re.search(r"\d", text):
        return "situation"  # "у меня 4, а у тебя?" — "тоже 4"
    if C.GROUNDED and made_up(them, draft, known_today, heard):
        return "situation"
    return None


WHERE_Q_RE = re.compile(r"\b(где|куда|gde|kuda)\b|qayer\w*|qatta\w*|\bwhere\b|\bwya\b|\buyda\w*mi\w*|\bдома\s*\?|\bdoma\s*\?", re.I)
DOING_Q_RE = re.compile(r"\b(что|чё|че|чо|чем)\s+(ты\s+)?(дела\w*|занят\w*|занима\w*)|\bch[eo]\s+dela\w+|\bchto\s+dela\w+|\bwyd\b|"
                        r"\bwhat\s+(are\s+|r\s+)?(you|u)\s+doing|\bnima\s+qil\w+", re.I)
ASIDE = {  # nobody says "I don't know" to "where are you" or "what are you doing"
    "where": {"ru": ["а что?", "а чё такое?", "а что случилось?"], "en": ["why?", "why whats up"], "uz": ["nimaga?", "nima bo'ldi?"]},
    "doing": {"ru": ["да ничего", "ничего особо", "да так"], "en": ["nm", "nothing much"], "uz": ["hech narsa", "shunchaki"]},
}


def agrees_late(history, them: str, draft: str, known_today: str = "") -> bool:
    """They asked for something, you put it off or asked back, and now they only add a detail ("на 8 утра", "ну пж",
    "она ждёт"): a draft that agrees now is the same promise."""
    if known_today or "?" in them or len(them.split()) > 3 or UNSURE_RE.search(draft) \
            or re.match(r"\W*(я|мы|ладно|ок|ok|кстати)\b", them, re.I):
        return False
    rest = list(itertools.dropwhile(lambda m: not m.out, history))       # from your last message back
    mine = rest[0].raw_text or "" if rest else ""
    request = next((m.raw_text or "" for m in rest[1:2] if not m.out), "")
    open_ = bool(UNSURE_RE.search(mine)) or mine.rstrip().endswith("?") or mine.lower().strip(" .!") in {
        p for kinds in DODGE.values() for lines in kinds.values() for p in lines}
    return bool(request and PLAN_RE.search(request) and open_
                and (COMMIT_RE.search(draft.lower()) or AFFIRM_RE.match(draft.lower())))


def dodge(kind: str, language: str | None, them: str = "") -> str:
    last = them.strip().splitlines()[-1] if them.strip() else ""
    aside = "where" if WHERE_Q_RE.search(last) else "doing" if DOING_Q_RE.search(last) else None
    if not aside and kind == "situation" and 0 < len(last.split()) <= 2:
        aside = "where"  # "а щас", "С кем": "ща гляну" would answer nothing
    if aside == "where" and kind in ("situation", "claim") or aside and kind == "situation":
        return random.choice(ASIDE[aside].get(language or "ru") or ASIDE[aside]["ru"])
    return random.choice(DODGE[kind].get(language or "ru") or DODGE[kind]["ru"])
