# v2.16 — 2026-08-27

Previous version: [v2.15](../v2.15/NOTES.md)

## What changed since v2.15

### Rule 4 (WITH_TREND SL re-entry gate) — real minimum cooldown added

**User's report** (XAUUSD, verbatim): "ager xauusd ki last 15 trades dekho
to woh with_trend sl se close kerta hai phir foran hi phir se with_trend
ki trade hi open ker deta hai" — a WITH_TREND SL close immediately followed
by a fresh WITH_TREND entry on the same side, over and over.

**Confirmed with real data** — XAUUSD, 2026-08-27, 18:49-19:00 (about 11
minutes): 12 WITH_TREND SELL trades, most re-opened within 0-20 seconds of
the previous one's SL close (several literally the SAME second — e.g.
closed 18:49:15 → reopened 18:49:16; closed 18:49:25 → reopened 18:49:25;
closed 18:49:42 → reopened 18:49:42). Net result of this one burst:
**-604.00**.

**Root cause**: Rule 4's gate clears via two paths, neither of which had
any time floor —
1. FAST path: that side's DI crosses back above the benchmark captured
   AT THE MOMENT OF THE SL. A single noisy tick right after a stop-out
   can satisfy this trivially, since the benchmark is essentially
   "wherever DI already was."
2. SLOW path: rolling DI rising + forming candle the right color — also
   satisfiable on a single favorable tick.

Neither path is wrong in isolation (both were deliberate, reasoned design
from earlier versions — see v2.5's history) — the missing piece was any
minimum time for the SL'd move to actually prove itself before either
path is even evaluated.

**Fix**: `config.RULE4_MIN_COOLDOWN_SECONDS` (180s, global — applies to
all 6 symbols since Rule 4 is one shared mechanism). `rule4_gate` now
records `sl_time` (wall clock) the moment the SL fires; `_check_rule4_gate`
returns immediately, without evaluating EITHER path, until 180s have
elapsed. **Rule 3 (WITH_TREND TP close) is completely unaffected** — per
the user's explicit instruction, only the SL side needed a wait; a
profitable close should keep behaving exactly as before.

**User's own framing** (verbatim): "ager with_trend sl k sath close ho to
jo kaam ker raha hai woh kerta hai lekin ager sl loss may hit ho to phir
wait kare thori der, poori candle close hone ka wait nahi lekin koi
logical wait." 180s (~1/5 of an M15 candle) was picked as a starting
value — not a full-candle wait (that exact mechanism was tried and
removed in v2.2/v2.5 for blocking genuine same-candle recoveries), just a
real floor. Easy to adjust as one number once there's real before/after
data to check.

**Verified live**: restarted the bot after this change and confirmed the
new cooldown wording appears in the real live logs, e.g. (USA500):
`"Rule 4: WITH_TREND SL (BUY) — BUY-side re-entry needs 180s minimum
wait, THEN EITHER DI crossing 18.6 (benchmark) OR rolling DI rising +
forming candle definitely green"` — and confirmed all 6 symbols came up
clean (`running: true`, MT5 `connected: true`, no exceptions) via an
authenticated `/api/status` check.

**IMPACT**: should meaningfully cut the rapid-reentry "death by a
thousand small SLs" pattern seen live on XAUUSD (and, per the v2.13
investigation, the same underlying mechanism on USA100) without touching
Rule 3's already-working same-candle TP re-entry. Worth a real
before/after comparison once a few days of data exist under this change.

### Unrelated operational incident during this same deploy (documented for the record, not a code change)

While restarting the bot to deploy the above, hit a serious VPS resource
issue: free physical memory dropped to ~282MB out of 8GB (96.5%
utilized), causing `pythonw.exe`/`terminal64.exe` startup to take 10+
minutes instead of seconds (severe paging). Root process identified:
`vmmem` (the WSL2 VM, used only for the nginx reverse proxy in front of
`trading.weezoun.com`/`weezoun.com`) was holding ~3.7GB. Memory pressure
eased on its own before any WSL2-side action was taken; the bot came back
up cleanly once it did. **Not yet fixed at the infrastructure level** — a
`.wslconfig` memory cap for WSL2 would be the natural next step if this
recurs, since WSL2 here only needs to run a lightweight reverse proxy, not
3.7GB worth of workload.

## Baseline at save time

- `stats/trade_history_at_v2.16_save.db` — snapshot taken 2026-08-27 at
  restart, after the Rule 4 cooldown fix was deployed and verified live.

## Next version

(none yet)
