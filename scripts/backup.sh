#!/bin/sh
# Encrypted nightly backup of everything that is NOT in git: your facts, the people folders, the learned style,
# the bot's state, lessons, clips, the day log, the chat exports and .env.
#
#   sh scripts/backup.sh               make a backup now
#   sh scripts/backup.sh list          show the backups
#   sh scripts/backup.sh restore FILE  unpack one into ./restored/ (never over the live files)
#   sh scripts/backup.sh passphrase    show the passphrase again
#
# Where: iCloud Drive/mfqbot-backups (falls back to ~/Backups/mfqbot if iCloud Drive can't be written). The last 14
# are kept. Each file is AES-256 encrypted with a passphrase kept in this Mac's Keychain — WRITE IT DOWN somewhere
# else too (it is printed when it is created): without it a backup can't be opened on a new Mac.
# The Telegram login (account.session) is deliberately left out: logging in again takes a minute, and a copy of it
# anywhere else is a copy of the keys to your account.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ICLOUD="$HOME/Library/Mobile Documents/com~apple~CloudDocs"
KEEP=14
SERVICE=mfqbot-backup

pass() {
  if ! security find-generic-password -s "$SERVICE" -w >/dev/null 2>&1; then
    new=$(openssl rand -base64 24)
    security add-generic-password -a "$USER" -s "$SERVICE" -w "$new" >/dev/null
    echo "A backup passphrase was created and stored in the Keychain. Save it somewhere off this Mac:" >&2
    echo "    $new" >&2
  fi
  security find-generic-password -s "$SERVICE" -w
}

dest() {
  for d in "$ICLOUD/mfqbot-backups" "$HOME/Backups/mfqbot"; do
    if mkdir -p "$d" 2>/dev/null && touch "$d/.write-test" 2>/dev/null; then rm -f "$d/.write-test"; echo "$d"; return; fi
  done
  echo "No place to write backups" >&2; exit 1
}

case "${1:-run}" in
  run)
    D=$(dest); P=$(pass); cd "$ROOT"
    items=""
    for f in userbot/facts.md userbot/state.json userbot/lessons.json userbot/clips.json userbot/daylog.json userbot/today.json \
             userbot/memory userbot/style chat-histories .env; do [ -e "$f" ] && items="$items $f"; done
    out="$D/mfqbot-$(date +%Y%m%d-%H%M).tar.gz.enc"
    # shellcheck disable=SC2086
    tar -czf - $items | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "pass:$P" -out "$out"
    ls -t "$D"/mfqbot-*.tar.gz.enc 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do rm -f "$old"; done
    echo "$(date '+%F %T') backup written: $out ($(du -h "$out" | cut -f1))" ;;
  list)       ls -lh "$(dest)"/mfqbot-*.tar.gz.enc 2>/dev/null | awk '{print $5, $6, $7, $8, $9}' ;;
  passphrase) pass ;;
  restore)
    [ -f "$2" ] || { echo "usage: sh scripts/backup.sh restore FILE"; exit 1; }
    mkdir -p "$ROOT/restored"
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "pass:$(pass)" -in "$2" | tar -xzf - -C "$ROOT/restored"
    echo "Unpacked into $ROOT/restored — copy back what you need." ;;
  *) sed -n '2,15p' "$0" ;;
esac
