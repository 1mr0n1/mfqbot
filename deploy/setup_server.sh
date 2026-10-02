#!/bin/sh
# One-time setup of a fresh Ubuntu / Debian server for the bot. Run it ON THE SERVER, as a normal user with sudo:
#
#   curl -fsSL https://raw.githubusercontent.com/<you>/<repo>/main/deploy/setup_server.sh | sh -s -- <git clone URL>
#   (or copy this file over and run:  sh setup_server.sh <git clone URL>)
#
# It installs Python, clones the code into ~/mfqbot, creates the virtualenv, and registers three services
# (backend, userbot, bot) that start at boot and restart if they stop. It does NOT start them: first bring your
# private data over from the Mac (deploy/push_data.sh) and log the Telegram account in (see deploy/README.md).
set -e
REPO="${1:?give the git clone URL of your repository}"
APP="$HOME/mfqbot"

sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git ffmpeg
[ -d "$APP/.git" ] || git clone "$REPO" "$APP"
cd "$APP"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
[ -f .env ] || cp .env.example .env

unit() {  # name, module
  sudo tee "/etc/systemd/system/mfqbot-$1.service" >/dev/null <<UNIT
[Unit]
Description=mfqbot $1
After=network-online.target $3
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP
ExecStart=$APP/.venv/bin/python -m $2
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
}
unit backend backend.main ""
unit userbot userbot.main mfqbot-backend.service
unit bot bot.main mfqbot-backend.service
sudo systemctl daemon-reload
sudo systemctl enable mfqbot-backend mfqbot-userbot mfqbot-bot

cat <<DONE

Installed in $APP. Next, from your Mac:
  1. sh deploy/push_data.sh $USER@<this server>      copies .env and your private data
Then here:
  2. cd $APP && .venv/bin/python -m userbot.login     log the Telegram account in (once)
  3. sudo systemctl start mfqbot-backend mfqbot-userbot mfqbot-bot
  4. journalctl -u mfqbot-userbot -f                  watch it start
Stop the copy on the Mac first (sh scripts/services.sh stop): one account must not run in two places.
DONE
