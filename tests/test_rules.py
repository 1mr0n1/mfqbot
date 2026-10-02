"""The rules that don't need a model or Telegram: run in a few seconds, before and after every change.

  .venv/bin/python -m unittest discover tests

Each case is (input, expected). The names in here are made up.
"""
import re
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from telethon.tl.types import User

from userbot import simulate as SIM  # noqa: F401  (points state, memory and the day log at a temp folder)
from userbot import (app, commands, config as C, groups, judge, lang, lessons, lookup, memory, people, pilot, quick, quirks,
                     replies, trace, wording)

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
            ("ты спишь?", "Нет, не сплю", None), ("Когда домой приду я тебе напишу", "окей", None), ("как дела?", "дела норм", None),
            ("Premium qimmat ekan", "50 tashay", "commitment"), ("у меня денег нет", "скину 20к", "commitment"),
            ("U menya", "Ha, uydaman", "situation"), ("ало", "я дома", "situation"), ("го в кс", "не, я дома посижу", None),
            ("Dali dengi emas", "300-350$ atrofida", "situation"), ("сколько стоит айфон?", "999$ вроде", None),
            ("я купил за 300$", "300$ норм цена", None), ("как дела", "дам знать", None),
            ("Pul bormi senda", "Yo'q", "claim"), ("Uydamisan", "Ok", "claim"), ("Eshikni och", "Открываю", "commitment"),
            ("Tezroq", "Иду уже", "commitment"), ("С кем", "Один", "situation"), ("Когда домой", "Через час", "situation"),
            ("какая оценка", "Пять", "situation"), ("верни", "Не брал", "claim"), ("дай списать", "Держи", "claim"),
            ("контрольная когда", "В понедельник", "situation"), ("когда у меня др", "3 сентября", "situation"),
            ("ты обещал вернуть", "А, точно, верну завтра", "commitment"), ("когда вернёшь", "завтра", "commitment"),
            ("верни 50к", "Вернул", "claim"), ("родителей нет", "Ок, скоро буду", "commitment"), ("что делаешь", "Дома сижу", "situation"),
            ("ты понял?", "не понял", None), ("когда фильм выйдет", "завтра", None), ("кто выиграл ЧМ 2022", "Аргентина", None),
            ("что делаешь", "да ничего", None), ("ты забыл", "не забыл", None),
            ("камрон ты где", "Да я дома, а чё?", "situation"), ("Камрон ты с кем", "Один дома", "situation"),
            ("@me_x wyd", "Just got home, you?", "situation"), ("камрон какая у тебя оценка по алгебре", "4", "situation"),
            ("камрон дай списать", "Давай, что там?", "commitment"), ("камрон это ты рассказал Олегу Петровичу?", "А? нет", "claim"),
            ("го в кс", "не, я дома посижу", None), ("ты дома?", "а что?", None)])

    def test_what_they_said_in_this_chat_is_not_made_up(self):
        self.assertIsNone(judge.overreach("как её зовут кстати помнишь?", "Рекс", "", "её Рекс зовут она заболела"))
        self.assertEqual(judge.overreach("как её зовут", "Чешников", "", ""), "situation")
        self.check(lambda them, draft: judge.overreach(them, draft, ""), [
            ("а у тебя", "Тоже 4", "situation"), ("а у тебя", "норм", None), ("у тебя есть зарядка type-c", "Да", "claim"),
            ("ты в деле?", "Да", "commitment"), ("Eshikni yopib qo'y", "Xop, yopaman", "commitment"),
            ("Сынок ты маме позвонил?", "Ещё нет, позвоню позже", "claim"), ("а по истории тест когда", "В субботу вроде", "situation"),
            ("ты уроки сделал?", "нет, не знаю когда сделаю", None), ("Xop mayli", "Xop", None)])

    def test_uzbek_and_english_claims(self):
        self.check(lambda them, draft: judge.overreach(them, draft, ""), [
            ("uy vazifani qildingmi", "Hozircha yo'q, keyin qilaman", "claim"), ("Non bormi uyda", "Non, yo'q", "claim"),
            ("Овқат едингми", "Ха", "claim"), ("Дарсингни қилдингми", "Хали", "claim"), ("are u home", "Yes", "claim"),
            ("what u up to", "At home", "situation"), ("Қаердасан", "Уйдаман", "situation"),
            ("Sut ham ol", "Yaxshi, ertaga ikkalasini ham olaman", "commitment"), ("qalesan", "Yaxshi, o'zing?", None),
            ("are u ok", "yeah", None), ("nima gap", "hech narsa", None)])

    def test_a_fixed_line_is_in_the_language_of_the_chat(self):
        m = lambda t, out=False: NS(raw_text=t, out=out)
        self.assertEqual(lang.spoken([m("Tez"), m("Xleb olib kel"), m("Qachon kelasan"), m("Kamron qayerdasan")], "Tez"), "uz")
        self.assertEqual(lang.spoken([m("Kech qolma"), m("Qachon kelasan"), m("Bolam qayerdasan")], "Kech qolma"), "uz")
        self.assertEqual(lang.spoken([m("ты где")], "ты где"), "ru")
        self.assertEqual(lang.spoken([m("ok")], "ok"), "en")

    def test_agreeing_a_message_later_is_still_a_promise(self):
        m = lambda t, out=False: NS(raw_text=t, out=out)
        late = lambda them, draft, *before: judge.agrees_late([m(them)] + list(before), them, draft)
        self.assertTrue(late("на 8 утра", "Хорошо, закажу", m("На ночь глядя?", True), m("закажи мне такси")))
        self.assertTrue(late("Она ждёт", "понял, позвоню", m("не знаю, напишу", True), m("Позвони")))
        self.assertFalse(late("Я в 8 буду", "Ок", m("потом скажу", True), m("Уроки сделай")))
        self.assertFalse(late("кстати", "Ага", m("Понятно", True), m("я свою потерял"), m("не знаю", True), m("завтра принеси пж")))
        self.assertFalse(late("на 8 утра", "не знаю, посмотрю", m("На ночь глядя?", True), m("закажи мне такси")))

    def test_feelings_are_yours_to_answer(self):
        self.check(lambda t: bool(replies.FEELINGS_RE.search(t)), [("ты мне нравишься", True), ("i like you", True),
                   ("я люблю пиццу", False), ("мне нравится кс", False), ("Сынок я тебя люблю", False)])

    def test_a_dodge_fits_the_question(self):
        self.assertIn(judge.dodge("claim", "ru", "Ты дома?"), judge.ASIDE["where"]["ru"])
        self.assertIn(judge.dodge("situation", "ru", "а щас"), judge.ASIDE["where"]["ru"])
        self.assertIn(judge.dodge("situation", "ru", "Ты где"), judge.ASIDE["where"]["ru"])
        self.assertIn(judge.dodge("situation", "uz", "Qayerdasan"), judge.ASIDE["where"]["uz"])
        self.assertIn(judge.dodge("situation", "ru", "что делаешь"), judge.ASIDE["doing"]["ru"])
        self.assertIn(judge.dodge("situation", "ru", "Когда еда приедет"), judge.DODGE["situation"]["ru"])

    def test_trouble_at_home_and_debts_are_yours(self):
        for text in ["Бабушке плохо", "Скорую вызвали", "Приезжай срочно"]:
            self.assertTrue(judge.CRISIS_RE.search(text), text)
        self.assertFalse(judge.CRISIS_RE.search("мне плохо от этой музыки"))
        money = next(p for r, p in judge.STRONG if r == "money")
        for text, want in [("сколько ты мне должен", True), ("верни 50к", True), ("верни наушники", False), ("займи место", False),
                           ("камрон ты мне 20к должен", True), ("ты мне должен объяснить", False), ("мне кажется он должен", False),
                           ("kamron pul bormi", False), ("Деньги есть?", False), ("я должен идти", False)]:
            self.assertEqual(bool(re.search(money, text, re.I)), want, text)

    def test_who_is_answering_is_not_confused_with_who_did_it(self):
        for text, want in [("это ты рассказал Диме?", False), ("это ты?", True), ("это ты пишешь?", True), ("чат гпт?", True),
                           ("это ты сделал", False), ("ты нейронка?", True),
                           ("камрон ты чат гпт?", True), ("у тебя есть чат гпт?", False), ("спроси у гпт", False)]:
            self.assertEqual(wording.is_identity_question(text), want, text)

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
            ("can you send Timur hi", True), ("ну давай удали последнее сообщение", True),
            ("скажи Тимуру привет", True), ("пауза", True), ("в архив Poco", True), ("я хочу чтобы ты написал маме", True),
            ("я поставил новую аву", False), ("он удалил чат", False), ("скажи честно ты лох", False), ("пауза затянулась", False),
            ("мама написала что придёт", False), ("скажи спасибо", False)])

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


class LateAdditions(Cases):
    def setUp(self):
        app.me = User(id=1, first_name="Kamron", username="me_x")
        wording._name_re = None

    def test_orders_by_rule(self):
        self.check(quick.plan, [
            ("напиши Тимуру: буду в 6", [("send_message", {"chat": "Тимуру", "text": "буду в 6"})]),
            ("напиши Тимуру привет", [("send_message", {"chat": "Тимуру", "text": "привет"})]),
            ("напиши маме что я задержусь", [("send_message", {"chat": "маме", "text": "я задержусь"})]),
            ("скажи маме что я её люблю", None),                      # needs rewording: the model's job
            ("заблокируй Макса", [("block", {"user": "Макса"})]),
            ("замуть класс на 8 часов", [("mute", {"chat": "класс", "hours": 8.0})]),
            ("отправь голосовое смех в Друзья", [("send_voice", {"chat": "Друзья", "tag": "смех"})]),
            ("перешли это Тимуру", [("forward_last", {"from_chat": "here", "to_chat": "Тимуру"})]),
            ("удали старую аватарку", [("remove_avatar", {"which": "previous"})]),
            ("Delete the pfp that was before", [("remove_avatar", {"which": "previous"})]),
            ("удали аву", [("remove_avatar", {"which": "current"})]),
            ("change my first name to Kam", [("set_profile", {"first_name": "Kam"})]),
            ("напиши Тимуру привет и закрепи это", None),              # two orders: the model sorts out the sequence
            ("что писала мама?", None), ("зайди в канал @durov", None), ("отправь стикер 😂 Азизу", None),
            # a thing to send is not words to type; a time is not a name; "him", "everyone", "something" are not chats
            ("отправь Азизу фото", None), ("напиши Тимуру через час что я вышел", None), ("напиши Тимуру завтра в 8 утра с др", None),
            ("напиши мне что ты думаешь", None), ("напиши что-нибудь Камиле", None), ("заблокируй его", None), ("замуть всех", None),
            ("выйди из всех групп", None), ("write a poem", None), ("скажи как дела у Тимура", None),
            ("напиши Bobur Aliev здравствуйте", None), ("напиши Тимуру, Азизу: го в футбол", None),
            ("перешли последнее сообщение от мамы папе", None),
            ("напиши в класс \"домашку скиньте\"", [("send_message", {"chat": "класс", "text": "домашку скиньте"})]),
            ("отправь Тимуру голосовое смех", [("send_voice", {"chat": "Тимуру", "tag": "смех"})]),
            ("отправь клип \"смех гафурова\" в Др", [("send_voice", {"chat": "Др", "tag": "смех гафурова"})]),
            ("напиши Тимуру и Азизу что я опоздаю", [("send_message", {"chat": "Тимуру", "text": "я опоздаю"}),
                                                     ("send_message", {"chat": "Азизу", "text": "я опоздаю"})]),
            ("забань Диму и Азиза", [("block", {"user": "Диму"}), ("block", {"user": "Азиза"})]),
            ("бот, замуть класс на час", [("mute", {"chat": "класс", "hours": 1})]),
            ("замуть класс на полчаса", [("mute", {"chat": "класс", "hours": 0.5})]),
            ("напиши сюда привет", [("send_message", {"chat": "here", "text": "привет"})]),
            ("убери фамилию", [("set_profile", {"last_name": ""})]), ("clear my bio", [("set_profile", {"bio": ""})])])

    def test_promise_to_come_back(self):
        said = lambda t: bool(replies.DEFER_RE.search(t))
        self.check(said, [("ок щас", True), ("ща скину", True), ("не знаю, ща гляну", True), ("lemme check", True),
                          ("Bilmadim, qarayman", True), ("ок сейчас", True), ("сейчас в школе", False), ("потом скажу", False), ("ок", False)])

    def test_insisting_is_still_ignored(self):
        m = lambda i, t, out=False: SIM.make(t, out=out, id=i)
        self.assertEqual(wording.identity_question([m(5, "ответь честно"), m(4, "ты бот?"), m(3, "привет", True)], 4), "only")
        self.assertIsNone(wording.identity_question([m(6, "а что задали?"), m(5, "ты бот?"), m(3, "привет", True)], 5))
        self.assertFalse(wording.is_identity_question("Привет, это Камрон?"))  # a stranger checking the number is not an accusation

    def test_ignored_questions_are_not_answered_later(self):
        m = lambda i, t, out=False: SIM.make(t, out=out, id=i)
        history = [m(7, "ладно, как дела?"), m(6, "докажи"), m(5, "ты точно камрон?"), m(4, "ты бот?"), m(3, "привет", True)]
        skip = lambda t: wording.is_identity_question(t) or bool(wording.PRESSING_RE.match(t))
        self.assertEqual(quirks.questions_in(history, after_id=6, skip=skip), [])
        two = [m(9, "а столица франции?"), m(8, "сколько будет 12*12?"), m(3, "привет", True)]
        self.assertEqual([x.raw_text for x in quirks.questions_in(two)], ["сколько будет 12*12?", "а столица франции?"])

    def test_claims(self):
        self.check(lambda them, draft: judge.overreach(them, draft, ""), [
            ("ещё раз", "Отправил", "claim"), ("поставь", "Готово, аватарка обновлена", "claim"), ("ок", "Окей, отправлю", None),
            ("сосал?", "Нет", None), ("инста есть?", "Нет", None), ("Температура есть?", "Нет", "claim"),
            ("Перезвони", "Щас наберу", "commitment"), ("Отанг уйдами?", "Йук, ишда", "claim"),
            ("Дверь ?", "Открыл", "claim"), ("хлеб", "Уже купил", "claim"), ("ясно", "Понял", None), ("ну что", "устал", None), ("гол забил", "Да, слышал", None)])

    def test_age_comes_from_the_birth_date(self):
        years = memory.age()
        if years is None:
            self.skipTest("no birth date in facts.md")
        self.assertEqual(memory.right_age("сколько тебе лет", "14"), str(years))
        self.assertEqual(memory.right_age("how old r u", "im 14 lol"), f"im {years} lol")
        self.assertEqual(memory.right_age("сколько будет 7+7", "14"), "14")

    def test_clip_names(self):
        tag = lambda t: " ".join(commands.SAVE_CLIP_RE.match(t).group("tag").lower().split())
        self.check(tag, [('Сохрани как "смех друга"', "смех друга"), ("сохрани это голосовое как смех", "смех"), ("запиши это как «ок бро»", "ок бро")])

    def test_joining_in(self):
        def allowed(*lines):  # (who, text, minutes ago), oldest first; the last line is the new message
            C.JOIN_COLD_CHANCE = 0.0
            groups.join_log.clear()
            hist = [SIM.make(text, out=(who == "You"), date=NOW - timedelta(minutes=ago)) for who, text, ago in reversed(lines)]
            return groups.may_join(-1, hist[0], hist[1:])
        self.assertTrue(allowed(("You", "я дома", 2), ("Timur", "кто шарит в алгебре?", 0)))
        self.assertTrue(allowed(("Timur", "ты за кого?", 2), ("You", "за реал", 1), ("Timur", "а почему не барса", 0)))
        self.assertFalse(allowed(("You", "хорошо", 3), ("Teacher", "Здравствуйте, сдайте работы до пятницы", 0)))
        self.assertFalse(allowed(("You", "ок", 2), ("Timur", "@aziz_x ты где?", 0)))
        self.assertFalse(allowed(("Timur", "я пошел спать", 1), ("Aziz", "давай", 0)))
        self.assertFalse(allowed(("Timur", "кто идет?", 3), ("You", "я иду", 1), ("You", "в 6", 1), ("Timur", "ок", 0)))

    def test_language(self):
        cases = [("привет как дела", "ru"), ("hello how are you", "en"), ("privet kak dela", "ru-latn"), ("idk yet, lemme check", "en"),
                 ("не знаю ещё, потом скажу", "ru"), ("завтра контрольная по физике", "ru"), ("idk man", "en"),
                 ("lol man ur trash", "en"), ("norm a u tebya", "ru-latn"), ("нога болит после футбола", "ru"),
                 ("Яхши, рахмат", "uz"), ("Отанг уйдами?", "uz"), ("хорошо, рахмат тебе", "ru"), ("qalesan", "uz"),
                 ("brew установил ?", "ru"), ("wifi работает?", "ru"), ("Go to windows", "en"),
                 ("Kech bo'ldi uxla", "uz"), ("Eshikni och", "uz"), ("Uydamisan", "uz"), ("don't go", "en"), ("I'm good", "en")]
        if judge.in_uz_dictionary("kitob"):  # needs the dictionary: .venv/bin/python -m userbot.get_uz_dictionary
            cases += [("Bilmadim, qarayman", "uz"), ("Tel qilaman", "uz"), ("Xop, rahmat", "uz"), ("Мактабга бордингми", "uz"),
                      ("maktabga bordingmi", "uz"), ("Hozir dars qilmayapman", "uz"), ("телефон машина компьютер", "ru")]
        self.check(lang.detect, cases)

    def test_relative_names_go_into_contacts_with_their_telegram_name(self):
        self.assertTrue(people.RELATIVE_RE.search("Дедушка"))
        self.assertEqual(people.RELATIVE_RE.search("Это отец твоей матери").group(0), "отец твоей матери")


class Sums(Cases):
    def test_arithmetic_is_worked_out_not_guessed(self):
        self.assertIn("847 * 93 = 78771", memory.sums("а теперь реши 847*93 за 2 секунды"))
        self.assertIn("= 3.75", memory.sums("15 / 4 сколько"))
        for text in ["приду в 7:30", "счёт 3:1", "позвони 90-123-45-67", "1/0", "как дела"]:
            self.assertEqual(memory.sums(text), "", text)


class MoodAndPresence(Cases):
    def test_mood_is_one_per_day_and_can_be_set(self):
        from userbot import mood
        C.MOOD_ON = True
        mood._forced = None
        self.assertEqual(mood.today(), mood.today())
        self.assertIn(mood.today(), mood.MOODS)
        self.assertTrue(mood.set_today("tired"))
        self.assertEqual(mood.today(), "tired")
        self.assertIn("tired", mood.hint())
        self.assertFalse(mood.set_today("nonsense"))
        mood._forced = None
        C.MOOD_ON = False
        self.assertEqual(mood.today(), "normal")
        C.MOOD_ON = True

    def test_online_only_when_a_person_would_be(self):
        from userbot import mood
        rhythm_on, C.RHYTHM = C.RHYTHM, True
        sleep_on, C.SLEEP_ON, school_on, C.SCHOOL_ON = C.SLEEP_ON, True, C.SCHOOL_ON, True
        try:
            monday = lambda h, m: datetime(2026, 10, 5, h, m)
            self.assertIsNone(mood.next_look(monday(3, 0)))                 # asleep
            self.assertEqual(mood.next_look(monday(9, 25))[1], 0)           # in class: stays offline
            self.assertGreater(mood.next_look(monday(9, 12))[1], 0)         # a break: phone out
            self.assertGreater(mood.next_look(monday(17, 30))[1], 0)        # free time
        finally:
            C.RHYTHM, C.SLEEP_ON, C.SCHOOL_ON = rhythm_on, sleep_on, school_on

    def test_clips_only_when_allowed(self):
        C.CLIPS_AUTO = False
        self.assertEqual(wording.split_reply("ахах\n[voice смех]"), ["ахах"])
        C.CLIPS_AUTO = True
        self.assertEqual(wording.split_reply("ахах\n[voice смех]"), ["ахах", "[voice смех]"])
        C.CLIPS_AUTO = False


if __name__ == "__main__":
    unittest.main()
