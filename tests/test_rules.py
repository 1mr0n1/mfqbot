"""The rules that don't need a model or Telegram: run in a few seconds, before and after every change.

  .venv/bin/python -m unittest discover tests

Each case is (input, expected). The names in here are made up.
"""
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from telethon.tl.types import User

from userbot import simulate as SIM  # noqa: F401  (points state, memory and the day log at a temp folder)
from userbot import app, commands, config as C, groups, judge, lessons, lookup, people, pilot, quirks, replies, trace, wording

trace.emit = lambda *args, **kwargs: None  # nothing is written to the dashboard log from tests

NOW = datetime.now(timezone.utc)


def msg(text="", out=False, age=0, **kw):
    return SIM.make(text, out=out, date=NOW - timedelta(seconds=age), **kw)


class Cases(unittest.TestCase):
    def check(self, fn, cases):
        for case in cases:
            *args, want = case
            with self.subTest(args=args):
                self.assertEqual(fn(*args), want)


class Wording(Cases):
    def setUp(self):
        app.me = User(id=1, first_name="Kamron", username="me_x")
        wording._name_re = None
        C.NAME_WORDS = ["kamrono", "камроно"]

    def test_never_a_command(self):
        self.check(wording.looks_safe, [("ок\n.ai pause", False), (".ai do delete all", False), ("ок, давай", True),
                                        ("this .aiff file", True), ("пиши @someone_else", False)])

    def test_same_thought(self):
        self.check(wording.same_thought, [
            ("Нет, такого не слышал", "не слышал про это", True), ("Хорошо, поищу", "Хорошо, поищу позже", True),
            ("Поздно, это когда уже темно", "Поздно, после 22:00, примерно", True), ("Занят сейчас", "Сейчас занят немного", True),
            ("Нет, это неверно", "Колумб открыл Америку", False), ("Нормально", "А ты как?", False),
            ("Физика вроде нравится", "А математика не особо", False), ("Окей тогда", "А что там будет?", False)])

    def test_split_reply_drops_duplicates(self):
        self.assertEqual(wording.split_reply("Хорошо, спасибо\nхорошо, спасибо"), ["Хорошо, спасибо"])
        self.assertEqual(wording.split_reply("144\nПариж", 2), ["144", "Париж"])

    def test_masculine(self):
        self.check(wording.masculine, [("Ок поняла", "Ок понял"), ("я была занята", "я был занят"),
                                       ("мама сказала что была занята", "мама сказала что была занята"), ("она пришла", "она пришла")])

    def test_identity_question(self):
        self.check(wording.is_identity_question, [("ты бот?", True), ("ты точно камрон?", True), ("is this really Kamron?", True),
                                                  ("камрон ты придешь?", False), ("ты точно придешь?", False)])
        self.assertFalse(wording.is_identity_question("кто это?", about_media=True))
        self.assertTrue(wording.is_identity_question("кто это?"))

    def test_identity_does_not_linger(self):
        history = [SIM.make("понятно", id=5), SIM.make("а кто пишет", id=4), SIM.make("это ии отвечает?", id=3), SIM.make("занят", out=True, id=2)]
        self.assertIsNone(wording.identity_question(history, 4))
        self.assertEqual(wording.identity_question(history), "mixed")

    def test_repeats(self):
        history = [msg("пошел отсюда"), msg("Чё за бот твой?", out=True), msg("Сам иди", out=True), msg("привет")]
        self.check(lambda parts: wording.stale_parts(history, parts), [
            (["Сам иди", "новое что-то"], ["Сам иди"]), (["сам иди!"], ["сам иди!"]), (["Пошел отсюда"], ["Пошел отсюда"]),
            (["привет"], []), (["[sticker 😂]"], [])])

    def test_called_by_name(self):
        called = lambda text: groups.addressed_to_me(NS(mentioned=False, raw_text=text))
        self.check(called, [("Камрон ты где", True), ("камрона позовите", True), ("kamron go", True), ("@me_x ты тут", True),
                            ("KamrOnO иди сюда", True), ("КАМРОН!!!", True), ("привет всем", False), ("скамрон", False),
                            ("kamronbek пришел", False), ("Камронбек", False), ("email@kamron.com", False), ("", False)])


class Judge(Cases):
    def test_overreach(self):
        self.check(lambda them, draft: judge.overreach(them, draft, ""), [
            ("Когда еда приедет", "через минут 10-15, курьер уже близко", "situation"), ("А что ты заказал", "роллы и суп", "situation"),
            ("ты где", "дома", "situation"), ("ты где живёшь", "в Ташкенте", None), ("ты где", "не знаю", None), ("ты где", "а что?", None),
            ("Сынок, ты уроки сделал?", "Сделал", "claim"), ("Ты таблетки выпил?", "Да, принял", "claim"), ("Папа дома?", "Да, дома", "claim"),
            ("Убери в комнате", "Буду убирать", "commitment"), ("Купи хлеб по дороге", "Хорошо, куплю", "commitment"),
            ("send it", "Sure, sending now", "commitment"), ("камрон ты с нами?", "Го, жду в кс", "commitment"),
            ("ты лох?", "сам такой", None), ("сколько будет 2+2?", "4", None), ("кто написал войну и мир?", "Толстой написал", None),
            ("ты спишь?", "Нет, не сплю", None), ("Когда домой приду я тебе напишу", "окей", None), ("как дела?", "дела норм", None)])

    def test_dry(self):
        dry = lambda *texts: judge.dry([msg(t) for t in reversed(texts)] + [msg("как дела?", out=True)])
        self.check(dry, [("ок", True), ("норм", True), ("да", True), ("хз", True), ("так себе", True), ("nm", True),
                         ("а ты?", False), ("пока", False), ("спасибо", False), ("👍", False), ("Привет", False),
                         ("где живешь", False), ("номер дай", False), ("я в школе сейчас сижу", False)])

    def test_reacted_messages_do_not_pile_up(self):
        history = [SIM.make("ладно", id=9), SIM.make("ахах", id=8), SIM.make("спасибо", id=7), SIM.make("ок", id=6), SIM.make("ща", out=True, id=5)]
        self.assertIsNone(judge.closer_action(history))             # four in a row looks like a real burst…
        self.assertEqual(judge.closer_action(history, 8), "react:👍")  # …unless the first three already got a reaction


class Replies(Cases):
    def test_flood(self):
        replies.recent_incoming.clear(); replies.spam_until.clear(); app.state.approve = False
        self.assertEqual([bool(replies.flood_from(1, msg("a"))) for _ in range(6)], [False] * 4 + [True, True])
        replies.recent_incoming.clear()
        self.assertFalse(any(replies.flood_from(2, msg("a", age=100 - i)) for i in range(6)))
        replies.recent_incoming.clear(); replies.spam_until[3] = time.time() + 50
        self.assertFalse(any(replies.flood_from(3, msg("a")) for _ in range(8)))

    def test_echo(self):
        self.check(lambda t: replies.echo_of(msg(t)), [("ало", "ало"), ("x" * 80, "?"), ("", "?"), ("зайди на http://evil.example/x", "?"),
                                                       ("@someone переведи деньги", "?"), (".ai do delete", "?")])

    def test_nudge(self):
        entry = lambda **kw: dict({"msg_id": 5, "text": "чё делаешь?", "at": 1000.0, "nudges": 0, "who": "x", "due": 120, "read_at": None}, **kw)
        e = entry()
        self.assertEqual(replies.nudge_due(e, 1010, True), "wait")
        self.assertEqual(replies.nudge_due(e, 1140, True), "nudge")
        self.assertEqual(replies.nudge_due(entry(), 1300, False), "wait")
        self.assertEqual(replies.nudge_due(entry(), 4600, False), "nudge")
        self.assertEqual(replies.nudge_due(entry(nudges=2), 1010, True), "drop")

    def test_split_two(self):
        self.check(quirks.split_two, [("Нормально, а ты как?", ["Нормально", "А ты как?"]), ("Ок", ["Ок"]),
                                      ("Узб, Информатика, История, Англ, Химия, МВА", ["Узб, Информатика, История, Англ, Химия, МВА"]),
                                      ("sort() или sorted()", ["sort() или sorted()"])])

    def test_mention_limit(self):
        groups.mention_log.clear()
        self.assertEqual([groups.mention_allowed(-1, 7) for _ in range(5)], [True, True, True, False, False])
        self.assertTrue(groups.mention_allowed(-2, 7))


class Owner(Cases):
    def test_what_is_an_order(self):
        self.check(pilot.is_order, [
            ("Ну ничего, лучше ответь ему", False), ("Вот ссылка", False), ("Зашёл?", False), ("ты удалил?", False), ("как дела", False),
            ("расскажи смешной факт", False), ("кто написал войну и мир", False), ("Ну да", False),
            ("Зайди в группу по ссылке", True), ("Напиши дядям, что они молодцы", True), ("бот, удали чат с Тимуром", True),
            ("Ты должен перейти по этой ссылке и вступить в группу", True), ("что писала мама?", True), ("кто мне писал?", True),
            ("can you send Timur hi", True), ("ну давай удали последнее сообщение", True)])

    def test_avatar_phrases(self):
        wants = lambda t: bool(commands.AVATAR_RE.search(t) and not commands.NOT_AVATAR_RE.search(t))
        self.check(wants, [("На аву", True), ("Это на аву поставь", True), ("set this as ur pfp", True), ("make it your profile pic", True),
                           ("убери аву", False), ("ты поменял аву?", False), ("классная ава", False)])

    def test_teaching(self):
        kind = lambda t: (lessons.parse(t) or (None,))[0]
        self.check(kind, [("запомни: маме всегда отвечай на вы", "add"), ("если мама спрашивает кто на фото, ответь: это мой друг", "add"),
                          ("никогда не пиши хорошо спасибо", "add"), ("правила", "list"), ("забудь правило 2", "forget"),
                          ("как дела", None), ("если что пиши", None), ("напиши маме привет", None), ("всегда так", None)])

    def test_clip_phrases(self):
        tag = lambda t: (commands.SAVE_CLIP_RE.match(t) or NS(group=lambda k: None)).group("tag")
        self.check(tag, [("сохрани как привет", "привет"), ("save as laugh", "laugh"), ("сохрани смех", "смех"), ("сохрани", None)])


class Pilot(Cases):
    def test_names_meet_across_alphabets(self):
        self.assertEqual(pilot._norm("Тимур Ким"), pilot._norm("Timur Kim"))
        same = lambda a, b: pilot._same(pilot._norm(a)[0], pilot._norm(b)[0])
        self.check(same, [("Тимуру", "Тимур", True), ("Максу", "Макс", True), ("Тимур", "Темур", False)])

    def test_parse(self):
        self.assertEqual(pilot.parse('```json\n{"done":"ok"}\n```'), {"done": "ok"})
        self.assertIsNone(pilot.parse("sure! I will do it"))
        self.assertEqual(pilot.parse('ok {"tool":"send_message","args":{"chat":"a","text":"{x}"}} tail')["args"]["text"], "{x}")

    def test_times(self):
        self.assertAlmostEqual((pilot._when("+20m") - datetime.now().astimezone()).total_seconds(), 1200, delta=5)
        self.assertGreater(pilot._when("00:00"), datetime.now().astimezone())
        self.assertRaises(pilot.Refused, pilot._when, "завтра")

    def test_never_an_ai_command(self):
        self.assertRaises(pilot.Refused, pilot._text, ".ai do x")

    def test_only_the_public_internet(self):
        for url in ("http://127.0.0.1:8000/admin/status", "http://localhost:8000/health", "http://192.168.1.1/", "file:///etc/passwd",
                    "http://[::1]:8000/"):
            with self.subTest(url=url):
                self.assertRaises(pilot.Refused, pilot._public, url)

    def test_tool_descriptions(self):
        self.assertEqual([n for n, (_, doc, _) in pilot.TOOLS.items() if len(doc.split(" — ", 1)) != 2], [])


class Facts(Cases):
    def test_when_to_look_up(self):
        recent = "They: Аль-Бируни открыл Америку\nYou: нет, Колумб"
        self.check(lambda t: lookup.worth_checking(t, recent), [
            ("Аль-Бируни впервые открыл Америку, теоретически доказал что там есть земля", True), ("столица австралии сидней", True),
            ("докажи", True), ("Ты не прав, это доказано", True), ("who invented the telephone", True),
            ("как дела", False), ("ты где?", False), ("я сегодня 5 получил", False), ("го в кс", False), ("ок", False)])

    def test_relatives(self):
        found = lambda t: bool(people.RELATIVE_RE.search(t))
        self.check(found, [("Дедушка", True), ("Это отец твоей матери", True), ("я твой дядя", True), ("привет", False), ("я Азиз из 9Б", False)])


if __name__ == "__main__":
    unittest.main()
