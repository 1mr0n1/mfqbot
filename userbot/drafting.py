"""Writing a draft: the examples of how you text that go into the prompt, and the call to the model."""
from collections import Counter
import base64
import itertools
import json
import random
import re
from datetime import datetime
import httpx
from telethon.tl.types import User
from . import config as C
from . import judge, lang, media, memory, punct, recall, rhythm
from . import trace
from . import app
from .app import full_name, http, log, to_chat_messages


persona = C.PERSONA_PATH.read_text()


HOLDOUT: set[str] = set()  # replies hidden from the examples (the simulator's answer key); empty in production


def holdout_key(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


def visible(items: list, text_of) -> list:
    if not HOLDOUT:
        return items
    return [i for i in items if not any(holdout_key(line) in HOLDOUT for line in text_of(i).splitlines())]


def _prefer(items: list, wanted, key, count: int) -> list:
    """Up to `count` random items, taking the ones where key(item) == wanted first."""
    matching = [i for i in items if key(i) == wanted] if wanted else []
    others = [i for i in items if i not in matching]
    picks = random.sample(matching, min(count, len(matching)))
    return picks + random.sample(others, min(count - len(picks), len(others)))


def contact_style_path(contact: User):
    """Per-person style file (see import_contact.py), or None if this person has none."""
    folder = C.STYLE_DIR / "contacts"
    if contact.username and (folder / f"{contact.username.lower()}.json").exists():
        return folder / f"{contact.username.lower()}.json"
    # someone without a @username is found by their name in your Telegram: contacts/_<name>.json
    name = "_".join(" ".join(x for x in (contact.first_name, contact.last_name) if x).lower().split())
    path = folder / f"_{name}.json"
    return path if name and path.exists() else None


FORCE_LANG: dict[str, str] = {}  # style file -> language for the next draft (set when an Uzbek draft was rejected)


def contact_style_block(path, incoming: str) -> str:
    """Style for one specific person, built only from your real chat with them."""
    data = json.loads(path.read_text())
    data["pairs"] = visible(data["pairs"], lambda p: p["me"])
    data["examples"] = visible(data["examples"], lambda m: m)
    st, wanted = data["stats"], lang.base(lang.detect(incoming))
    turns = ", ".join(f"{k} message(s) in a row {v}%" for k, v in st.get("messages_per_turn_pct", {}).items())
    block = (
        f"You are talking to {data['name']} — someone you know very well. Write to them ONLY the way your real "
        "messages to them below show: same languages, same words and forms of address, same politeness, same "
        "length. Do not use slang, greetings or jokes that don't appear in these examples.\n"
        f"Facts from your real chat with them: languages you use (share of your messages): {st.get('languages_pct')}; "
        f"typical message is about {st['length_chars']['median']} characters; {turns}; "
        f"emoji in {st.get('with_emoji_pct', 0)}% of messages"
        + (f" (mostly {' '.join(st['top_emojis'][:5])})" if st.get("top_emojis") else "") + ".\n"
    )
    # Pick ONE reply language in code — the one you most often answer in when they write in this language —
    # and show only examples in it. Mixed-language examples make the model produce mixed-up text.
    relevant = [p for p in data["pairs"] if p.get("them_lang") == wanted and p.get("lang")] or \
               [p for p in data["pairs"] if p.get("lang")]
    # Which language do you answer in when they write like this? Not always the same one: pick with the same odds
    # as in your real chat (with your mom, Russian about as often as Uzbek) — unless one is forced for a rewrite.
    odds = Counter(p["lang"] for p in relevant if p["lang"] in ("ru", "uz", "en"))
    real = {k: v for k, v in odds.items() if k != "en" or v > sum(odds.values()) * 0.5}  # "ok"/"da" look English
    reply_lang = (FORCE_LANG.pop(str(path), None)
                  or (random.choices(list(real), weights=list(real.values()))[0] if real else wanted))
    in_lang = [m for m in data["examples"] if lang.base(lang.detect(m)) == reply_lang] or data["examples"]
    examples = random.sample(in_lang, min(C.STYLE_EXAMPLES, len(in_lang)))
    block += "\nReal messages you sent them:\n" + "\n".join(f"- {m.replace(chr(10), ' / ')}" for m in examples) + "\n"
    recalled, used = recall.block(recall.index_for((str(path), path.stat().st_mtime), data["pairs"]),
                                  incoming, C.RECALL_PAIRS)
    same = [p for p in relevant if p["lang"] == reply_lang and p not in used]
    pairs = random.sample(same, min(C.CONTACT_PAIRS, len(same)))
    if pairs:
        block += ("\nReal exchanges with them — what they wrote and what you actually answered "
                  "(copy the manner and the language choice, never the content):\n"
                  + "\n".join(f"THEM: {p['them'].replace(chr(10), ' / ')}\nYOU: {p['me'].replace(chr(10), ' / ')}"
                              for p in pairs) + "\n")
    block += recalled
    name = {"uz": "Uzbek (Latin letters, exactly the everyday forms shown above)", "ru": "Russian",
            "en": "English"}.get(reply_lang, "the language of the examples above")
    block += (f"\nLanguage note: write your whole reply in {name}. Use only words and forms that appear in your "
              "real messages above; if unsure, answer with something very short.\n")
    return block


def style_stats(contact: User) -> dict:
    """Your measured habits (lengths, punctuation): with this person if they have a style file, else in general."""
    try:
        path = contact_style_path(contact)
        return json.loads(path.read_text())["stats"] if path else json.loads((C.STYLE_DIR / "stats.json").read_text())
    except (OSError, ValueError, KeyError):
        return {}


def punct_profile(contact: User) -> dict:
    return style_stats(contact).get("punct") or punct.DEFAULT


def style_block(contact_name: str = "", incoming: str = "", contact: User | None = None) -> str:
    """Learned style (see learn_style.py). Re-read every time so re-learning needs no restart."""
    path = contact_style_path(contact) if contact else None
    if path:
        return contact_style_block(path, incoming)
    profile_path = C.STYLE_DIR / "profile.md"
    examples_path, pairs_path = C.STYLE_DIR / "examples.json", C.STYLE_DIR / "pairs.json"
    if not profile_path.exists():
        return ""
    code = lang.detect(incoming)
    wanted = lang.base(code)
    block = f"How {full_name(app.me)} texts — follow this closely, it matters more than the generic rules above:\n"
    block += profile_path.read_text().strip() + "\n"
    if examples_path.exists():
        examples = visible(json.loads(examples_path.read_text()), lambda m: m)
        # Mostly messages in the language of this conversation, so the right register gets copied.
        picks = _prefer(examples, wanted, lambda m: lang.base(lang.detect(m)), C.STYLE_EXAMPLES)
        block += ("\nReal messages they've sent (for style only — don't reuse their content):\n"
                  + "\n".join(f"- {m.replace(chr(10), ' / ')}" for m in picks) + "\n")
    if pairs_path.exists():
        pairs = visible(json.loads(pairs_path.read_text()), lambda p: p["me"])
        recalled, used = recall.block(recall.index_for((str(pairs_path), pairs_path.stat().st_mtime), pairs),
                                      incoming, C.RECALL_PAIRS)
        rest = [p for p in pairs if p not in used]
        picks = _prefer(rest, wanted, lambda p: lang.base(p.get("lang")), C.STYLE_PAIRS)
        if picks:
            block += ("\nReal exchanges — what someone wrote and what they actually answered "
                      "(copy the manner, never the content):\n"
                      + "\n".join(f"THEM: {p['them'].replace(chr(10), ' / ')}\nYOU: {p['me'].replace(chr(10), ' / ')}"
                                  for p in picks) + "\n")
        block += recalled
    if code:
        block += (f"\nLanguage note: their latest message is in {lang.NAMES[code]}. Write your whole reply in "
                  "that language and script.\n")
    return block


PHOTO_HINT = ("\nThe other person sent you photo(s) — they are attached to their last message and you can see "
              "them. React to what is actually in the picture (name something specific you see), in your usual "
              "short style. Never repeat their own words back to them.\n")


async def attach_photos(history, messages: list[dict]) -> int:
    """Give the model the newest photos the other person sent since your last message. Returns how many."""
    photos = []
    for msg in history:  # newest first
        if msg.out:
            break
        if msg.photo:
            photos.append(msg)
    parts = [{"type": "text", "text": messages[-1]["content"]}]
    for msg in reversed(photos[:C.MAX_IMAGES]):
        try:
            data = await msg.download_media(file=bytes)
        except Exception:
            log.exception("Could not download photo")
            continue
        if data and len(data) <= 4_000_000:
            parts.append({"type": "image_url",
                          "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(data).decode()}})
    if len(parts) > 1:
        messages[-1]["content"] = parts
        log.info("Attached %d photo(s) for the model", len(parts) - 1)
    return len(parts) - 1


async def generate(history, contact: User, extra: str = "") -> str | None:
    messages = to_chat_messages(history)
    if not messages or messages[-1]["role"] != "user":
        return ""  # nothing to answer (None means the backend failed)
    photos = await attach_photos(history, messages) if C.VISION else 0
    incoming = " ".join(m.raw_text for m in itertools.takewhile(lambda m: not m.out, history) if m.raw_text)
    if len(incoming.split()) < 3:  # "ok", an emoji, a photo: go by how this person has been writing lately
        incoming = " ".join([m.raw_text for m in history if not m.out and m.raw_text][:8])
    system = persona.format(name=app.me.first_name or full_name(app.me), contact=full_name(contact),
                            style=style_block(full_name(contact), incoming, contact),
                            now=datetime.now().strftime("%A %d %B %Y, %H:%M"),
                            status=rhythm.status())
    if not contact_style_path(contact):
        system += media.media_block(full_name(app.me))
    if photos:
        system += PHOTO_HINT
    system += memory.facts_block(full_name(app.me)) + memory.notes_block(contact.id, full_name(contact))
    if C.SMART_SKIP:
        system += judge.REACT_HINT
    system += extra  # what just happened outside the conversation (e.g. a profile photo change)
    try:
        body = {"messages": messages, "system": system, "max_tokens": 200, "temperature": C.TEMPERATURE,
                "models": C.PHOTO_MODELS if photos else C.MODELS}
        if not photos:
            body["hedge_after"] = C.HEDGE_AFTER  # the second model joins if the first is slow or rate-limited
        resp = await http.post("/complete", json=body)
    except httpx.HTTPError as e:
        log.warning("Backend unreachable: %r", e)
        return None
    if resp.is_error:
        log.warning("Backend error %s: %s", resp.status_code, resp.text[:200])
        return None
    data = resp.json()
    log.info("Reply generated by %s", data["model"])
    trace.emit("decision", full_name(contact),
               f"Model used: {data['model']}" + (f" — looked at {photos} photo(s)" if photos else ""))
    return data["reply"]
