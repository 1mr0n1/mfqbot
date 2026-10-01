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
REACTIONS = ["👍", "❤"]  # the only reactions the account uses


def _closer_kind(text: str) -> str | None:
    """-> 'thanks' | 'bye' | 'ack' | 'laugh' | 'emoji' if the whole message is just that, else None."""
    text = text.strip()
    if "?" in text:
        return None  # "?" / "??" means "hello, answer me", not "bye"
    if not text or EMOJI_ONLY_RE.match(text):
        return "emoji"
    words = [w for w in re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*", text.lower()) if w not in VOCATIVE]
    if "?" in text or len(words) > 6:
        return None
    if not words:
        return "ack"
    if all(LAUGH_RE.match(w) for w in words):
        return "laugh"
    if not all(w in ACK_WORDS or w in THANKS_WORDS or w in BYE_WORDS or LAUGH_RE.match(w) for w in words):
        return None
    if any(w in BYE_WORDS for w in words) and not all(w in ACK_WORDS for w in words):
        return "bye"
    if any(w in THANKS_WORDS for w in words):
        return "thanks"
    return "ack"


def closer_action(history) -> str | None:
    """-> 'react:<emoji>' or None (= answer normally). Only when they're closing after YOUR message.

    Someone wrapping up ("ok", "спасибо", "пока", "спокойной ночи") gets a reaction instead of more text."""
    unanswered = list(itertools.takewhile(lambda m: not m.out, history))
    if not unanswered or len(unanswered) > 3:
        return None  # nothing new, or a real burst
    kinds = []
    for msg in unanswered:
        if msg.photo or msg.voice or msg.video or msg.video_note or (msg.document and not msg.sticker):
            return None
        kind = "emoji" if msg.sticker else _closer_kind(msg.raw_text or "")
        if not kind:
            return None
        kinds.append(kind)
    if "thanks" in kinds or "bye" in kinds:
        return "react:❤" if "thanks" in kinds or random.random() < 0.4 else "react:👍"
    return "react:👍"


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
STRONG = [
    ("a verification code or password",
     r"\b(otp|password|passcode)\b|парол\w*|\bparol\w*"
     r"|(sms|смс|verification|login|confirm\w*|подтвержд\w*|tasdiq\w*)\W+(\w+\W+){0,3}(code|код|kod)\b"
     r"|\b(code|код|kod)\b\W+(\w+\W+){0,3}(sms|смс|пришл\w*|прислал\w*|отправ\w*|скин\w*|keldi|yubor\w*|ayt\w*|came|sent)"),
    ("money", r"\b(lend|borrow|loan|owe|debt|pay me|send me \$?\d|transfer|cash ?app|paypal)\b|\$\s?\d{2,}|\d{2,}\s?(\$|usd|сум|sum|so'm|som|руб|k\b|к\b)"
              r"|\bзаня(ть|л|ла)\b|\bзайм\w*|\bдолж(ен|на|ок)\b"
              r"|в\s*долг|одолжи\w*|займи\w*|перевед\w*|скинь\s+(деньг|на карт)|на карту|деньг\w*|\bqarz\w*|\bpul\w*\s+(ber|kerak|tashla|o'tkaz)|kartaga"),
    ("an emergency", r"\b(emergency|hospital|ambulance|accident|police|urgent(ly)?|asap|died|passed away)\b|срочно|больниц\w*|скор(ая|ую)"
                     r"|авари\w*|полици\w*|умер(ла)?|kasalxona\w*|tez yordam|avariya|vafot|zudlik|shoshilinch"),
]
CLASSIFY = (
    "Below are the latest messages someone sent to their friend or relative {name} in a private chat. Decide whether "
    "{name} must answer PERSONALLY. Answer PERSONAL only for something clearly serious: the person is in real distress "
    "(crying, panicking, saying they are deeply hurt), a serious fight or breaking off contact, romantic or relationship "
    "talk, illness, injury, death or other bad news, trouble with police, school administration or the law.\n"
    "Everything else is NORMAL — including teasing, banter, jokes, mild complaints or reproaches ('you didn't reply', "
    "'you didn't do it'), embarrassing or silly stories, everyday plans and logistics, favors, questions, greetings. "
    "When in doubt, answer NORMAL.\n"
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
    if keywords_only or len(joined.split()) < 4:
        return None  # too short to be worth a model call
    try:
        resp = await http.post("/complete", json={
            "messages": [{"role": "user", "content": CLASSIFY.format(name=name, messages=joined[:1500])}],
            "models": C.MODELS, "max_tokens": 30, "temperature": 0})
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
WORD_CHECK = ("For each word below say whether it is a real word in Russian, English or Uzbek — including slang, "
              "informal spellings, names, brands and game or app names. Answer one per line as word=YES or word=NO.\n{words}")
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


VOWELS = set("аеёиоуыэюяaeiouy'ʻ‘’")


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
            and len(_norm(text).split()) >= 2:
        return "it repeats their message"
    their_lang, draft_lang = lang.base(lang.detect(them)), lang.base(lang.detect(text))
    known = {"uz", "ru", "en"}
    if expected is None and their_lang in known and draft_lang in known and their_lang != draft_lang \
            and len(them.split()) >= 2 and len(text.split()) >= 2:
        return f"wrong language ({draft_lang} instead of {their_lang})"
    odd = foreign_word(them, text)
    if odd:
        return f"strange word '{odd}'"
    # they wrote in Cyrillic, the draft has no Cyrillic at all and isn't just a word or two (a name, "ok", a translation)
    if expected is None and re.search("[а-яё]", them, re.I) and not re.search("[а-яё]", text, re.I) \
            and len(re.findall(r"[A-Za-z]{2,}", text)) >= 3 \
            and not all(w[0].isupper() or len(w) < 3 for w in re.findall(r"[A-Za-z]{2,}", text)):
        return "wrong language (Latin letters instead of Russian)"
    suspects = unknown_words(them, text)
    if suspects:
        return f"nonsense word '{suspects[0]}'"
    return None


# ---------- things the account must not decide or claim on its own ----------
PLAN_RE = re.compile(
    r"\bго\b|пойд[её]шь|ид[её]шь|прид[её]шь|зайд[её]шь|приедешь|встрет\w*|давай\s+(в|на|завтра|сегодня|после)|поможешь|принес\w*|"
    r"отдашь|ждём|ждем|выходи|подойд[её]шь|во\s+сколько|"
    r"\b(wanna|coming|come\s+(over|to)|meet|bring|let'?s)\b|kelasan\w*|borasan\w*|chiqasan\w*|uchrash\w*|olib\s+kel", re.I)
COMMIT_RE = re.compile(
    r"\b(приду|буду|выйду|зайду|подойду|приеду|принесу|отдам|помогу|скину|сделаю|договорились|"
    r"го|погнали|заходи|выхожу|иду|еду)\b|\bв\s+\d{1,2}([:.]\d\d)?\b|\b(давай|ок|окей|хорошо|да|конечно)\b[\s,]+\b(приду|буду|зайду|го|давай|помогу)\b|"
    r"\b(i'?ll\s+(come|be|bring|help)|coming|on\s+my\s+way|let'?s\s+go|sure\s+let'?s|yeah\s+let'?s|im\s+down)\b|"
    r"\b(kelaman|boraman|chiqaman|olib\s+kelaman|xop\s+kelaman)\b", re.I)
DID_RE = re.compile(
    r"\b(сделал\w*|сдал\w*|прив[её]з(ла|ли)?|прин[её]с(ла|ли)?|подготовил\w*|написал\w*|выучил\w*|поел\w*|покушал\w*|кушал\w*|"
    r"взял\w*|купил\w*|забрал\w*|был\w*\s+(на|в|у)|ходил\w*|почему\s+(тебя|вас)\s+не\s+было)\b|"
    r"\bdid\s+(u|you)\b|\bhave\s+(u|you)\b|yedingmi|qildingmi|bordingmi|oldingmi|keldingmi|yozdingmi", re.I)
CLAIM_RE = re.compile(r"^\W*(да|нет|не|неа|ага|угу|yes|yeah|yep|no|nope|nah|ha|yo'?q|xa|йўқ|ҳа)\b", re.I)
AFFIRM_RE = re.compile(r"^\W*(да|ага|угу|ок|окей|оке\w*|хорошо|конечно|давай|го|погнали|sure|yeah|yes|yep|ok|okay|bet|"
                       r"mayli|xop|ha)\b", re.I)
UNSURE_RE = re.compile(r"не\s+знаю|не\s+помню|не\s+уверен|посмотр|может|хз|потом|позже|idk|not\s+sure|maybe|later|dunno|"
                       r"bilma|keyin", re.I)
DODGE = {
    "commitment": {"ru": ["не знаю ещё", "посмотрим", "не знаю, напишу", "пока не знаю"], "en": ["idk yet", "not sure yet", "will lyk"],
                   "uz": ["bilmasam", "hali bilmayman", "keyin aytaman"]},
    "claim": {"ru": ["потом скажу", "потом расскажу"], "en": ["tell u later"], "uz": ["keyin aytaman"]},
}


def overreach(them: str, draft: str, known_today: str = "") -> str | None:
    """-> 'commitment' (agreeing to come/meet/bring/help) or 'claim' (yes/no about what you did) — or None."""
    text = draft.lower()
    if UNSURE_RE.search(text):
        return None  # already non-committal
    if PLAN_RE.search(them) and (COMMIT_RE.search(text) or AFFIRM_RE.match(text)):
        return "commitment"
    if DID_RE.search(them) and CLAIM_RE.match(text) and not known_today:
        return "claim"
    return None


def dodge(kind: str, language: str | None) -> str:
    return random.choice(DODGE[kind].get(language or "ru") or DODGE[kind]["ru"])
