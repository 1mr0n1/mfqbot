#!/bin/sh
# Runs the backend, the userbot and the Telegram bot as macOS launch agents: they start when you log in and are
# started again if they stop. A fourth agent keeps the Mac from sleeping while it is plugged in.
#
#   sh scripts/services.sh install     set everything up and start it (also after moving the project folder)
#   sh scripts/services.sh status      what is running
#   sh scripts/services.sh restart [backend|userbot|bot]     restart one, or all three
#   sh scripts/services.sh stop        stop everything until the next "start" (or login)
#   sh scripts/services.sh start
#   sh scripts/services.sh logs [backend|userbot|bot]        follow a log (default: userbot)
#   sh scripts/services.sh uninstall   remove the launch agents
#
# Logs: ~/Library/Logs/mfqbot/. Stop the hand-started copies first — "install" does that for you.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY="$ROOT/.venv/bin/python"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/mfqbot"
DOMAIN="gui/$(id -u)"
APPS="backend userbot bot"

plist() {  # name, then the program and its arguments
  name=$1; shift
  {
    printf '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
    printf '<plist version="1.0"><dict>\n<key>Label</key><string>com.mfqbot.%s</string>\n<key>ProgramArguments</key><array>\n' "$name"
    for arg in "$@"; do printf '  <string>%s</string>\n' "$arg"; done
    printf '</array>\n<key>WorkingDirectory</key><string>%s</string>\n' "$ROOT"
    printf '<key>RunAtLoad</key><true/>\n<key>KeepAlive</key><true/>\n<key>ThrottleInterval</key><integer>15</integer>\n'
    printf '<key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string><key>PYTHONUNBUFFERED</key><string>1</string></dict>\n'
    printf '<key>StandardOutPath</key><string>%s/%s.log</string>\n<key>StandardErrorPath</key><string>%s/%s.log</string>\n</dict></plist>\n' "$LOGS" "$name" "$LOGS" "$name"
  } > "$AGENTS/com.mfqbot.$name.plist"
}

load()   { launchctl bootstrap "$DOMAIN" "$AGENTS/com.mfqbot.$1.plist" 2>/dev/null || launchctl kickstart "$DOMAIN/com.mfqbot.$1"; }
unload() { launchctl bootout "$DOMAIN/com.mfqbot.$1" 2>/dev/null || true; }

case "${1:-status}" in
  install)
    [ -x "$PY" ] || { echo "No virtualenv at $ROOT/.venv — create it first (see README)."; exit 1; }
    mkdir -p "$AGENTS" "$LOGS"
    for app in $APPS awake; do unload $app; done
    pkill -if "python.* -m backend.main" 2>/dev/null || true; pkill -if "python.* -m userbot.main" 2>/dev/null || true
    pkill -if "python.* -m bot.main" 2>/dev/null || true; pkill -x caffeinate 2>/dev/null || true
    sleep 2
    plist backend "$PY" -m backend.main
    plist userbot "$PY" -m userbot.main
    plist bot "$PY" -m bot.main
    plist awake /usr/bin/caffeinate -is
    load backend; sleep 3; load userbot; load bot; load awake
    echo "Installed. Logs: $LOGS"; sleep 4; sh "$0" status ;;
  uninstall) for app in $APPS awake; do unload $app; rm -f "$AGENTS/com.mfqbot.$app.plist"; done; echo "Removed." ;;
  stop)      for app in $APPS; do unload $app; done; echo "Stopped (the Mac is still kept awake)." ;;
  start)     load backend; sleep 3; load userbot; load bot; load awake; sleep 3; sh "$0" status ;;
  restart)   for app in ${2:-$APPS}; do launchctl kickstart -k "$DOMAIN/com.mfqbot.$app"; done; sleep 4; sh "$0" status ;;
  logs)      tail -n 40 -f "$LOGS/${2:-userbot}.log" ;;
  status)
    for app in $APPS awake; do
      pid=$(launchctl print "$DOMAIN/com.mfqbot.$app" 2>/dev/null | awk '/^[[:space:]]*pid = /{print $3}')
      if [ -n "$pid" ]; then echo "$app: running (pid $pid)"; elif [ -f "$AGENTS/com.mfqbot.$app.plist" ]; then echo "$app: NOT running"; else echo "$app: not installed"; fi
    done ;;
  *) sed -n '2,12p' "$0" ;;
esac
