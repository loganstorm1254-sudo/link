# Beacon Console

Read-only remote console for your Discord bot server PC.

Your bot folder should look like:

```
smmod/
  smmod.py
  (other bot files…)
```

## Deploy on Vercel

1. Go to https://vercel.com/new
2. Import **loganstorm1254-sudo/link**
3. Framework: Next.js (auto)
4. Add env var: `SESSION_SECRET` = a long random string
5. Optional: `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`
6. Deploy

## PC bridge

1. Run BeaconConsoleBridge.exe (or `py bridge.py`)
2. Enter Vercel URL + username/password
3. Enter path to your **smmod folder** (the folder that contains `smmod.py`)
4. Command stays `py smmod.py` (runs inside that folder)

Website is view-only — no typing, no remote shell.
