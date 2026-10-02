#!/bin/sh
# Copies what is NOT in git from this Mac to the server: .env and your private data (facts, people, learned style,
# state, lessons, clips, chat exports). Run it ON THE MAC:   sh deploy/push_data.sh user@server
#
# The Telegram login (userbot/account.session) is not copied: log in again on the server with
#   .venv/bin/python -m userbot.login
# so the session on the Mac and the one on the server stay separate.
set -e
DEST="${1:?usage: sh deploy/push_data.sh user@server}"
cd "$(dirname "$0")/.."
items=""
for f in .env userbot/facts.md userbot/state.json userbot/lessons.json userbot/clips.json userbot/daylog.json \
         userbot/memory userbot/style chat-histories; do [ -e "$f" ] && items="$items $f"; done
# shellcheck disable=SC2086
rsync -avR --progress $items "$DEST:mfqbot/"
echo "Copied. On the server, check .env: LOCAL_LLM_URL / the 'local' model are not available there —"
echo "set USERBOT_MODELS and USERBOT_JUDGE_MODELS without 'local' (for example: deepseek,gemma,nemotron)."
