"""Download an Uzbek word list, so that real Uzbek words are not mistaken for made-up ones.

  .venv/bin/python -m userbot.get_uz_dictionary

Models invent plausible-looking Uzbek. The account's check for that used to know only the words from your own
chats, so it also threw out correct words you simply never typed — and then answered in Russian instead. This
fetches the open Uzbek spelling dictionary (github.com/u2b3k/uz-hunspell, GPL-3.0; Latin and Cyrillic, about
95,000 word stems each) into userbot/style/uz_dictionary.txt. The file stays on this machine (git-ignored).
"""
import re

import httpx

from . import config as C

SOURCE = "https://raw.githubusercontent.com/u2b3k/uz-hunspell/master/{}"
FILES = ("uz_UZ.dic", "uz_UZ_Cyrl.dic")
PATH = C.STYLE_DIR / "uz_dictionary.txt"


def plain(word: str) -> str:
    """One spelling for the many apostrophes of Uzbek (oʻ, o‘, o’, o`), lower case."""
    return re.sub("[ʻ‘’`ʼ]", "'", word.strip().lower())


def main():
    words: set[str] = set()
    for name in FILES:
        resp = httpx.get(SOURCE.format(name), timeout=60, follow_redirects=True)
        resp.raise_for_status()
        lines = resp.text.splitlines()[1:]  # the first line is the count
        for line in lines:
            word = plain(line.split("/")[0])
            if len(word) >= 3 and re.fullmatch(r"[^\W\d_]+(?:['-][^\W\d_]+)*", word):
                words.add(word)
                words.add(word.replace("'", ""))  # people type o'qish as oqish
        print(f"{name}: {len(lines)} entries")
    C.STYLE_DIR.mkdir(exist_ok=True)
    PATH.write_text("\n".join(sorted(words)))
    print(f"{len(words)} word forms -> {PATH}")


if __name__ == "__main__":
    main()
