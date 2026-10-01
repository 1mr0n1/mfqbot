"""Recall: how did you really answer when someone wrote something like this before?

A small lexical search (rarity-weighted word overlap + character trigrams, no model, no network) over the
"they wrote → you answered" exchanges taken from your chat exports. The closest real exchanges are shown to the
model for every reply, so its answer is anchored in things you actually said in that situation instead of in
generic style rules.
"""
import math
import re
from collections import Counter

_cache: dict[tuple, "Index"] = {}


def tokens(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+(?:['ʻ‘’][^\W\d_]+)*", text.lower().replace("ё", "е"))


def trigrams(text: str) -> set[str]:
    t = " ".join(tokens(text))
    return {t[i:i + 3] for i in range(len(t) - 2)} if len(t) >= 3 else ({t} if t else set())


def norm(text: str) -> str:
    return " ".join(tokens(text))


class Index:
    def __init__(self, pairs: list[dict]):
        self.pairs = pairs
        self.words = [set(tokens(p["them"])) for p in pairs]
        self.tris = [trigrams(p["them"]) for p in pairs]
        df = Counter(w for ws in self.words for w in ws)
        self.idf = {w: math.log(1 + len(pairs) / c) for w, c in df.items()}
        self.rare = math.log(1 + len(pairs))  # weight of a word never seen before

    def search(self, query: str, k: int) -> list[tuple[float, dict]]:
        """-> up to k (score, pair), most similar first, with different answers (no duplicates of the same reply)."""
        qw, qt = set(tokens(query)), trigrams(query)
        if not qw:
            return []
        weight = lambda ws: sum(self.idf.get(w, self.rare) for w in ws)
        qweight = weight(qw)
        scored = []
        for i in range(len(self.pairs)):
            common = qw & self.words[i]
            shared_tris = len(qt & self.tris[i])
            if not common and not shared_tris:
                continue
            words = weight(common) / (qweight + weight(self.words[i] - qw))       # rarity-weighted Jaccard
            chars = shared_tris / max(len(qt | self.tris[i]), 1)
            score = 0.7 * words + 0.3 * chars
            if score > 0.1:
                scored.append((score, i))
        scored.sort(reverse=True)
        out, seen = [], set()
        for score, i in scored:
            key = norm(self.pairs[i]["me"])
            if key in seen:
                continue
            seen.add(key)
            out.append((score, self.pairs[i]))
            if len(out) >= k:
                break
        return out


def index_for(key: tuple, pairs: list[dict]) -> Index:
    """Build once per (file, modification time, number of visible pairs)."""
    full = (*key, len(pairs))
    if full not in _cache:
        if len(_cache) > 12:
            _cache.clear()
        _cache[full] = Index(pairs)
    return _cache[full]


MIN_SCORE = 0.5        # below this the "similar" message is about something else, and its answer misleads
MIN_QUERY_LETTERS = 9  # "ok", "idk", "ааа": what you answered depended on the moment, not on the words


def block(index: Index, incoming: str, k: int) -> tuple[str, list[dict]]:
    """Text for the prompt + the pairs used (so the caller can avoid showing them twice)."""
    if k <= 0 or sum(len(t) for t in tokens(incoming)) < MIN_QUERY_LETTERS or len(tokens(incoming)) < 2:
        return "", []
    hits = [(s, p) for s, p in index.search(incoming, k) if s >= MIN_SCORE]
    if not hits:
        return "", []
    lines = [f"THEM: {p['them'].replace(chr(10), ' / ')}\nYOU: {p['me'].replace(chr(10), ' / ')}" for _, p in hits]
    text = ("\nPeople wrote almost the same thing to you before; this is what you actually answered then (most similar "
            "first). Take the manner from it — length, tone, the kind of answer. The facts in those answers (names, "
            "places, times, things) belonged to that moment: do not reuse them now.\n" + "\n".join(lines) + "\n")
    same = [p["me"].replace("\n", " / ") for s, p in hits if s >= 0.8]
    if len(same) >= 2:
        text += ("They have written exactly this to you before; your real answers were: "
                 + " | ".join(f"“{m}”" for m in same[:4]) + "\n")
    return text, [p for _, p in hits]
