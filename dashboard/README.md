# Admin dashboard as a website (Vercel)

The page in this folder is a static site. It holds no data and no secrets: it only talks to **your** backend,
using an address and a token you type into it (stored in that browser only).

```
phone / tablet ──> https://your-panel.vercel.app   (this static page)
       │
       └── API calls ──> https://your-tunnel…  ──tunnel──>  backend on your Mac (127.0.0.1:8000)
```

## What is protected

- From outside your Mac the backend answers **only** `/admin/*`, and only with `ADMIN_TOKEN`
  (`Authorization: Bearer …`). `/chat`, `/complete` and everything else return 403 from outside.
- With no `ADMIN_TOKEN` in `.env`, remote access is off entirely.
- Browsers may only call the backend from the sites listed in `ADMIN_ORIGINS`.
- The dashboard can send messages from your Telegram account. Treat the token like a password; if it leaks,
  change it in `.env` and restart the backend.

## One-time setup

1. **Deploy the page**
   ```bash
   npm i -g vercel
   vercel login
   cd dashboard && vercel --prod        # note the https://….vercel.app address it prints
   ```
2. **Allow that site and set the token** in the project's `.env`:
   ```
   ADMIN_TOKEN=<long random string>     # e.g. python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ADMIN_ORIGINS=https://<your-site>.vercel.app
   ```
   then restart the backend.
3. **Open a tunnel to the backend** (the Mac must be on and the backend running):
   ```bash
   brew install cloudflared
   cloudflared tunnel --url http://127.0.0.1:8000     # prints an https://….trycloudflare.com address
   ```
   A quick tunnel gets a new address every time it starts; a named Cloudflare tunnel (or Tailscale Funnel)
   gives you a permanent one.
4. **Connect** — open the Vercel site on your phone, tap ⚙︎, paste the tunnel address and the token.

## If the Vercel project is connected to the GitHub repo

Then every push redeploys the site from the repository. The `vercel.json` at the repository's top level tells
Vercel to serve this `dashboard/` folder (`outputDirectory`); without it the site would be an empty 404.
Keep `dashboard/index.html` in sync with `backend/admin.html` (`dashboard/sync.sh`) before pushing.

## Updating the site

After changing `backend/admin.html`: `dashboard/sync.sh && cd dashboard && vercel --prod`.

## Phone tips

On iPhone/iPad: Share → *Add to Home Screen* gives a full-screen app-like icon.
