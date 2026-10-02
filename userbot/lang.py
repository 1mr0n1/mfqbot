"""Tiny language detector for the three languages the account chats in: Uzbek, Russian, English."""
import re

# Common Uzbek (Latin) chat words that aren't English or transliterated Russian words.
UZ_WORDS = {
    "salom", "assalomu", "alaykum", "qalaysan", "qalaysiz", "qalay", "qalesan", "qalesiz", "qale", "qalaysizlar", "yaxshi", "yaxshimisan", "yaxshimisiz", "rahmat",
    "nima", "nega", "qachon", "qayerda", "qayerdasan", "qanday", "qancha", "kim", "men", "sen", "siz", "biz", "ular",
    "ha", "yoq", "yo'q", "mayli", "xop", "hop", "bor", "kerak", "emas", "bilan", "uchun", "lekin", "ham", "hozir",
    "bugun", "ertaga", "kecha", "keyin", "aka", "uka", "opa", "dost", "do'st", "jora", "jo'ra", "oka", "bolar",
    "bo'ldi", "boldi", "qilyapsan", "qilyapsiz", "qilaman", "qilasan", "kelasan", "kelasanmi", "kelaman", "boraman",
    "borasan", "ketdim", "keldim", "bilmayman", "bilaman", "gap", "zor", "zo'r", "ishlar", "ishing", "uyda", "dars",
    "darsga", "maktab", "pul", "vaqt", "yordam", "iltimos", "kechirasiz", "uzr", "tushundim", "aytdim", "ayt",
}
# Everyday (Tashkent) spellings and forms. Kept separate because many are short and collide with English.
UZ_WEAK = {
    "man", "san", "sanga", "manga", "sani", "mani", "sila", "silani", "biza", "bizaga", "uyga", "uyda", "ekan", "shu",
    "shuni", "kere", "narsa", "yana", "deb", "qil", "qilib", "boladi", "bormi", "haa", "haaa", "uje", "qanchada",
    "shunaqa", "bir", "endi", "boshqa", "borib", "ozi", "ozim", "qara", "yoz", "qatta", "kel", "tur", "bitta", "bop",
    "labbay", "juda", "bilmasam", "chiqib", "kelib", "olib", "hali", "ming", "keldi", "olmang", "voy", "daa", "opajon",
    "oyijon", "dadajon", "tashab", "tashadim", "zakaz", "oqib", "kelila", "chiqila", "minutda", "yoq", "xa", "hop",
    "ketyapman", "kelyapman", "boryapman", "qildim", "boldim", "kerakmi", "yaxshimi", "nechida", "soat", "yozing",
}
EN_STOP = {"the", "you", "is", "are", "what", "and", "to", "it", "that", "this", "my", "of", "in", "for", "do", "on",
           "not", "was", "have", "with", "bro", "just", "im", "u", "me", "so", "but", "like", "no", "yes", "can", "how"}
RU_TRANSLIT = {
    "privet", "poka", "kak", "dela", "che", "chto", "shto", "nichego", "nichё", "norm", "normalno", "davay", "davai",
    "spasibo", "pozhaluysta", "ladno", "horosho", "xorosho", "khorosho", "da", "net", "ne", "segodnya", "zavtra",
    "skazhi", "znaesh", "ponyal", "seychas", "shas", "potom", "pochemu", "kogda", "gde", "skolko", "brat",
}
NAMES = {
    "uz": "Uzbek", "uz-cyrl": "Uzbek written in Cyrillic", "ru": "Russian", "ru-latn": "Russian typed in Latin letters",
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese", "it": "Italian",
    "tr": "Turkish", "id": "Indonesian", "pl": "Polish", "nl": "Dutch", "az": "Azerbaijani", "uk": "Ukrainian",
    "kk": "Kazakh", "ky": "Kyrgyz", "tg": "Tajik", "ar": "Arabic", "fa": "Persian", "he": "Hebrew", "hi": "Hindi",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "th": "Thai", "el": "Greek", "ka": "Georgian", "hy": "Armenian",
    "other": "the same language they wrote in",
}

# Scripts that identify a language (or family) on their own.
SCRIPTS = [
    ("ja", r"[\u3040-\u30ff]"), ("ko", r"[\uac00-\ud7af]"), ("zh", r"[\u4e00-\u9fff]"),
    ("fa", r"[پچژگ]"), ("ar", r"[\u0600-\u06ff]"), ("he", r"[\u0590-\u05ff]"), ("hi", r"[\u0900-\u097f]"),
    ("th", r"[\u0e00-\u0e7f]"), ("el", r"[\u0370-\u03ff]"), ("ka", r"[\u10a0-\u10ff]"), ("hy", r"[\u0530-\u058f]"),
]
# Cyrillic languages told apart by their special letters (checked before falling back to Russian).
CYRILLIC_MARKS = [("uz-cyrl", "ўЎ"), ("tg", "ӣӯҷӢӮҶ"), ("kk", "әұӘҰ"), ("uk", "їєґіЇЄҐІ"), ("ky", "ңөүҢӨҮ"),
                  ("uz-cyrl", "қғҳҚҒҲ")]
# Very common words per Latin-script language.
LATIN_WORDS = {
    "en": EN_STOP | {"hello", "hi", "hey", "thanks", "thank", "please", "why", "when", "where", "who", "your", "we",
                     "they", "be", "at", "from", "will", "would", "about", "there", "good", "ok", "okay", "lol"},
    "es": {"hola", "que", "qué", "como", "cómo", "estas", "estás", "gracias", "por", "favor", "pero", "muy", "bien",
           "donde", "dónde", "cuando", "cuándo", "tengo", "tienes", "esta", "está", "eres", "soy", "los", "las", "una",
           "para", "porque", "buenos", "buenas", "dias", "días", "amigo", "vale", "también"},
    "fr": {"bonjour", "salut", "merci", "oui", "non", "comment", "ça", "va", "est", "une", "des", "les", "pour", "avec",
           "pas", "mais", "très", "bien", "pourquoi", "quand", "où", "suis", "tu", "je", "vous", "nous", "c'est", "quoi"},
    "de": {"hallo", "danke", "bitte", "ja", "nein", "wie", "geht", "und", "ist", "nicht", "ich", "du", "wir", "sie",
           "das", "der", "die", "ein", "eine", "mit", "für", "aber", "warum", "wann", "wo", "gut", "auch", "bin", "was"},
    "pt": {"olá", "ola", "obrigado", "obrigada", "sim", "não", "nao", "como", "você", "voce", "está", "tudo", "bem",
           "por", "favor", "mas", "muito", "onde", "quando", "tenho", "uma", "para", "porque", "bom", "dia", "isso"},
    "it": {"ciao", "grazie", "prego", "sì", "come", "stai", "sono", "che", "non", "per", "favore", "ma", "molto", "bene",
           "dove", "quando", "perché", "perche", "una", "con", "anche", "buongiorno", "cosa", "sei", "questo"},
    "tr": {"merhaba", "selam", "teşekkürler", "tesekkurler", "evet", "hayır", "hayir", "nasılsın", "nasilsin", "iyi",
           "ben", "sen", "biz", "ve", "bir", "bu", "ne", "için", "icin", "ama", "çok", "cok", "değil", "degil", "var",
           "yok", "nerede", "zaman", "tamam", "lütfen", "lutfen", "günaydın", "naber", "nasıl", "nasil"},
    "id": {"halo", "terima", "kasih", "ya", "tidak", "apa", "kabar", "saya", "kamu", "dan", "ini", "itu", "di", "ke",
           "yang", "untuk", "dengan", "tapi", "sangat", "baik", "kapan", "dimana", "kenapa", "aku", "sudah", "belum"},
    "pl": {"cześć", "czesc", "dziękuję", "dziekuje", "tak", "nie", "jak", "się", "sie", "masz", "jest", "to", "na",
           "ale", "bardzo", "dobrze", "gdzie", "kiedy", "dlaczego", "jestem", "co", "proszę", "prosze"},
    "nl": {"hallo", "dank", "bedankt", "ja", "nee", "hoe", "gaat", "het", "en", "is", "niet", "ik", "jij", "wij",
           "een", "met", "voor", "maar", "waarom", "wanneer", "waar", "goed", "ook", "ben", "wat", "alsjeblieft"},
    "az": {"salam", "necəsən", "necesen", "sağol", "sagol", "bəli", "beli", "xeyr", "mən", "sən", "və", "bu", "nə",
           "üçün", "ucun", "amma", "çox", "yaxşı", "yaxsi", "harada", "niyə", "təşəkkür"},
}


RU_COMMON = set("""привет пока спасибо пожалуйста что это как где когда почему потому если чтобы или тоже уже ещё еще очень
    сегодня завтра вчера сейчас потом хорошо плохо нормально ладно давай можно нужно надо будет было есть нет да меня тебя
    мне тебе его она они мы вы ты он был была были буду будешь знаю хочу могу делаю делаешь""".split())


_CYR = (("shch", "щ"), ("sch", "щ"), ("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("ya", "я"), ("yu", "ю"),
        ("yo", "ё"), ("ye", "е"), ("a", "а"), ("b", "б"), ("v", "в"), ("g", "г"), ("d", "д"), ("e", "е"), ("z", "з"), ("i", "и"),
        ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"), ("r", "р"), ("s", "с"), ("t", "т"), ("u", "у"),
        ("f", "ф"), ("h", "х"), ("c", "к"), ("j", "ж"), ("x", "х"), ("w", "в"), ("q", "к"), ("'", "ь"))


def _to_cyrillic(word: str, y: str) -> str:
    out, i = "", 0
    while i < len(word):
        if word[i] == "y" and not word.startswith(("ya", "yu", "yo", "ye"), i):
            out, i = out + y, i + 1
            continue
        for latin, cyr in _CYR:
            if word.startswith(latin, i):
                out, i = out + cyr, i + len(latin)
                break
        else:
            out, i = out + word[i], i + 1
    return out


UZ_CYR_WORDS = set("""яхши рахмат хоп майли йук йўқ ҳа нима нега качон қачон каерда қаерда канча қанча ким хозир ҳозир эртага
    кеча бугун уйда уйдами уйга отанг онанг ота она ака ука опа сингил келди келасан борасан болди бўлди булди катта кичик
    тез секин керак йок бор борми йукми салом хайр яхшимисан яхшимисиз ишлар калай қалай узингчи ўзингчи раҳмат""".split())
UZ_ENDINGS = ("yapman", "yapsan", "yapti", "aman", "asan", "amiz", "asiz", "dim", "ding", "dik", "gan", "moqchi", "ingiz",
              "larni", "larga", "lar", "ning", "dagi", "dan", "ga", "mi", "man", "san", "miz", "siz", "ymi", "imi")
UZ_ENDINGS_CYR = ("япман", "япсан", "япти", "аман", "асан", "амиз", "асиз", "дим", "динг", "дик", "ган", "моқчи", "мокчи", "ингиз",
                  "ларни", "ларга", "лар", "нинг", "даги", "дан", "га", "ми", "ман", "сан", "миз", "сиз")


def _russian_in_latin(word: str) -> bool:
    """ "nomer", "naydi", "menya": a Russian word typed in Latin letters — recognised by turning it back into Cyrillic
    and looking it up among the words you yourself use. Not for words that look Uzbek (q, o', g', Uzbek endings)."""
    if len(word) < 4 or not word.isascii() or "q" in word or "'" in word or word.endswith(UZ_ENDINGS):
        return False
    try:
        from . import judge
        judge._load_words()
        vocab = judge._vocab or set()
    except Exception:
        return False
    if judge._is_english(word):
        return False  # "windows", "linux"
    return any(_to_cyrillic(word, y) in vocab for y in ("й", "ы", "и"))


def _dictionary_uzbek(word: str) -> bool:
    """An Uzbek word by the dictionary (if one was downloaded): a stem it knows carrying an Uzbek ending, or a word
    with q / o' / g' that it knows. Loanwords shared with Russian ("nomer", "телефон") don't count."""
    if len(word) < 4:
        return False
    try:
        from .judge import _is_english, _load_words, in_uz_dictionary
        _load_words()
        if _is_english(word) or word in RU_TRANSLIT or not in_uz_dictionary(word):
            return False
    except Exception:
        return False
    if word.isascii():
        return "q" in word or "'" in word or word.endswith(UZ_ENDINGS)
    return word.endswith(UZ_ENDINGS_CYR) and word not in RU_COMMON


def _words(text: str) -> list[str]:
    text = text.lower().replace("‘", "'").replace("’", "'").replace("`", "'").replace("ʻ", "'")
    return re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*", text)


def detect(text: str) -> str | None:
    """-> language code (see NAMES), 'other' for an unrecognized language, or None when there are no letters."""
    words = _words(text)
    if not words:
        return None
    for code, pattern in SCRIPTS:
        if re.search(pattern, text):
            return code
    cyr = sum(bool(re.search("[\u0400-\u04ff]", w)) for w in words)
    if cyr >= len(words) / 2:  # "brew установил?", "wifi работает?": a Latin name in a Russian sentence
        for code, marks in CYRILLIC_MARKS:
            if set(marks) & set(text):
                return code
        # Uzbek typed in Cyrillic without ў/қ/ғ/ҳ ("хозир кечки, эртага борайликми") looks like Russian by its letters
        if not any(w in RU_COMMON for w in words) and sum(w in UZ_CYR_WORDS for w in words) >= max(1, len(words) * 0.5):
            return "uz"
        longer = [w for w in words if len(w) >= 4]
        if longer and sum(_dictionary_uzbek(w) or w in UZ_CYR_WORDS for w in longer) >= max(1, len(longer) * 0.5) \
                and not any(w in RU_COMMON for w in words):
            return "uz"
        return "ru"
    if any(re.search(r"[og]['ʻ‘’`][a-z]", w) for w in words):
        return "uz"  # o', g' — no other language you write in has them
    uz = sum(w in UZ_WORDS or "o'" in w or "g'" in w or _dictionary_uzbek(w) for w in words)
    weak = sum(w in UZ_WEAK for w in words)
    try:
        from .judge import CHAT_ENGLISH
    except Exception:
        CHAT_ENGLISH = set()
    english_looking = bool((EN_STOP | CHAT_ENGLISH) & set(words))
    if (uz or weak) and not english_looking and not uz:
        uz += 0  # only weak evidence: decided below
    if uz or (weak and not english_looking):  # weak words only count when it doesn't look like English
        uz += weak
    scores = {code: sum(w in vocab for w in words) for code, vocab in LATIN_WORDS.items()}
    scores["uz"] = uz * 2  # home languages win ties
    scores["ru-latn"] = sum(w in RU_TRANSLIT or _russian_in_latin(w) for w in words) * 1.5
    best = max(scores, key=scores.get)
    # One shared word isn't enough to name a foreign language in a longer message.
    if scores[best] and (best in ("uz", "ru-latn", "en") or scores[best] >= 2 or len(words) < 3):
        return best
    if len(words) < 3:
        if any(len(w) >= 6 and w.endswith(("misan", "misiz", "yapman", "yapsan", "dingmi", "asanmi", "dagi", "larni", "ikni", "ingni",
                                           "imni", "ngizni")) for w in words):
            return "uz"  # "Uydamisan", "kelyapsan": the ending gives it away
        return "en"  # nothing recognized and short: treat as English
    try:  # longer: English if most words are in the system dictionary or common chat English
        from .judge import _is_english, _load_words
        _load_words()
        real = [w for w in words if len(w) >= 3]  # two-letter "words" exist in every language
        if real and sum(_is_english(w) for w in real) >= len(real) * 0.7:
            return "en"
    except Exception:
        pass
    return "other"


def base(code: str | None) -> str | None:
    return code.split("-")[0] if code else None
