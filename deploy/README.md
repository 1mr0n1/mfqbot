# Moving the bot to an always-on server

On a laptop the bot stops when the lid closes. A small rented Linux server (1 CPU, 1–2 GB RAM, about $4–5 a month
at Hetzner, DigitalOcean, Vultr and the like — Ubuntu 24.04) keeps it running around the clock. The replies come
from hosted models, so the server needs no GPU.

## Steps

1. **Rent the server** and make sure you can `ssh user@server`.
2. **On the server:** `sh setup_server.sh <git clone URL>` (this folder's script). It installs everything and
   registers the three services, without starting them.
3. **On the Mac:** stop the local copy — `sh scripts/services.sh stop` — then `sh deploy/push_data.sh user@server`.
4. **On the server:** edit `~/mfqbot/.env`: remove `local` from `USERBOT_MODELS`, `USERBOT_JUDGE_MODELS` and
   `USERBOT_PHOTO_MODELS` (there is no LM Studio there).
5. **Log the account in** on the server: `cd ~/mfqbot && .venv/bin/python -m userbot.login` (phone, code, 2FA).
6. **Start:** `sudo systemctl start mfqbot-backend mfqbot-userbot mfqbot-bot`.
7. **Dashboard address:** install Tailscale on the server (`curl -fsSL https://tailscale.com/install.sh | sh`,
   `sudo tailscale up`, `sudo tailscale funnel --bg 8000`) and open the dashboard once with
   `https://<your dashboard>/#api=https://<server name>.<tailnet>.ts.net`. `ADMIN_TOKEN` and `ADMIN_ORIGINS` in
   `.env` stay as they are.

## Day to day

| | |
|---|---|
| status | `systemctl status mfqbot-userbot` |
| logs | `journalctl -u mfqbot-userbot -f` |
| restart after a change | `cd ~/mfqbot && git pull && sudo systemctl restart mfqbot-backend mfqbot-userbot mfqbot-bot` |
| stop everything | `sudo systemctl stop mfqbot-userbot mfqbot-bot mfqbot-backend` |

## What is different on a server

- **No local model.** The `local` fallback and anything using it is gone; hosted models do all the work.
- **Voice messages** are transcribed on the server's CPU: fine for short messages, slow for long ones on the
  smallest machines. `WHISPER_MODEL=base` in `.env` is faster and less accurate than `small`.
- **Backups:** `scripts/backup.sh` is written for macOS (Keychain, iCloud). On a server, copy `~/mfqbot/userbot`
  somewhere else on a schedule, or keep the Mac as the backup by pulling the data back with rsync.
- **Never run the account in two places at once.** Stop one copy before starting the other.
