# Beacon Console

Read-only remote console for your Discord bot server PC.

## Deploy on Vercel

1. Go to https://vercel.com/new
2. Import **loganstorm1254-sudo/link**
3. Framework: Next.js (auto)
4. Add env var: `SESSION_SECRET` = a long random string
5. Optional: `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`
6. Deploy

## PC bridge

Run BeaconConsoleBridge.exe on your server PC, enter the Vercel URL + username/password + `py smmod.py`.

Website is view-only — no typing, no remote shell.
