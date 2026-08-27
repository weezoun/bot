# v2.15 — 2026-08-25

Previous version: [v2.14](../v2.14/NOTES.md)

## What changed since v2.14

### 1. Duplicate-process singleton lock (real infrastructure bug, not a rule/SL change)

**Background:** the user reported what looked like a LOCKED Rule 1 violation
— a trade opened ~37s after a bot restart, inside the same M15 candle
(2026-08-24, USA30, ticket 1298580633). Investigated thoroughly:
- Measured the exact broker/local clock offset (~10790s) and converted the
  position's open time to local wall-clock time to confirm the timing.
- Confirmed `time == time_update` on the position (rules out a stale
  trailing-edit misreading).
- Re-read Rule 1's gate logic (`bot_runner.py`, `startup_bar_time`/
  `startup_gate_cleared`) end to end — reads correct on static analysis.
- Live-reproduced a clean restart and watched it behave correctly: no
  fresh entry fired inside the same candle for any of the 6 symbols.
- **While investigating a separate issue** (the Scheduled Task
  intermittently failing with `ERROR_NO_SUCH_LOGON_SESSION`), directly
  observed TWO `pythonw.exe` processes running simultaneously after a
  Stop/Start-ScheduledTask retry — the old process hadn't actually died
  before the new one launched.

**Root cause (most likely explanation for the original report):** a
restart that fires before the OLD process has fully exited leaves two live
bot instances for a window. The OLD one's Rule 1 gate had already cleared
long ago (from whenever IT started), so it kept trading completely
normally — from the outside this looks exactly like "the bot just
restarted and immediately took a trade, bypassing Rule 1," when Rule 1
itself was never actually violated by any single process. This is a
process-management bug, not a Rule 1 logic bug — Rule 1 itself is
untouched.

**Fix:** `app.py` now acquires an OS-level exclusive lock (`bot.lock`, via
`msvcrt.locking()`) on a single fixed byte the instant the process starts,
before `connect_mt5()` or any bot thread runs. Windows releases file locks
automatically the instant a process exits or is killed — even a crash —
so this needs no stale-PID cleanup logic: a second launch just fails fast
with a clear message in `task_err.log` instead of silently running
side-by-side with a live instance.

**Bug caught in my own first attempt, fixed before deploying:** the first
version opened the lock file in `"a+"` mode, whose write position floats
to EOF — two processes ended up locking two *different* bytes (no
conflict), so the intended `sys.exit(1)` path never fired; instead the
second process crashed later and messily at `.flush()` with an unrelated-
looking `PermissionError`. Fixed by opening in `"r+b"` and calling
`.seek(0)` explicitly right before `msvcrt.locking()`, so every process
contends for the exact same byte. Verified live both ways: launched a
second instance manually — it now exits within ~1s with the clean "FATAL:
another bot process already holds bot.lock" message, and only the
original process remains running.

**IMPACT:** eliminates a real reliability gap (silent duplicate trading
processes) uncovered directly during this investigation. No behavior
change for the normal single-instance case.

### 2. USA100 Rule 2 (WITH_TREND) SL reverted 15 → 30

Full history on this one value: 30 (original) → 2026-08-21 tried 15 →
tried 50 → settled back at 15 (v2.13) → ran live ~4 days → checked real
stats.

**Stats checked at save time** (USA100, since 2026-08-21 00:00, the full
15.0-SL period):

| Mode (rule) | Trades | Win% | Total P/L |
|---|---|---|---|
| WITH_TREND (Rule 2) | 116 | 44.0% | **-612.42** |
| COUNTER_SCALP (Rule 5/7) | 22 | 45.5% | -59.65 |

**REASON (user's words):** "USA100 ka with_trend ka sl wapis se 30 per
kerdo, 15 per kerne ka koi faida nahi ho raha hai, hum ne 50 bhi kia koi
faida nahi hoa, 15 bhi kia no faida, lekin 30 per atleast kuch faida hoa
tha to dobara set ker k dekho kuch din wahan per chala ker dekhta hon."

**IMPACT:** back to the original, larger per-stop-out loss on Rule 2, but
30 is the one value with an actual track record of net benefit for this
symbol/rule — trading smaller-loss-per-stop (15/50) for real
profitability (30). Does not touch Rule 4's separately-diagnosed
rapid-reentry pattern (v2.13) — unrelated lever.

**NOTE FOR NEXT TIME THIS IS RECONSIDERED:** 15, 30, and 50 have ALL now
been tried on this exact value with real stats checked each time — 30 is
the only one with a positive track record. That's 3 data points already
spent; look for a different lever (e.g. Rule 4's own gate, or a real
config/data-driven brainstorm) before trying a 4th SL number on this same
rule.

## Baseline at save time

- `stats/trade_history_at_v2.15_save.db` — snapshot taken 2026-08-25 at
  restart, immediately after both changes deployed and verified live.
- Live-restart verification: single clean process only (confirmed via
  `Get-Process pythonw`), lock file held (`bot.lock` — confirmed
  `Device or resource busy` when a second process tried to read it),
  Scheduled Task `LastTaskResult = 267009` (SCHED_S_TASK_RUNNING).

## Next version

[v2.16](../v2.16/NOTES.md) — Rule 4 (WITH_TREND SL re-entry gate) given a
real minimum cooldown (180s) after a live XAUUSD case of rapid-fire
same-second re-entries following an SL close.
