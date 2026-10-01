"""Build simulator scenarios from real chat exports: what people actually wrote to you, the conversation before
it, and what you really answered (the reference the bot's reply is compared with).

  .venv/bin/python -m userbot.sim_from_exports config.json out.json

config.json: {"me": "YourNameInExports", "me_profile": {"first_name": "..."}, "per_chat": 20, "seed": 1,
              "chats": {"ChatExport_X": {"first_name": "...", "username": "..."}, ...}, "folder": "chat-histories"}
The sampled exchanges are listed under "holdout" so the simulator hides them from the bot's few-shot examples.
"""
import json
import random
import sys
from pathlib import Path

from .import_export import PRIVATE_RE, parse_export
from .learn_style import URL_RE, usable


def turns_of(dialog: list[dict]) -> list[dict]:
    """Group consecutive messages by author: [{"author", "texts", "clean"}] (clean = text only, nothing private)."""
    turns: list[dict] = []
    for msg in dialog:
        ok = bool(msg["text"]) and not msg["media"] and not URL_RE.search(msg["text"]) and usable(msg["text"]) \
            and not PRIVATE_RE.search(msg["text"])
        if turns and turns[-1]["author"] == msg["author"]:
            turns[-1]["texts"].append(msg["text"])
            turns[-1]["clean"] &= ok
        else:
            turns.append({"author": msg["author"], "texts": [msg["text"]], "clean": ok})
    return turns


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    me, rng = config["me"], random.Random(config.get("seed", 1))
    contacts, scenarios, holdout = {}, [], []
    for folder, spec in config["chats"].items():
        files = sorted(Path(config.get("folder", "chat-histories"), folder).glob("messages*.html"),
                       key=lambda p: (len(p.name), p.name))
        turns = turns_of([m for f in files for m in parse_export(f)])
        candidates = [i for i in range(4, len(turns) - 1)
                      if turns[i]["author"] != me and turns[i + 1]["author"] == me
                      and turns[i]["clean"] and turns[i + 1]["clean"] and len(turns[i]["texts"]) <= 3
                      and all(len(t) <= 140 for t in turns[i]["texts"]) and len(turns[i + 1]["texts"]) <= 3
                      and len(" ".join(turns[i + 1]["texts"])) <= 70]
        key = folder.replace("ChatExport_", "")
        contacts[key] = spec
        for i in rng.sample(candidates, min(config.get("per_chat", 20), len(candidates))):
            history = []
            for t in turns[max(0, i - 6):i]:
                if t["clean"]:
                    history += [[text, t["author"] == me] for text in t["texts"]]
            reference = "\n".join(turns[i + 1]["texts"])
            scenarios.append({"id": len(scenarios) + 1, "who": key, "tag": "real", "history": history[-10:],
                              "turns": [turns[i]["texts"]], "reference": reference})
            holdout += turns[i + 1]["texts"]
    Path(sys.argv[2]).write_text(json.dumps({"me": config.get("me_profile", {}), "contacts": contacts,
                                             "scenarios": scenarios, "holdout": holdout}, ensure_ascii=False, indent=1))
    print(f"{len(scenarios)} scenarios from {len(contacts)} chats -> {sys.argv[2]}")


if __name__ == "__main__":
    main()
