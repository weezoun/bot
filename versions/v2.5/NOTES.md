# Version 2.5 — saved 2026-08-13

**Previous version:** [`../v2.4/NOTES.md`](../v2.4/NOTES.md) — read that
first for the generic same-candle cap removal and the local-time
timestamp fix. This file lists ONLY what changed since that save point —
it is not a standalone history of the whole bot.

**Next version:** [`../v2.6/NOTES.md`](../v2.6/NOTES.md) — this version's
own history stops at the point described above (Rule 4 collapsed to one
check + benchmark-crossing, and the USDJPY/GBPUSD trailing-SL backward
regression fix). Read `v2.6/NOTES.md` for what changed after that:
XAUUSD's SL unified to a flat 5.00 across every mode. See
[`../INDEX.md`](../INDEX.md) for the full chain of every version.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.5_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## What changed since v2.4

### Rule 4 — redundant "wait for a new candle" removed from its own gate

User caught this live on XAUUSD: a WITH_TREND SELL hit its SL, price then
reversed straight back into the trend direction — DI rising vs. the
preceding candle, forming candle red, both genuinely true — but the bot
still hadn't re-entered several minutes later. Asked to check it and
implement the fix as its own version.

**Investigation** (done live, against the already-running process's own
`/api/status` and logs — no restart needed to diagnose):

Confirmed `_check_rule4_gate()` had TWO stacked same-candle barriers,
where only one was ever supposed to exist:

1. Rule 4's own explicit, intentional, correctly-designed "block ALL new
   entries this candle after an SL" (via `last_bar_time`, set in
   `_classify_and_record_close`'s SL branch) — confirmed correct, left
   completely untouched.
2. `_check_rule4_gate()` **itself** ALSO had `if live_snap.bar_time <=
   gate['bar_time']: return` — comparing against the EXACT SAME stored
   bar_time value as #1. This was the identical redundant-wait pattern
   found and removed from Rule 3 and Rule 6 back in v2.2 — but Rule 4
   was never checked for the same issue at the time, since the user's
   original v2.2 instruction named only Rule 3 and Rule 6 specifically.

**Effect of the redundancy**: if DI + candle color happened to align
WHILE still on the SL's own candle, that alignment was wasted — the gate
ignored it (still locked on its own bar_time check) — and once the next
candle started, the gate would only clear if DI + candle happened to
ALSO be aligned again at that exact moment, effectively requiring two
separate alignments to line up instead of one.

**Fix**: removed the redundant `bar_time` check from `_check_rule4_gate`
entirely — same shape as the Rule 3/6 fix. DI/candle confirmation can now
be satisfied at ANY time, including during the SL's own candle, and it
sticks. Actual re-entry still correctly waits for barrier #1 to lift
(Rule 4's own same-candle block, completely unchanged) — but no longer
ALSO needs a fresh DI/candle re-alignment after that candle starts.

**Also directly confirmed, not assumed**: live `-DI` was independently
observed oscillating right at its own rolling threshold during the
delay (~33.5 to 34.7, back and forth tick to tick) — genuine flat-market
behavior, not a bug, and likely contributed to part of the real-world
delay alongside the redundant-wait bug. While diagnosing, the actual
live position in question cleared and re-entered on its own (the running
process was still on pre-fix code at that point) — direct confirmation
the underlying mechanism does work correctly once conditions align, just
with unnecessary extra lag before this fix.

Verified with a standalone test reproducing the live scenario's exact
DI/candle values (di_minus=33.53 vs prior 30.65, close < open) — gate now
clears within the same candle; a control case with DI not rising
correctly stays blocked; BUY-side mirror also verified.

Dashboard's Rule 4 card and `docs/current_strategy.md` updated to
describe the fix and the now-single remaining same-candle barrier.

**Pattern for future rule-pattern fixes**: when the same design flaw gets
fixed on two rules that share a lineage with a third (Rule 3, 4, and 6
all trace back to the original shared `momentum_gate` refactor) —
explicitly check the third for the identical issue rather than assuming
"not named in this instruction" means "not affected." A fix scoped by
the user to specific rules doesn't mean siblings with the same original
bug are automatically safe.

### Follow-up 1 (same session, kept as v2.5 per direct instruction): Rule 4 collapsed to ONE check + benchmark-crossing fast path

User pushed back on the fix above: *"jab maine kaha rolling DI benchmark
cross kare to same candle par bhi trade ho sakti hai, isko apply kyun
nahi kiya... tamam rules independent banaye the, phir multiple places
par ek hi check kyun laga hua hai ek hi rule ke liye."*

Two distinct asks:
1. **Benchmark-crossing fast path** — same concept as Rule 7's own
   reversal-SL re-arm. `rule4_gate` now also records `benchmark` (the
   SL'd side's DI value at the moment of THIS SL). Clears via EITHER
   that side's DI crossing back above the benchmark (fast, no
   candle-color check) OR the existing rolling-DI + forming-candle-color
   check (slower, unchanged) — whichever comes first.
2. **Removed the duplicate check** — Rule 4's SL branch had been setting
   `last_bar_time` (a separate, generic same-candle block) ON TOP OF
   `rule4_gate`'s own presence check. User identified this as exactly the
   "same rule checked in multiple places" pattern the isolated-rules
   process forbids. `last_bar_time` set removed from Rule 4's SL branch —
   `rule4_gate` alone now governs Rule 4 (same scope as Rule 3: blocks
   only a fresh same-side WITH_TREND entry, never the opposite side or
   scalp). `last_bar_time` is now written ONLY by Rule 7's own internal
   one-tick bookkeeping.

Verified with a standalone test: benchmark-crossing alone clears the
gate even when the slower path fails; the slower path still
independently clears it when the benchmark hasn't been crossed; confirmed
no `last_bar_time` assignment remains in Rule 4's SL branch source.

### Follow-up 2 (same session): USDJPY/GBPUSD trailing SL moving BACKWARD — real bug, fixed

User: *"USDJPY aur GBPUSD mein trailing stops aage kyun nahi barh rahe,
check karo, agar masla hai to theek karo."*

Found via live logs: a BUY position's trailed SL genuinely oscillating
(`...159.388 -> 159.382 -> 159.392 -> 159.369...`) instead of only
ratcheting forward. Root cause: `trail_all_positions()`'s "never
regress" guard (`nsl > p.sl`) only checks the RAW pre-clamp candidate —
`_modify_sltp()`'s `min_dist` safety clamp runs AFTER that guard and can
silently override it. Since v2.3 flattened USDJPY's/GBPUSD's TP to small
fixed values, `lock_back` (0.3× tp_dist) is now often TIGHTER than the
broker's real minimum stop distance, so the clamp engages almost every
tick — replacing the intended trailing value with `current_price -+
min_dist`, which moves backward whenever `current_price` itself pulls
back, defeating "only ever ratchets forward" entirely.

**Fix**: added a second monotonic guard inside `_modify_sltp`, checked
AFTER the clamp (the true last point before sending) — if the post-clamp
SL would regress relative to the position's real current SL, skip
sending entirely rather than forcibly moving it backward.

Verified with a standalone test (mocked `order_send`): an engineered
clamp-regression case now sends nothing; a genuine forward improvement
still sends normally.

This was a direct, unintended side effect of v2.3's SL/TP flattening for
these two symbols — tightening one number (TP) silently broke an
assumption elsewhere (the trailing math) that had been sized off the old,
larger value.

---

## Stats baseline, refreshed after the two follow-ups above (account 49825877, demo)

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 35 | 14/21 | 40.0% | -39.89 |
| USA100 | 42 | 29/13 | 69.0% | 50.14 |
| USA30 | 40 | 20/20 | 50.0% | -552.20 |
| XAUUSD | 49 | 30/19 | 61.2% | -1019.00 |
| GBPUSD | 25 | 6/19 | 24.0% | -904.00 |
| USDJPY | 16 | 5/11 | 31.2% | 278.39 |

Overall: 207 trades, 104W/103L, win rate 50.24%, net P/L -2186.56. (Still
BEFORE this version's fixes have a real chance to show effect — the live
process needs a restart to pick up any of v2.5's changes.)

Overall: 203 trades, 102W/101L, win rate 50.25%, net P/L -1404.71.

(This baseline is BEFORE this version's fix has a real chance to show
its effect — it's this version's starting point, not its own results.
The live process was still running pre-fix code at save time; a restart
is needed to actually pick up this change.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).
