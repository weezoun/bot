# c:\bot — MT5 multi-symbol trading bot

Python/Flask bot trading 6 symbols (USA500, USA100, USA30, XAUUSD, GBPUSD,
USDJPY) on MetaTrader5, with a live web dashboard. This file is the
standing context for working on this project — read it before making any
change. Detailed, per-rule technical reference lives in
`docs/current_strategy.md`; full version-by-version change history (every
value tuned, every bug fixed, with REASON + IMPACT for each) lives in
`versions/INDEX.md` and each version's own `NOTES.md`. This file is the
map to those, plus everything that doesn't live in code/docs at all —
working conventions, infra quirks, and standing instructions.

**The user communicates in mixed Urdu/English (Roman Urdu).** Reply in
whatever mix they use — don't switch to English-only by default.

## The single most important constraint

**A numbered rule, once implemented, must NEVER be modified again without
the user's explicit permission.** Treat this as inviolable. If a request
seems to require touching an already-locked rule's behavior, flag it and
ask before changing it — don't proceed on inference. The user has broken
this exact plan themselves multiple times when they had new evidence (see
Rule 4's cooldown fix, USA100's Rule 2 SL history) — that's fine, it's
their call to make, not something to pre-empt.

**Every rule's logic must be a fully ISOLATED function/state** — no shared
function, no shared dict with a distinguishing tag, no branching on
"which rule called this." Each rule that owns a gate gets its own state
field (`rule3_gate`, `rule4_gate`, ...) and its own dedicated clearing
method, fully self-contained. Rules may only interact through trivial
one-line state READS (a bare presence/side check) — never by calling into
or computing from another rule's logic. Duplicated code across rules is
the *accepted tradeoff*, not a DRY violation to fix. Before implementing
any new rule: "if I later edit ONLY this rule's function, is it
physically impossible for any other rule's behavior to change?" If not,
restructure until it is.

This isolation boundary is about **code and state only** — diagnostic
log/reason text that names another rule (e.g. "Rule 4 gate active") is
fine and should stay; it's what makes the live dashboard/logs legible.
Comments explaining design lineage between rules are fine too. Don't
strip rule-number mentions from text; do keep the actual code/state fully
separate.

When discussing/fixing one rule, stay scoped to it — don't proactively
explain a different rule's mechanics even in passing, and don't add
adjacent scope/caveats about related-but-different mechanisms unless
asked. If something adjacent seems relevant, ask about it separately.

## XAUUSD is frozen — excluded from all future rule/logic tuning (2026-08-29)

**XAUUSD is performing well and is not to be touched by any future
rule/logic change, experiment, or tuning pass — full stop, until the user
explicitly says otherwise.** User's own words: "xauusd acha perform ker
raha hai us may kisi change ki zaroorat nahi mazeed... sub se pehle
xauusd ko us k tamam rules k sath isolate kerdo... ab xauusd baqi sub k
rules follow nahi kare" — XAUUSD keeps trading normally (it stays in a
live/running position, nothing stops) with its CURRENT rule
values/behavior exactly as they are now; it just no longer inherits
future changes the way the other 5 symbols do. This **inverts point 1
below specifically for XAUUSD**: from now on, any rule/logic change,
unless the user names XAUUSD explicitly, applies to USA500/USA100/USA30/
GBPUSD/USDJPY only — XAUUSD is skipped by default, not included by
default. This is a standing exclusion, not a one-off — don't ask again
each time; just apply new changes to the other 5 and leave XAUUSD's
config/logic untouched unless told otherwise. REASON this was asked now:
the user is about to start a round of experiments/testing specifically
aimed at bringing the currently loss-making symbols to profit, and
doesn't want that testing to have any chance of perturbing XAUUSD's
already-working setup.

## Standing process for every rule/value change

1. Applies equally to all 6 symbols unless the user scopes it to specific
   ones — only pre-existing per-symbol numeric config (SL/TP points, ATR
   floors, trailing values) stays symbol-specific. **Exception, standing
   as of 2026-08-29: XAUUSD is excluded from this default entirely — see
   above.**
2. Numbered rules get a card on the dashboard (`templates/dashboard.html`
   + `app.py._build_rules()`) and, if the rule actually triggers/confirms
   an entry (not a pure blocking gate like Rule 1), get tagged into that
   trade's `open_reason` text ("Rule 2: ...").
3. **Every change's reasoning must be recorded, in both the inline code
   comment at the change site AND the version's `NOTES.md`**: the user's
   own stated REASON (kept close to verbatim, not paraphrased vaguer),
   and the IMPACT/trade-off it introduces — so reconsidering the same
   value later starts from what's already known instead of rediscovering
   it from scratch.
4. Before proposing a code cause for "X is losing/behaving oddly," **pull
   real trade data and find the actual inflection point first** — don't
   assume the most recent change is the culprit just because it's most
   recent, and don't reach for machine learning to "learn and fix" a
   pattern before checking whether the real data resolves into a normal,
   nameable, diagnosable rule-tuning problem (it usually does — with a
   few hundred trades total, an ML model risks overfitting to noise and
   erodes this bot's fully-explainable-by-name design).
5. **This entire project, `c:\bot`, is the DEMO bot** (`MT5_SERVER =
   "HFMarketsGlobal-Demo"`, account 49825877) — restarting it, modifying
   its code, and (per the standing exception below) restarting its own
   `pythonw.exe` process after a deployed change are all normal, expected
   parts of working here.

   **There is a SEPARATE, real "live bot" — a different system, on a
   different MT5 account/terminal, that this session does NOT own or
   maintain — completely outside this project's scope, full stop.**
   Added 2026-09-02 after a real incident: while restarting the demo bot
   across several config changes, `terminal64.exe` processes were killed
   as part of routine "clean up duplicate processes" cleanup, WITHOUT
   verifying each one's origin first — the user has their own separate
   watchdog/auto-restart system for the live bot running on this same
   machine, and there was a genuine, unresolved risk of having killed a
   process belonging to THAT system by mistake, not just the demo bot's
   own. User's own words: "tum kisi bhi surat live bot aur us se related
   terminal ya code ya process ko change nahi karo ge, woh tumhare scope
   se bahar ki cheez hai, us se door raho... demo bot ki change ko revert
   nahi karna" — demo-bot changes (this project's own config/rule/code
   work) stay exactly as made, only the live bot is the hard boundary.

   **Standing rule going forward**: never kill, restart, inspect, or
   otherwise touch ANY `terminal64.exe` process (or any other process)
   without first confirming its parent-process chain traces back to THIS
   project's own `TradingBotAutoStart` scheduled task / `pythonw.exe`
   (e.g. via `Get-CimInstance Win32_Process -Filter "ProcessId=..."` and
   walking `ParentProcessId`, or via `Get-NetTCPConnection -LocalPort
   5050` to find the port-5050 owner first). When restarting the demo
   bot, restart ONLY its own confirmed `pythonw.exe` — do NOT kill
   `terminal64.exe` as part of that routine at all; `connect_mt5()`
   already reuses an existing terminal or reconnects gracefully on its
   own (v2.14's auto-reconnect), so killing it was never necessary in the
   first place and only adds risk. If literally any doubt exists about
   whether a process belongs to this project, leave it alone and ask.

   **Incident confirmed, 2026-09-02**: investigation (via `c:\bot -
   Live\logs\watchdog.log`, `task_out.log`/`task_err.log`, and
   `Get-CimInstance Win32_Process`/`ParentProcessId` tracing — no MT5
   connection made, per the rule below) found the live bot's own
   `terminal64.exe` ("MetaTrader 5 - Live Terminal") WAS killed during
   today's demo-bot duplicate-process cleanups: the verification used at
   the time only checked "does this process hold port 5050" (the demo
   bot's port), which the live bot's terminal never holds either, so it
   looked like an orphaned duplicate under that flawed check and got
   killed by mistake. Confirmed via `c:\bot\logs\watchdog.log`: the
   user's own pre-existing `BotWatchdog` scheduled task (built 2026-08-31,
   `tools/bot_watchdog.ps1` — polls both bots' dashboards independently,
   restarts via each bot's own scheduled task on failure) detected the
   live bot down at 19:18:00 today and auto-restarted it via
   `TradingBotLiveAutoStart`; `task_out.log` confirms it reconnected to
   its terminal and resumed its loop by 19:18:38, and it has been serving
   normal traffic since. **No manual revert was needed or performed** —
   the live bot's own pre-existing watchdog self-healed it before this was
   even reported; this session made no code/config change inside `c:\bot
   - Live` at any point (only ever edited files under `c:\bot`) and took
   no further action on the live bot process once confirmed healthy, per
   the standing rule above. A second, unrelated near-miss the same day: a
   duplicate-process pair was misidentified as belonging to the demo bot
   (mistraced to `TradingBotAutoStart`) and a kill was attempted — it was
   in fact the live bot's own legitimate process, and the kill was blocked
   by Claude Code's own permission classifier before it ran.

   Verify logic changes with a standalone test before/instead of manually
   launching the bot — the user runs the live server themselves. **The
   one standing exception**: the user's keyboard has been unreliable, so
   restarting the demo bot's own `pythonw.exe` after a deployed change is
   expected of Claude now, without being asked each time — this is about
   THIS project's own process, never the separate live bot above.

   **Separately, this restart exception does NOT extend to connecting
   into the demo bot's own MT5 session** (added 2026-09-01, user's own
   words: "tum live bot per koi kaam ya changes nahi karo ge") — never
   run an ad-hoc script that calls `mt5.initialize()`/`mt5.login()` (e.g.
   to pull live prices or reconstruct historical indicator values
   directly from MT5) while the demo bot is running; that connection
   belongs to the running bot process alone. If a task seems to need this
   — even if the user asks for it directly, possibly
   by mistake — say so and don't proceed; remind them of this standing
   rule rather than silently connecting. Investigate using
   `trade_history.db`, the live dashboard's own `/api/status` (in-memory
   logs), or standalone tests against static/synthetic data instead.
6. After any code change: `python -m py_compile` (or `ast.parse`) on
   every touched file before considering it done — this project has hit
   real syntax errors (duplicate keyword args, etc.) that a compile check
   catches immediately.
7. Save a version checkpoint (`versions/v<N>/code/` + a fresh
   `trade_history.db` snapshot + `NOTES.md` with the delta since the
   previous version + a "Previous version" link) for any change worth
   remembering later, update the previous version's "Next version"
   pointer, and add a row to `versions/INDEX.md`. Ask if unsure whether a
   change counts as a new version vs. an in-place update to the current
   one (the user has explicitly asked for both, situationally).

## Project layout

- `bot_runner.py` — `SymbolBot`/`BotState`, the MT5 connection, the main
  poll loop (`bot_tick()`), order placement, trailing, rule gates.
- `strategy.py` — pure decision logic (`decide()`, `evaluate_entry()`,
  `evaluate_flip()`, SL/TP sizing) — takes an explicit `cfg`
  (`SymbolConfig`) argument rather than importing config globally, so
  multiple symbols run independently.
- `config.py` — all MT5/dashboard/global settings + one `SymbolConfig`
  instance per symbol (`config.SYMBOLS`). Edit here only, never in the UI.
- `app.py` — Flask dashboard + login/session auth + `/api/*` routes +
  the singleton-instance lock (see Infra below).
- `trade_store.py` — trade history persistence (SQLite,
  `trade_history_<MT5_LOGIN>` table).
- `docs/current_strategy.md` — the live, detailed per-rule reference,
  kept in sync with the code. Read this for what a specific rule
  currently does; this file (`CLAUDE.md`) is for how to work on it.
- `versions/INDEX.md` — one-line-per-version index of the ENTIRE change
  history from the original baseline onward. Read a specific version's
  `NOTES.md` for the full reasoning behind any past value/behavior.
- `tools/` — VPS deployment helper scripts (WSL2/nginx startup, etc.).

## Infrastructure (Windows VPS — hostname ZEESHANANSARIUS, 198.44.118.152)

**MT5 is Windows-only, period.** The `MetaTrader5` Python package talks to
a locally-running `terminal64.exe` via local IPC, not a network API —
this bot can only ever run on this Windows machine (or another real
Windows box with MT5 installed), never on Linux/WSL2/the Ubuntu VPS this
repo also gets pulled to. A Windows Service doesn't work either (Session
0 is isolated from the interactive desktop MT5 needs) — persistence is
via Windows auto-logon + a Scheduled Task (`TradingBotAutoStart`, "At
logon" trigger, `LogonType=Interactive`) running `pythonw.exe app.py`
through a `powershell -WindowStyle Hidden -Command "Start-Process ...
-RedirectStandardOutput task_out.log -RedirectStandardError task_err.log
-NoNewWindow -Wait"` wrapper (needed because raw `pythonw.exe` with no
redirected stdout crashes silently on any print).

**Known Scheduled Task flakiness**: `Start-ScheduledTask` intermittently
fails with `LastTaskResult = 2147946720` (Win32 `ERROR_NO_SUCH_LOGON_SESSION`,
4320) even with an active interactive session — root cause never fully
diagnosed. Workaround: `Stop-ScheduledTask` then `Start-ScheduledTask`
again; the retry succeeds (`LastTaskResult = 267009` / SCHED_S_TASK_RUNNING).

**Singleton-instance lock** (`app.py`, `bot.lock`, `.gitignore`d): the
process acquires an OS-level exclusive lock via `msvcrt.locking()` (byte 0
pinned) as the literal first thing in `__main__`, before `connect_mt5()`
or any bot thread starts. This exists because a restart racing before the
OLD process fully exits can leave two live instances running briefly —
the old one's Rule 1 startup gate had already cleared long ago, so it
kept trading normally, which from the outside looked exactly like "the
bot just restarted and immediately violated Rule 1" (it hadn't — see
v2.15). Windows releases file locks automatically on process exit/kill
(even a crash), so a second launch just fails fast with a clear message
instead of silently duplicating. If ever reworking this: pin the lock
byte position explicitly (`seek(0)` before `locking()`) — opening in
`"a+"` mode let two processes lock two *different* bytes and never
actually conflict, a real bug caught before it shipped.

**MT5 auto-reconnect** (`bot_runner.py`, `_maybe_reconnect()`,
30s-cooldown): `is_connected()` used to return a stale cached flag forever
— any disconnect (weekend market close/reopen, a terminal crash) left the
bot stuck logging "Not enough rate data" indefinitely until a human
restarted it. Fixed in v2.14; genuinely re-verifies and reconnects from
both `bot_tick()` failure paths.

**Public dashboard**: `https://trading.weezoun.com`, nginx running
*inside a WSL2 Ubuntu install on this same VPS*, reverse-proxying to
Flask on `198.44.118.152:5050` (WSL2 and Windows share a public IP here
but not loopback). Flask session-based login (`app.py` `/login`/
`/logout`, `config.DASHBOARD_ADMIN_*`/`DASHBOARD_GUEST_*`) — admin can
start/stop and sees the Rules section, guest is view-only. WSL2's IP can
drift after a real reboot; `tools/wsl_nginx_startup.ps1` (own Scheduled
Task, "At logon") re-detects it and re-creates the `netsh portproxy`
rules every login.

**Known WSL2 memory risk**: `vmmem` (the WSL2 VM — used ONLY for this
lightweight nginx reverse proxy) can grow to consume multiple GB on an
8GB-RAM VPS, and has been observed pushing free memory down to ~280MB,
causing `pythonw.exe`/`terminal64.exe` startup to take 10+ minutes instead
of seconds (severe paging) — this looks like a hung process but isn't; it
self-resolves once memory pressure eases, or can be fixed with a
`.wslconfig` memory cap if it recurs. Check `Get-Process | Sort
WorkingSet64 -Desc` and `Get-CimInstance Win32_OperatingSystem |
FreePhysicalMemory` before assuming a stuck bot process is a code bug.

**This VPS also hosts a completely unrelated live website, weezoun.com**
(same nginx/WSL2). Never touch its code or nginx config without explicit,
scoped permission for that specific action — this has been asked and
granted exactly once (a file-location move), otherwise hands off.

**Git remote**: `https://github.com/weezoun/bot.git` (moved here from an
earlier `zeshansari/bot`; the old repo is left alone deliberately, not
this account's job to remove). **A separate automated process on this
machine periodically auto-commits/pushes `trade_history.db`** with terse
messages like "push"/"trade history" (discovered live during a session —
its commits can land concurrently with yours; check `git fetch` +
`git log origin/main` before assuming a rejected push means real
divergence needing a merge decision — it's usually just this).

## Symbols

`config.SYMBOLS`: USA500, USA100, USA30, XAUUSD, GBPUSD, USDJPY. GBPUSD
and USDJPY currently run WITH_TREND only (Rules 1-4) — scalping (Rule
5/6/7) and FLIP are disabled on these two (`SCALPING_ENABLED`/
`FLIP_ENABLED = False`) after real data showed them as pure loss
contributors with 0% win rates (v2.9) — re-enabling either flag fully
reverts to the old behavior, no other code path needs touching.

## Communication style the user has given direct feedback on

- Give the REASON before/alongside a proposed fix, not just the fix.
- When comparing performance day-to-day, use a full per-rule
  (WITH_TREND/SCALP/REVERSAL/FLIP) breakdown table, not a single
  aggregate delta number.
- When two requested values genuinely conflict (can't both be satisfied
  under the current architecture), surface the conflict and ask, rather
  than silently picking one or guessing which takes priority.
- Don't over-literally implement a user's own illustrative
  numbers/formula when they're clearly explaining a *concept* informally
  — sanity-check the resulting edge cases, and prefer reusing an
  already-proven mechanism's shape if it captures the same intent more
  safely, flagging the substitution rather than reproducing their example
  number-for-number.
