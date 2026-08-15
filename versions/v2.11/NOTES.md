# Version 2.11 — saved 2026-08-14

**Previous version:** [`../v2.10/NOTES.md`](../v2.10/NOTES.md) — read
that first for the trend direction calculation fix. This file lists
ONLY what changed since that save point — it is not a standalone history
of the whole bot.

**Next version:** none yet — this is the current version. See
[`../INDEX.md`](../INDEX.md) for the full chain of every version, in
order, with a one-line summary of each.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.11_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## What changed since v2.10

### 1. Rule 7 fully decoupled from Rule 5 — architecture change

**Background**: user asked for the same per-rule (Rule 2/5/7/FLIP)
win-rate/P&L breakdown already run for GBPUSD/USDJPY (see v2.9), applied
to USA500/USA100/USA30/XAUUSD, then brainstormed specific SL cuts and
faster trailing per symbol based on that data.

Two genuine conflicts surfaced while parsing the brainstorm, both
flagged directly (per the user's own "question karo agar conflict ho"
instruction) rather than guessed at:
- **USA500**: wanted Rule 5's SL cut to 2.5 while Rule 7's stayed at
  5.00.
- **USA30**: wanted Rule 2/Rule 7 cut to 25 while Rule 5 stayed EXACT at
  50.

Both were structurally impossible under the existing architecture:
`bot_runner._reverse_scalp()` had ALWAYS called `strategy._sl_tp_scalp()`
directly, so Rule 7's SL was forced to equal whatever Rule 5's was — they
could never differ, no matter what config value was set.

User's answer, emphatic: *"har rule independent hona chahiye, koi kisi
par dependent nahi... alag mechanism banao, chota sa kaam hai, zyada
tokens na lo."*

**Change**: added `strategy._sl_tp_reversal()` — Rule 7's own, dedicated
sizing function. Checks `cfg.REVERSAL_FIXED_SL_POINTS` (a NEW config
field) FIRST; only falls back through the exact same chain
`_sl_tp_scalp()` uses (`SCALP_FIXED_SL_POINTS` → `FIXED_SL_POINTS` →
ATR-based) when a symbol hasn't been given its own reversal value — so
nothing changes for any symbol not explicitly configured this round.
`_reverse_scalp()` now calls `_sl_tp_reversal()` instead of
`_sl_tp_scalp()` directly. TP still sourced from `SCALP_TP_POINTS` — not
asked to split out independently.

### 2. Per-symbol SL split (Rule 2 / Rule 5 / Rule 7)

| Symbol | Rule 2 | Rule 5 | Rule 7 | Reasoning |
|---|---|---|---|---|
| USA500 | 5.00 (unchanged) | **2.50** (cut) | **5.00** (held, independent) | Rule 5 had most trades but only 34.8% win/-37.49; Rule 7 was the best performer (83.3%/+18.56) — cut the loser, protect the winner |
| USA100 | 30 (unchanged) | **15** (cut) | 15 (follows, no override) | Rule 2 was healthiest (75%/+44.62); Rule 5/7 both had room to improve, tightened together |
| USA30 | **25** (cut) | 50 (**held exact**, independent) | **25** (cut, independent) | The ONE symbol where Rule 2 was the biggest loser (31.2%/-435.50) and Rule 5 the best performer (75%/+181.70) — opposite pattern from every other symbol; Rule 5 deliberately untouched |
| XAUUSD | 5.00 (unchanged) | **2.00** (cut, back to pre-v2.6 value) | 2.00 (follows, no override) | Rule 5 (-1155) and Rule 7 (-575) both weak; Rule 2 (+330) clearly best |

IMPACT (recorded per the v2.8 standing practice, in full detail inline
in `config.py` for each symbol): every SL cut shrinks the loss on a
losing trade of that specific rule, but does NOT by itself improve win
rate (TP/entry logic unchanged) — the trailing changes below are the
other half of the plan, aimed at improving win rate/profit-capture
directly.

### 3. Two new trailing mechanisms (plus XAUUSD's existing one, unchanged)

- **`_trail_fixed_points()` (USA500)** — a CONTINUOUS (not staircase)
  trail matching an exact worked example: open 7800, +1pt profit → SL
  7800 (breakeven), +2pt → SL 7801, +3pt → SL 7802. SL trails
  `cfg.TRAIL_FIXED_LOCKBACK_POINTS` behind current price once
  `cfg.TRAIL_FIXED_ACTIVATE_POINTS` profit is reached (USA500:
  activate=1, lockback=1, minlock=0) — at the activation threshold
  itself, SL lands exactly at breakeven, matching the example precisely.
- **`_trail_staircase_pct()` (USA100 20%, USA30 25%)** — same
  non-delayed staircase SHAPE as XAUUSD's existing fixed-point one (SL
  already in profit at step 1 — "first benchmark price reach hote hi
  TSL profit mein aa jaye"), but each step is a FRACTION of the
  position's own TP distance (`cfg.TRAIL_STEP_PCT`/`INCREMENT_PCT`, 1:1
  ratio) instead of a fixed point value, scaling automatically per
  symbol.

`trail_all_positions()` dispatch order: `TRAIL_STEP_POINTS` (XAUUSD's
existing staircase) → `TRAIL_STEP_PCT` (USA100/USA30, new) →
`TRAIL_FIXED_ACTIVATE_POINTS` (USA500, new) → generic %-of-TP default
(GBPUSD/USDJPY — confirmed untouched this round, all three new fields
`None` on both).

**Verified** with a standalone test:
- All 4 symbols' Rule2/5/7 SL values match the table above exactly,
  including the explicit assertion that changing one rule's SL never
  silently moves another's (the whole point of this round).
- USA500's fixed-point trail: +1pt → SL=open exactly; +2pt →
  SL=open+1 exactly.
- USA100's %-staircase at +20% of TP lands SL exactly at
  `open + 20%×TP`.
- USA30's %-staircase at +25% of TP lands SL exactly at
  `open + 25%×TP`.
- GBPUSD/USDJPY confirmed still on the plain generic trail (all new
  fields `None`).

Dashboard's Rule 7 card, the Rule-coverage matrix (new row for Rule 7's
independent sizing), and `docs/current_strategy.md` (per-symbol table
rewritten with per-rule SL columns, Trailing section, Rule 7 write-up)
all updated.

**Pattern for future isolation work**: a config field being its own,
separately-named value doesn't guarantee genuine independence if the
CODE that reads it still calls through a shared function underneath.
`SCALP_FIXED_SL_POINTS` looked isolated on the config surface, but
`_reverse_scalp()` was still calling `_sl_tp_scalp()` directly — two
rules that looked independent were still coupled one layer down. When a
user says "make X independent," check every function call in the path,
not just every config field.

---

## Stats baseline at this version's save time (account 49825877, demo)

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 70 | 32/38 | 45.7% | -57.83 |
| USA100 | 69 | 48/21 | 69.6% | 81.78 |
| USA30 | 61 | 34/27 | 55.7% | -575.20 |
| XAUUSD | 113 | 67/46 | 59.3% | -3780.00 |
| GBPUSD | 46 | 16/30 | 34.8% | -1662.00 |
| USDJPY | 35 | 12/23 | 34.3% | -111.21 |

Overall: 394 trades, 209W/185L, win rate 53.05%, net P/L -6104.46.

(This baseline is BEFORE this version's changes have a real chance to
show their effect — it's this version's starting point, not its own
results. A restart is needed to pick up any of this version's changes.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).

---

## FOLLOW-UP, 2026-08-14 — trailing staircase bug fix (USA100/USA30)

**Real bug in the %-of-TP staircase trail introduced by this version**,
caught by the user during a later GBPUSD/USDJPY follow-up (see
`versions/v2.9/NOTES.md`'s own follow-up section for the full writeup —
same bug, same fix, both documented in full there since it was caught in
that context first). Short version: `TRAIL_STEP_PCT` had been set EQUAL
to `TRAIL_INCREMENT_PCT` on both USA100 (0.20/0.20) and USA30
(0.25/0.25) — this collapsed the first trail step's trigger price and
its new SL to the same point, risking an immediate close/failed modify
the moment trailing engaged. User: the 20%-with-20%-increment wording
this version's NOTES quoted from the user was only meant to explain the
non-delayed CONCEPT, not an exact literal spec — the mechanism that
should actually have been followed is this SAME version's own XAUUSD
staircase, where `TRAIL_INCREMENT_POINTS` (0.5) is deliberately smaller
than `TRAIL_STEP_POINTS` (1.0), a 2:1 ratio, so the first trail sits
behind live price rather than on top of it.

**Fix**: `TRAIL_STEP_PCT` = **0.25** on both symbols (USA30's activation
level was already correct at 0.25; USA100's raised from 0.20 to match,
now uniform), `TRAIL_INCREMENT_PCT` = **0.125** on both (half of step,
matching XAUUSD's already-correct ratio). XAUUSD's own points-based
values in this version are UNCHANGED — never had this bug. `code/`
refreshed to the live bot's current full state at this update (includes
the GBPUSD/USDJPY mechanism added afterward in the `v2.9` follow-up —
those fields are inert/`False` for USA500/USA100/USA30/XAUUSD, no effect
on this version's own symbols). A restart is needed to pick up this
correction.

---

## SECOND FOLLOW-UP, 2026-08-15 — the staircase SHAPE itself replaced
## (not just its levels) with a unified continuous trail, all 6 symbols

**Caught LIVE, on USA30**, the day after the fix directly above:

```
USA30 SELL 1289742196 | open 53755.20 | SL 53742.40 | TP 53703.90
current price 53722.90 | profit 32.30
```

User: *"USA30 ki price ka difference dekho lekin trailing SL aage nahi
barh raha hai kyun?"* — the SL shown (53742.40) was EXACTLY this
version's own staircase's step-2 value (`open - 2×12.5%×tp_dist`), even
though price had moved well past that step toward step 3 (62.9% of TP
reached, next jump not due until 75%). The DISCRETE staircase — this
version's own design, and the design corrected just above this section —
was working exactly as built, but its SHAPE was the deeper problem: it
only moves SL at fixed jump points and sits completely flat in between,
even as price keeps advancing.

**User's fix, with an exact worked example** (verbatim): *"first trail ko
open price se thora upper rakho jeise tum ne banaya hoa tha tumhara
machenism acha tha bus meine yeh kaha tha k us k levels kum kerdo...
jab yeh 25% ho tab trail 12.5% ho... jab 50% ho tab trail 25% ho... jab
75% ho tab 50% ho jaye... trail sub symbols per aeise hi laga do jeise
meine bataya hai."* (Apply this exact same way on every symbol, gold
included.)

**Solved algebraically before writing any code**: this maps EXACTLY onto
`trail_all_positions()`'s own ORIGINAL generic formula — continuous,
recomputed fresh from live price every tick, not a discrete staircase —
`nsl = max(current_price - lock_back, open_price + min_lock)`, at new
percentages `activate_at=25%`, `lock_back=25%`, `min_lock=12.5%` of TP:

| Profit reached | Raw (`current - lock_back`) | Floor (`min_lock`) | Locked (max of the two) | User's example |
|---|---|---|---|---|
| 25% (activation) | 0% | 12.5% | **12.5%** | 12.5% ✓ |
| 50% | 25% | 12.5% | **25%** | 25% ✓ |
| 75% | 50% | 12.5% | **50%** | 50% ✓ |

Matches all three of the user's worked numbers exactly. Between whole
thresholds (e.g. 40%, 45%) the SL keeps moving too — the raw
`current - lock_back` term already exceeds the floor past 37.5% profit,
so from there on SL tracks live price continuously, fixing the original
"aage nahi barh raha" complaint directly.

**Fix**: changed the hardcoded constants in `trail_all_positions()`'s
generic default branch from `0.4/0.3/0.15` to `0.25/0.25/0.125` — no new
function, this IS the pre-existing generic branch, just re-parametrized.
Then removed EVERY per-symbol trail override field from all 6 symbols'
configs (`TRAIL_STEP_POINTS` on XAUUSD, `TRAIL_STEP_PCT`/`INCREMENT_PCT`
on USA100/USA30/GBPUSD/USDJPY, `TRAIL_FIXED_ACTIVATE_POINTS`/etc. on
USA500 — this version's own USA500 continuous trail and USA100/USA30
staircase both included) so every symbol now falls through to this ONE
branch identically. `_trail_staircase()`, `_trail_staircase_pct()`, and
`_trail_fixed_points()` are left in the code, unused, per this project's
standing "don't delete superseded mechanisms" pattern.

**Verified** with a standalone test: the formula reproduces the user's
three examples exactly (25%→12.5%, 50%→25%, 75%→50%); SL demonstrably
keeps moving between non-round profit levels (40% vs. 45% give different
locked amounts) — confirming the "flat between jumps" complaint is fixed;
below 25% activation, nothing fires (unchanged floor behavior).

Same message, USDJPY's flat SL/TP also raised 0.050→0.075 — see
`versions/v2.9/NOTES.md`'s own follow-up section, not specific to this
version's own symbols. `code/` refreshed to the live bot's current full
state. A restart is needed to pick up this correction.
