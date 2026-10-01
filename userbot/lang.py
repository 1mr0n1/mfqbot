"""Tiny language detector for the three languages the account chats in: Uzbek, Russian, English."""
import re

UZ_CYRILLIC = set("ўқғҳЎҚҒҲ")
# Common Uzbek (Latin) chat words that aren't English or transliterated Russian words.
UZ_WORDS = {
    "salom", "assalomu", "alaykum", "qalaysan", "qalaysiz", "qalay", "yaxshi", "yaxshimisan", "yaxshimisiz", "rahmat",
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
    if cyr > len(words) / 2:
        for code, marks in CYRILLIC_MARKS:
            if set(marks) & set(text):
                return code
        return "ru"
    uz = sum(w in UZ_WORDS or "o'" in w or "g'" in w for w in words)
    weak = sum(w in UZ_WEAK for w in words)
    if uz or (weak and not EN_STOP & set(words)):  # weak words only count when it doesn't look like English
        uz += weak
    scores = {code: sum(w in vocab for w in words) for code, vocab in LATIN_WORDS.items()}
    scores["uz"] = uz * 2  # home languages win ties
    scores["ru-latn"] = sum(w in RU_TRANSLIT for w in words) * 1.5
    best = max(scores, key=scores.get)
    # One shared word isn't enough to name a foreign language in a longer message.
    if scores[best] and (best in ("uz", "ru-latn", "en") or scores[best] >= 2 or len(words) < 3):
        return best
    if len(words) < 3:
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
