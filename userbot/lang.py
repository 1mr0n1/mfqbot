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
NAMES = {"uz": "Uzbek", "uz-cyrl": "Uzbek written in Cyrillic", "ru": "Russian",
         "ru-latn": "Russian typed in Latin letters", "en": "English"}


def _words(text: str) -> list[str]:
    text = text.lower().replace("‘", "'").replace("’", "'").replace("`", "'").replace("ʻ", "'")
    return re.findall(r"[a-zа-яёўқғҳ']+", text)


def detect(text: str) -> str | None:
    """-> 'uz' | 'uz-cyrl' | 'ru' | 'ru-latn' | 'en' | None (no letters)."""
    words = _words(text)
    if not words:
        return None
    cyr = sum(bool(re.search("[а-яёўқғҳ]", w)) for w in words)
    if cyr > len(words) / 2:
        return "uz-cyrl" if UZ_CYRILLIC & set(text) else "ru"
    uz = sum(w in UZ_WORDS or "o'" in w or "g'" in w for w in words)
    weak = sum(w in UZ_WEAK for w in words)
    if uz or (weak and not EN_STOP & set(words)):  # weak words only count when it doesn't look like English
        uz += weak
    ru = sum(w in RU_TRANSLIT for w in words)
    if uz and uz >= ru:
        return "uz"
    if ru:
        return "ru-latn"
    return "en"


def base(code: str | None) -> str | None:
    return code.split("-")[0] if code else None
