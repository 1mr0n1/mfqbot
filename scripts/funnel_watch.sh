#!/bin/sh
# Keeps the Tailscale Funnel in front of the backend alive.
#
# After the Mac changes network or wakes up, Tailscale's public entry points can keep refusing connections
# although `tailscale funnel status` still says "on". Re-creating the funnel fixes it, so this loop tests the
# public address through every entry point once a minute and re-creates the funnel when all of them fail three times
# in a row.   Run:  nohup sh scripts/funnel_watch.sh >> funnel_watch.log 2>&1 &
TS="${TAILSCALE:-/Applications/Tailscale.app/Contents/MacOS/Tailscale}"
PORT="${PORT:-8000}"
HOST=$("$TS" status --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))') || exit 1
[ -n "$HOST" ] || { echo "Tailscale is not running"; exit 1; }
echo "$(date '+%F %T') watching https://$HOST"
bad=0
while true; do
  sleep 60
  curl -s -m 4 -o /dev/null "http://127.0.0.1:$PORT/health" || continue          # backend down: not the funnel's fault
  curl -s -m 6 -o /dev/null https://www.gstatic.com/generate_204 || continue      # no internet: nothing to fix
  ips=$(dig +short +time=4 +tries=1 A "$HOST" @ns1.dnsimple.com | grep -E '^[0-9.]+$')
  total=0; failed=0
  for ip in $ips; do
    total=$((total + 1))
    code=$(curl -s -m 10 -o /dev/null -w '%{http_code}' --resolve "$HOST:443:$ip" "https://$HOST/health")
    [ "$code" = 000 ] && failed=$((failed + 1))
  done
  if [ "$total" -eq 0 ] || [ "$failed" -eq "$total" ]; then bad=$((bad + 1)); else bad=0; fi
  if [ "$bad" -ge 3 ]; then
    echo "$(date '+%F %T') $failed of $total entry points fail — re-creating the funnel"
    "$TS" funnel reset >/dev/null 2>&1; sleep 2; "$TS" funnel --bg "$PORT" >/dev/null 2>&1
    bad=0; sleep 60
  fi
done
