"""Photos through the real reply flow (real vision model, fake Telegram): can it read what is in a picture?

  PYTHONPATH=. .venv/bin/python tests/photos.py        (the backend must be running)

The pictures are drawn here: text on a plain background (a homework problem, a schedule, a chat screenshot, a
price tag, a meme caption) and simple shapes — enough to tell whether the picture was actually looked at.
"""
import asyncio
import io

from PIL import Image, ImageDraw, ImageFont
from telethon.tl.types import User

from userbot import simulate as SIM
from userbot import app, config as C, replies, trace


def font(size):
    for path in ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/System/Library/Fonts/Helvetica.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def text_image(lines, size=(640, 360), bg=(255, 255, 255), fg=(20, 20, 20), big=44) -> bytes:
    image = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(image)
    y = 30
    for line in lines:
        draw.text((30, y), line, fill=fg, font=font(big))
        y += big + 16
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def shapes() -> bytes:
    image = Image.new("RGB", (480, 320), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 60, 200, 220), fill=(220, 30, 30))
    draw.rectangle((260, 60, 440, 220), fill=(30, 60, 220))
    buf = io.BytesIO()
    image.save(buf, "JPEG")
    return buf.getvalue()


CASES = [  # (name, picture, what they write with it, words one of which must be in the reply)
    ("a maths problem", text_image(["Решите уравнение:", "2x + 5 = 15"]), "помоги решить", ["5", "пять"]),
    ("a timetable", text_image(["Понедельник", "1. Алгебра", "2. Биология", "3. Физ-ра"], big=38), "какой второй урок?", ["биолог"]),
    ("a price tag", text_image(["Кроссовки Nike", "Цена: 850 000 сум"]), "сколько стоят?", ["850"]),
    ("a chat screenshot", text_image(["Тимур: го в кино в 7?", "Азиз: я не могу"], big=36), "кто не может пойти?", ["азиз"]),
    ("two shapes", shapes(), "что на картинке? какого цвета круг?", ["красн", "red"]),
    ("a meme caption", text_image(["Когда сказал", "«я только посмотрю»", "а уже 3 часа ночи"], bg=(20, 20, 20), fg=(255, 255, 255), big=40), "жиза?", None),
    ("a photo with no question", shapes(), "", None),
    ("English text", text_image(["Meeting moved", "to Friday 5 PM"]), "when is it?", ["friday", "5", "пятниц"]),
]


async def main():
    fake = SIM.FakeClient(); app.client = fake
    app.me = User(id=1, first_name="Kamron")
    events = []
    trace.emit = lambda kind, chat="", text="", **d: events.append(text)

    async def never(d): return False
    async def nothing(d): return {}
    trace.draft_cancelled, trace.draft_state = never, nothing
    C.VISION = True
    good = 0
    for n, (name, data, caption, expect) in enumerate(CASES):
        chat_id = 800 + n
        msg = SIM.make(caption, photo=True)

        async def download(file=None, thumb=None, data=data):
            return data
        msg.download_media = download
        fake.histories[chat_id] = [msg, SIM.make("привет", out=True)]
        events.clear()
        await asyncio.wait_for(replies.reply_flow(chat_id, User(id=chat_id, first_name="Timur", contact=True)), 120)
        sent = fake.sent.get(chat_id, [])
        looked = any("looked at 1 photo" in e for e in events)
        text = " ".join(sent).lower()
        ok = looked and bool(sent) and (expect is None or any(word in text for word in expect))
        good += ok
        print(("ok    " if ok else "FAIL  ") + f"{name}: “{caption}” → {' / '.join(sent) or '(nothing)'}"
              + ("" if looked else "   [no model looked at the photo]"), flush=True)
    await app.http.aclose()
    print(f"\n{good} of {len(CASES)} photo checks passed")

asyncio.run(main())
