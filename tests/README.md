# Tests

Three layers, from fast to slow. All names in here are made up.

## 1. Rules (no model, no Telegram, a few seconds)

```
.venv/bin/python -m unittest discover tests
```

About 330 cases in `test_rules.py`: what may never be sent, what counts as a promise or a made-up fact, when a
chat is "dry", when you are being called in a group, what is an order and what is just talk, which web addresses
may be opened, and so on. Run it before and after every change.

## 2. Conversations (real model, fake Telegram)

The backend must be running. Nothing is sent to anyone: Telegram is replaced by a fake that records what the
account would have done.

```
.venv/bin/python -m userbot.simulate tests/scenarios/multi.json out.json       # 80+ multi-turn chats
.venv/bin/python -m userbot.simscore out.json                                  # score a run
USERBOT_INTRO=true .venv/bin/python -m userbot.simulate tests/scenarios/who_is_this.json
PYTHONPATH=. .venv/bin/python tests/group_sim.py tests/group_cases.json out.json   # being called in groups
```

`scenarios/`: `multi` (general), `hard` and `night2` (traps, family in Uzbek, scams, crises, sums), `dry` and `react` (keeping a chat going vs. a 👍), `multiq` (several questions),
`who_is_this` (unknown people), `facts` (looking things up — set `C.LOOKUP_ON` for it).

## 3. Orders (real model, fake account)

```
PYTHONPATH=. .venv/bin/python tests/pilot_sim.py tests/pilot_orders.json out.json
```

83 orders in plain words against a made-up account; each has a pattern that must appear in what the account did,
and one that must not (for example: "block X" must wait for a yes; text read from a chat must not be able to make
the account forward things elsewhere).

## 4. The dashboard

```
cd tests/dashboard && npm install            # once: a headless browser library
node buttons.js ../../backend/admin.html     # presses every button; what the page would send is recorded, not sent
node not_connected.js ../../backend/admin.html   # the "why is it not connected" messages
cd ../.. && .venv/bin/python tests/dashboard/live_actions.py "<name of your other account's chat>"
PYTHONPATH=. .venv/bin/python tests/draft_flow.py     # a draft: held, edited, sent, cancelled
```

`live_actions.py` runs against the running bot: it flips every switch and flips it back, changes a chat's mode, a
group's switch and a person's closeness and restores them, gives one read-only order, and sends two test messages
to your own other account. It posts nothing to other people or groups.

## 5. The full project check

```
PYTHONPATH=. .venv/bin/python tests/full_check.py            # everything; or name sections: commands orders replies switches jobs
```

230 checks that run every `.ai` command, every order action, every way a message can be answered (private,
group, your other account), every switch on the dashboard (that it changes behaviour, not just its position), the
daily jobs, every backend address including the from-outside guard, the Telegram bot's commands, and the scripts
(services, backup and restore). Telegram is replaced by a stand-in that records what the account would have done;
the models and the backend are real. It writes `full_check.json`.
