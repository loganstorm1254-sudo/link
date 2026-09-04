# Beacon Console

Read-only remote console for your Discord bot (`smmod/smmod.py`).

## Deploy / update on Vercel

1. Import **loganstorm1254-sudo/link** (or Redeploy if already linked)
2. Environment Variables (Project Settings):
   - `SESSION_SECRET` = long random string
   - `CONSOLE_USERNAME` = shared login name
   - `CONSOLE_PASSWORD` = shared login password
3. Deploy

If login says wrong password after two people use the site, you are missing
`CONSOLE_USERNAME` / `CONSOLE_PASSWORD` — add them and **Redeploy**.

## PC bridge

Download: [BeaconConsoleBridge-Windows.zip](./BeaconConsoleBridge-Windows.zip)

- Ctrl+C = stop smmod only
- `start` / Enter = run again
- `quit` = exit bridge
