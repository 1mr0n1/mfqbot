"""Teaching the account by talking to it.

From your other account (USERBOT_COMMANDERS) you tell it how to behave, in your own words:

  запомни: маме всегда отвечай на вы            a rule (also: "правило: …", "remember: …")
  если мама спрашивает кто на фото, отвечай: это мой друг      an "if … then answer …" rule
  никогда не пиши «хорошо, спасибо»              "never …" / "always …" / "не пиши …" work too
  правила                                         show what it has been taught
  забудь правило 3                                remove one

And without saying anything: when you edit a draft on the dashboard before it is sent, the account keeps
"they wrote this → you changed my reply to that" as an example of how you would have answered.

Rules and corrections go into every prompt, above the style examples. Kept in userbot/lessons.json (git-ignored).
"""
import json
import re
import time

from . import config as C

PATH = C.HERE / "lessons.json"
MAX_RULES, MAX_FIXES = 60, 40

RULE_RE = re.compile(
    r"^\W*(?:запомни|правило|урок|учти|remember|rule|lesson|eslab\s+qol)\s*[:,\-—]?\s+(?P<a>.{6,})$"
    r"|^\W*(?P<b>(?:если|когда|if|when|agar)\s+.{4,}?\b(?:отвеч\w+|ответь|говори\w*|скажи\w*|пиши\w*|напиши\w*|answer|say|reply|"
    r"write|ayt\w*|yoz\w*)\b.{2,})$"
    r"|^\W*(?P<c>(?:никогда\s+не|всегда|не\s+(?:пиши|говори|отвечай|используй|ставь|спрашивай|называй)|never|always|"
    r"don'?t\s+(?:say|write|use|ask|call)|hech\s+qachon|doim)\s+.{4,})$", re.I | re.S)
LIST_RE = re.compile(r"^\W*(?:покажи\s+)?(?:правила|уроки|что\s+ты\s+запомнил|rules|lessons)\W*$", re.I)
FORGET_RE = re.compile(r"^\W*(?:забудь|удали|убери|forget|remove|delete)\s+(?:правило|урок|rule|lesson)\s*№?\s*(\d+)\W*$", re.I)


def _load() -> dict:
    try:
        return json.loads(PATH.read_text())
    except (OSError, ValueError):
        return {"rules": [], "fixes": []}


def _save(data: dict):
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1))


def rules() -> list[str]:
    return [r["text"] for r in _load()["rules"]]


def parse(text: str) -> tuple[str, str] | None:
    """-> ("add", rule) | ("list", "") | ("forget", number) if the message is teaching, else None."""
    text = (text or "").strip()
    if not text or len(text) > 500:
        return None
    if LIST_RE.match(text):
        return "list", ""
    forget = FORGET_RE.match(text)
    if forget:
        return "forget", forget.group(1)
    match = RULE_RE.match(text)
    if match:
        return "add", (match.group("a") or match.group("b") or match.group("c")).strip()
    return None


def add_rule(text: str) -> int:
    data = _load()
    if not any(r["text"].lower() == text.lower() for r in data["rules"]):
        data["rules"] = (data["rules"] + [{"text": text[:400], "date": time.strftime("%Y-%m-%d")}])[-MAX_RULES:]
        _save(data)
    return next(i for i, r in enumerate(data["rules"], 1) if r["text"].lower() == text.lower()[:400])


def forget_rule(number: int) -> str | None:
    data = _load()
    if not 1 <= number <= len(data["rules"]):
        return None
    gone = data["rules"].pop(number - 1)
    _save(data)
    return gone["text"]


def add_fix(them: str, draft: str, yours: str):
    """You rewrote a draft on the dashboard: that is how you would have answered."""
    them, draft, yours = them.strip()[:300], draft.strip()[:300], yours.strip()[:300]
    if not yours or yours == draft:
        return
    data = _load()
    data["fixes"] = (data["fixes"] + [{"them": them, "draft": draft, "yours": yours, "date": time.strftime("%Y-%m-%d")}])[-MAX_FIXES:]
    _save(data)


def block() -> str:
    """What goes into the prompt."""
    data = _load()
    out = ""
    if data["rules"]:
        out += ("\nRules you set for yourself. They come before everything about style, and they apply whenever the "
                "situation they describe comes up:\n" + "\n".join(f"- {r['text']}" for r in data["rules"]) + "\n")
    if data["fixes"]:
        out += ("\nReplies of yours that you corrected by hand — answer like the corrected version in similar "
                "situations:\n" + "\n".join(
                    f"THEM: {f['them'] or '(a message)'}\nNOT: {f['draft']}\nYOU: {f['yours']}" for f in data["fixes"][-12:]) + "\n")
    return out
