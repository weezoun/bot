# Chat history — VPS MDRDP-1267 deployment (2026-10-08 → 2026-10-10)

Paste this file into a new Claude Code window on the next VPS to restore
context. Written as a handoff: what was done, why, what broke along the
way, and exactly how to redeploy. **No secrets are in this file** (repo is
on GitHub) — see "Secrets" below for where each one comes from.

## Background

- User moved to a new Claude account; older chat context was lost. The
  project itself carries its own standing context in `CLAUDE.md`,
  `docs/current_strategy.md`, `versions/INDEX.md` — read those first.
- 2026-10-08: the demo bot was brought up on a fresh Windows Server 2022
  VPS, hostname **MDRDP-1267**, IP **216.75.142.157**, project path
  **`C:\bot-demo`** (previous VPS was ZEESHANANSARIUS / 198.44.118.152 /
  `c:\bot` with nginx inside WSL2).
- 2026-10-10: user decided to close MDRDP-1267 and move to yet another new
  VPS. This file was written + pushed before wiping MDRDP-1267.

## What was set up on MDRDP-1267 (and how)

1. **Python deps**: Python 3.14 was already installed
   (`C:\Users\Administrator\AppData\Local\Programs\Python\Python314`).
   `pip install -r requirements.txt` → MetaTrader5 5.0.6231 (has 3.14
   wheels), flask 3.1, pandas 3.0, numpy 2.5. All files `py_compile` clean.
2. **MT5** (`C:\Program Files\MetaTrader 5\terminal64.exe`) was already
   installed by the user. The bot opens it itself: `connect_mt5()` calls
   `mt5.initialize(path=...)`, which launches the terminal if not running.
3. **Scheduled Task `TradingBotAutoStart`** — trigger At logon
   (Administrator), `LogonType=Interactive`, RunLevel Highest, no time
   limit, MultipleInstances IgnoreNew. Action:
   `powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command "Start-Process -FilePath '<Python314>\pythonw.exe' -ArgumentList 'app.py' -WorkingDirectory 'C:\bot-demo' -RedirectStandardOutput 'C:\bot-demo\logs\task_out.log' -RedirectStandardError 'C:\bot-demo\logs\task_err.log' -NoNewWindow -Wait"`
4. **Public dashboard via Cloudflare Tunnel — NOT nginx.** Decided against
   nginx because: IIS came preinstalled holding 80/443; a proxied A record
   only reaches origin on 80/443 (bot is on 5050); the old WSL2-nginx setup
   had memory (vmmem) and IP-drift problems. Tunnel = no open ports, HTTPS
   by Cloudflare, runs as a Windows service.
   - cloudflared 2025.8.1 (MSI from GitHub releases), installed to
     `C:\Program Files (x86)\cloudflared\`.
   - `cloudflared tunnel login` → user authorized zone **weezoun.com** in
     their browser → `C:\Users\Administrator\.cloudflared\cert.pem`.
   - `cloudflared tunnel create demo-bot` → tunnel ID
     **0aed8dd9-3504-4caa-9179-76b800d7cddf**.
   - `cloudflared tunnel route dns --overwrite-dns demo-bot demo.weezoun.com`
     (replaced an A record the user had made pointing `demo` at the VPS IP).
   - Config for the service at
     `C:\Windows\System32\config\systemprofile\.cloudflared\config.yml`:
     ```yaml
     tunnel: 0aed8dd9-3504-4caa-9179-76b800d7cddf
     credentials-file: C:\Windows\System32\config\systemprofile\.cloudflared\0aed8dd9-3504-4caa-9179-76b800d7cddf.json
     ingress:
       - hostname: demo.weezoun.com
         service: http://127.0.0.1:5050
       - service: http_status:404
     ```
   - **Gotcha**: `cloudflared service install` registers the service with
     NO arguments → it crash-loops ("terminated unexpectedly"). Fix: set
     `HKLM:\SYSTEM\CurrentControlSet\Services\cloudflared\ImagePath` to
     `"C:\Program Files (x86)\cloudflared\cloudflared.exe" --config "<config.yml>" tunnel run`
     via `Set-ItemProperty` (`sc.exe config binPath=` mangles the quotes
     under PowerShell 5.1).
5. **`config.FLASK_HOST` changed `0.0.0.0` → `127.0.0.1`** (comment at the
   change site in `config.py`) — the tunnel reaches Flask over loopback, so
   5050 is never exposed on the public IP.
6. **Watchdog** — `tools/bot_watchdog.ps1` rewritten for this VPS: paths →
   `C:\bot-demo`, removed the live-bot (port 5051) check (no live bot on
   this machine), added a check that starts the `cloudflared` service if
   stopped. Scheduled Task `BotWatchdog` every 5 min via
   `wscript.exe tools\run_bot_watchdog_hidden.vbs` (zero-flash launcher).
7. **Auto-logon** — user changed the Administrator password (on request)
   and auto-logon was enabled with Sysinternals **Autologon64.exe**
   (Microsoft-signed, stores password as encrypted LSA secret, not
   plaintext `DefaultPassword`). If the password changes, re-run
   `Autologon64.exe /accepteula Administrator <HOST> <newpassword>` or
   auto-logon silently breaks.
8. **`.env`** (gitignored, added `.env` to `.gitignore`) held tunnel
   ID/secret/paths + VPS login. **User's standing rule: every token /
   passkey / password created must be saved in `.env`** ("baad may
   zaroorat hoti hai to milti hi nahi").
9. `CLAUDE.md` Infrastructure section rewritten for the tunnel setup;
   old WSL2/nginx/trading.weezoun.com text removed.
10. Reboot test was scheduled (`shutdown /r /t 60`) to verify auto-logon →
    bot → MT5 chain.

## Things that were blocked / left undone on MDRDP-1267

- Disabling preinstalled IIS (`W3SVC`) — blocked by Claude Code's
  permission classifier ("Modify Shared Resources"). Harmless; tunnel
  doesn't need 80/443.
- `Remove-Item` under `C:\bot-demo` was blocked by the harness ("system
  path protected"), so old `tools/wsl_nginx_startup.ps1`,
  `tools/run_wsl_nginx_startup_hidden.vbs`, `logs/wsl_nginx_startup.log`
  were left in place (unused).
- Printing tunnel credential JSON into chat was blocked ("Credential
  Materialization") — values were written to `.env` by script instead.

## Secrets — where each one comes from on the next VPS

- **MT5 login/password/server**: in `config.py` (account 49867955,
  HFMarketsGlobal-Demo).
- **Cloudflare tunnel credentials**: NOT needed from the old `.env`. On the
  new VPS: install cloudflared → `cloudflared tunnel login` (user
  authorizes weezoun.com in browser) →
  `cloudflared tunnel token --cred-file <path>\0aed8dd9-3504-4caa-9179-76b800d7cddf.json demo-bot`
  regenerates the credentials file for the SAME tunnel. DNS
  (`demo.weezoun.com` CNAME → tunnel) stays as-is in Cloudflare — user
  chose to KEEP the tunnel for reuse.
- **Dashboard admin/guest logins**: `config.DASHBOARD_ADMIN_*` /
  `DASHBOARD_GUEST_*`.
- **VPS Administrator password**: new VPS will have its own; save it in
  the new `.env` and use it for Autologon.

## Redeploy checklist for the next VPS

1. Install Python 3.14 (or 3.12/3.13) + MT5 terminal; log MT5 in once.
2. `git clone https://github.com/weezoun/bot.git C:\bot-demo` (or wherever;
   update paths in the task/watchdog/CLAUDE.md if different).
   `pip install -r requirements.txt`; `py_compile` all `.py`.
3. Create `TradingBotAutoStart` exactly as in step 3 above (fix the
   Python path).
4. cloudflared: install MSI → `tunnel login` → `tunnel token --cred-file`
   (above) → write `config.yml` (above) into
   `C:\Windows\System32\config\systemprofile\.cloudflared\` →
   `cloudflared service install` → fix ImagePath (gotcha above) →
   `Start-Service cloudflared` → test `https://demo.weezoun.com/login`.
   Make sure the OLD VPS's cloudflared is gone first, or both connectors
   will serve the same tunnel.
5. `BotWatchdog` task (5-min repeat, wscript + vbs) — update paths.
6. Auto-logon with Autologon64.exe (download from
   live.sysinternals.com, check Microsoft signature).
7. Create `.env` with every secret made along the way.
8. Restart test: reboot, wait 3-4 min, check dashboard + MT5 on desktop.

## Decommission of MDRDP-1267 (2026-10-10)

User's instruction: write this history → push to git → then remove
everything installed/created on MDRDP-1267 (tasks, cloudflared service +
files, Autologon, Python packages, project folder, credentials) and do
**not** push anything to git after that. Cloudflare tunnel `demo-bot` and
its DNS record are intentionally left in Cloudflare for reuse.

## IMPORTANT — what is NOT in git

Per the user, ONLY this history file was pushed ("git per already code
mojood hai, sirf chat history bhejo"). The code edits made on MDRDP-1267
were deleted with that VPS and are NOT in the repo — redo them on the next
VPS if the same tunnel setup is used:
- `config.py`: `FLASK_HOST = "127.0.0.1"` (repo still has `"0.0.0.0"`),
  with the comment explaining the tunnel reaches Flask over loopback.
- `.gitignore`: add `.env`.
- `tools/bot_watchdog.ps1` + `run_bot_watchdog_hidden.vbs`: paths →
  new project dir, drop the Live/5051 check, add the cloudflared service
  check (described in step 6 above).
- `CLAUDE.md` Infrastructure section: rewrite for the new VPS + tunnel
  (repo copy still describes ZEESHANANSARIUS / WSL2-nginx).
- `trade_history.db`: the repo copy is whatever was last pushed from the
  OLD VPS; trades recorded on MDRDP-1267 (2026-10-08 → 10-10) were not
  pushed. The bot's history sync re-imports closed positions from MT5
  deals (last 90 days) on startup, so they will be recovered from the
  broker.
