"""Common orders, understood by fixed rules instead of a model.

"заблокируй Тимура", "напиши маме: буду в 6", "замуть класс на 8 часов", "отправь голосовое смех в Др" — these
have one obvious meaning, and a model reading them is one more thing that can go wrong (it has sent the order
itself as the message, searched the internet for a photo it was handed, deleted the wrong picture). So the orders
people actually give are recognised here and turned straight into the steps to run. Anything that does not match
one of these shapes exactly goes to the model as before.

A plan is a list of (tool, args) for pilot.py; the same checks apply to it as to the model's steps (a "yes" for
things that can't be undone, the limits on sending).
"""
import re

WHO = r"(?P<who>[^,:\"«»“”]+?)"   # a name: up to the comma, the colon or the quote
TEXT = r"[\"«“](?P<text>[^\"«»“”]+)[\"»”]|(?P<text2>.+)"
THIRD = re.compile(r"\b(он|она|они|его|её|ее|ему|ей|им|их|него|неё|нее|ним|ней|them|him|her|his|their|he|she)\b", re.I)
HERE = re.compile(r"^(?:сюда|тут|здесь|в\s+этот\s+чат|here|this\s+chat)$", re.I)


def _clean(who: str) -> str:
    who = re.sub(r"^(?:чат[еу]?\s+с\s+|контакт[ау]?\s+|пользовател[яю]\s+|группу\s+|группе\s+|канал[еу]?\s+|в\s+|to\s+|the\s+)", "",
                 who.strip(), flags=re.I).strip()
    who = re.sub(r"\s+(?:групп[ыуе]|чата?|канала?|group|chat|channel)$", "", who, flags=re.I).strip() or who
    return "here" if HERE.match(who) else who


def _hours(text: str | None) -> float:
    if not text:
        return 0
    n = float(re.search(r"\d+(?:[.,]\d+)?", text).group(0).replace(",", "."))
    return n * 24 if re.search(r"д[ен]|day", text, re.I) else n / 60 if re.search(r"мин|min", text, re.I) else n


RULES = []  # (pattern, function(match) -> plan or None)


def rule(pattern: str):
    def register(fn):
        RULES.append((re.compile(r"^\W*(?:(?:бот|слушай|ну|а|давай|пж|пожалуйста|please|pls)[\s,]+)*" + pattern + r"\W*$", re.I | re.S), fn))
        return fn
    return register


@rule(r"(?:напиши|отпиши|отправь|скажи|передай|write|send|tell|text)\s+" + WHO + r"\s*(?::|,?\s+что\s+|,\s*)\s*(?:" + TEXT + ")")
def _say(m):
    text = (m.group("text") or m.group("text2") or "").strip()
    who = _clean(m.group("who"))
    if not text or len(who.split()) > 3 or (m.group("text") is None and THIRD.search(text)):
        return None  # "скажи маме что я её люблю" needs rewording ("тебя"): the model's job
    if re.match(r"(?:голосов|войс|voice|стикер|sticker|гиф|gif|фото|картинк|ссылк)", who, re.I):
        return None
    return [("send_message", {"chat": who, "text": text})]


@rule(r"(?:напиши|отпиши|отправь|скажи|write|send|tell|text)\s+(?P<who>[^\s,:\"«»“”]+)\s+(?P<text2>[^:].*)")
def _say_plain(m):
    """ "напиши Тимуру привет": the first word is the person — if a chat by that name exists (pilot checks)."""
    text, who = m.group("text2").strip().strip('"«»“”'), m.group("who")
    if THIRD.search(text) or re.match(r"(?:что|чтобы|that|to)\b", text, re.I) or len(text) > 200 \
            or re.match(r"(?:голосов|войс|voice|стикер|sticker|гиф|gif|фото|картинк|ссылк|привет|всем|мне|me|это|this)", who, re.I):
        return None
    return [("send_message", {"chat": who, "text": text})]


@rule(r"(?:заблокируй|заблочь|забань|block|ban)\s+" + WHO)
def _block(m):
    return [("block", {"user": _clean(m.group("who"))})]


@rule(r"(?:разблокируй|разблочь|разбань|unblock|unban)\s+" + WHO)
def _unblock(m):
    return [("unblock", {"user": _clean(m.group("who"))})]


@rule(r"(?:замуть|заглуши|mute|выключи\s+(?:уведомления|звук)\s+(?:в|у|от|для)?)\s*" + WHO +
      r"(?:\s+(?:на|for)\s+(?P<span>\d+(?:[.,]\d+)?\s*(?:час\w*|ч\b|h\w*|мин\w*|min\w*|д[ен]\w*|day\w*)))?")
def _mute(m):
    return [("mute", {"chat": _clean(m.group("who")), "hours": _hours(m.group("span"))})]


@rule(r"(?:размуть|unmute|включи\s+(?:уведомления|звук)\s+(?:в|у|от|для)?)\s*" + WHO)
def _unmute(m):
    return [("unmute", {"chat": _clean(m.group("who"))})]


@rule(r"(?:заархивируй|архивируй|в\s+архив|archive)\s+" + WHO)
def _archive(m):
    return [("archive", {"chat": _clean(m.group("who")), "on": True})]


@rule(r"(?:разархивируй|достань\s+из\s+архива|верни\s+из\s+архива|unarchive)\s+" + WHO)
def _unarchive(m):
    return [("archive", {"chat": _clean(m.group("who")), "on": False})]


@rule(r"(?:удали|delete)\s+(?:чат|переписку|chat)\s+(?:с[о]?|with)\s+" + WHO)
def _delete_chat(m):
    return [("delete_chat", {"chat": _clean(m.group("who"))})]


@rule(r"(?:очисти|сотри|clear)\s+(?:историю|переписку|history)\s+(?:с[о]?|with|в)\s+" + WHO)
def _clear(m):
    return [("clear_history", {"chat": _clean(m.group("who"))})]


@rule(r"(?:выйди|покинь|ливни|leave)\s+(?:из\s+|с\s+)?(?:группы\s+|чата\s+|канала\s+)?" + WHO)
def _leave(m):
    return [("leave", {"chat": _clean(m.group("who"))})]


@rule(r"(?:отметь|пометь|mark)\s+" + WHO + r"\s+(?:как\s+)?(?:прочитанн\w+|read)")
def _read(m):
    return [("mark_read", {"chat": _clean(m.group("who"))})]


@rule(r"(?:закрепи|pin)\s+(?:это|последнее(?:\s+сообщение)?|this|it)(?:\s+(?:в|in)\s+" + WHO + ")?")
def _pin(m):
    return [("pin_last", {"chat": _clean(m.group("who") or "here")})]


@rule(r"(?:отправь|скинь|кинь|send)\s+(?:голосовое|войс|voice|клип|clip)\s+[\"«“]?(?P<tag>[^\"«»“”]+?)[\"»”]?\s+(?:в|to|кому)\s+" + WHO)
def _voice(m):
    return [("send_voice", {"chat": _clean(m.group("who")), "tag": m.group("tag").strip()})]


@rule(r"(?:отправь|скинь|перешли|send|forward)\s+(?:это|this)\s+(?:голосовое|войс|voice)\s+(?:в|to|кому)\s+" + WHO)
def _this_voice(m):
    return [("send_voice", {"chat": _clean(m.group("who"))})]


@rule(r"(?:перешли|forward)\s+(?:это|последнее(?:\s+сообщение)?|this|it)\s+(?:в\s+|to\s+)?" + WHO)
def _forward(m):
    return [("forward_last", {"from_chat": "here", "to_chat": _clean(m.group("who"))})]


@rule(r"(?:поставь\s+бота\s+на\s+паузу|пауза|останови\s+бота|pause(?:\s+the\s+bot)?)")
def _pause(m):
    return [("bot_pause", {"on": True})]


@rule(r"(?:сними\s+(?:бота\s+)?с\s+паузы|продолжи|включи\s+бота|resume(?:\s+the\s+bot)?)")
def _resume(m):
    return [("bot_pause", {"on": False})]


@rule(r"(?:поменяй|смени|измени|поставь|change|set)\s+(?:моё\s+|мое\s+|my\s+)?(?:био|bio|описание)\s+(?:на|to)?\s*:?\s*(?:" + TEXT + ")")
def _bio(m):
    return [("set_profile", {"bio": (m.group("text") or m.group("text2")).strip()})]


@rule(r"(?:поменяй|смени|измени|поставь|change|set)\s+(?:мо[её]\s+|my\s+)?(?:имя|first\s+name|name)\s+(?:на|to)\s*:?\s*[\"«“]?(?P<name>[^\"«»“”]{1,40}?)[\"»”]?")
def _first_name(m):
    return [("set_profile", {"first_name": m.group("name").strip()})]


@rule(r"(?:поменяй|смени|измени|поставь|change|set)\s+(?:мою\s+|my\s+)?(?:фамилию|last\s+name|surname)\s+(?:на|to)\s*:?\s*[\"«“]?(?P<name>[^\"«»“”]{0,40}?)[\"»”]?")
def _last_name(m):
    return [("set_profile", {"last_name": m.group("name").strip()})]


@rule(r"(?:удали|убери|сними|remove|delete)\s+(?:текущую\s+|current\s+)?(?:аву|аватарку|аватар|фото\s+профиля|pfp|avatar)")
def _avatar_current(m):
    return [("remove_avatar", {"which": "current"})]


@rule(r"(?:удали|убери|remove|delete)\s+(?:предыдущую|прошлую|старую|ту\s+что\s+была(?:\s+до)?|previous|old)\s+(?:аву|аватарку|аватар|pfp|avatar)"
      r"|(?:delete|remove)\s+the\s+(?:pfp|avatar)\s+that\s+was\s+before")
def _avatar_previous(m):
    return [("remove_avatar", {"which": "previous"})]


@rule(r"(?:какие\s+(?:есть\s+)?(?:клипы|голосовые)|список\s+клипов|клипы|clips)")
def _clips(m):
    return [("list_clips", {})]


def plan(order: str) -> list[tuple[str, dict]] | None:
    """-> the steps for this order, if it is one of the common shapes; else None (the model takes it)."""
    order = " ".join((order or "").split())
    if not order or "\n" in order or len(order) > 300:
        return None
    if re.search(r"\s(?:и|потом|затем|а\s+потом|and\s+then|then)\s+(?:напиши|отправь|удали|заблокируй|поставь|закрепи|перешли|замуть|"
                 r"write|send|delete|block|pin|forward|mute)\b", order, re.I):
        return None  # two orders in one sentence: let the model sort out the sequence
    for pattern, fn in RULES:
        match = pattern.match(order)
        if match:
            steps = fn(match)
            if steps:
                return steps
    return None
