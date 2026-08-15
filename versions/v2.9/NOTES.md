# Version 2.9 — saved 2026-08-14

**Previous version:** [`../v2.8/NOTES.md`](../v2.8/NOTES.md) — read that
first for USA500's SL flattening and the new REASON+IMPACT standing
practice. This file lists ONLY what changed since that save point — it
is not a standalone history of the whole bot.

**Next version:** [`../v2.10/NOTES.md`](../v2.10/NOTES.md) — this
version's own history stops at the point described above (GBPUSD/USDJPY
Rule 5/6/7 + FLIP disabled). Read `v2.10/NOTES.md` for what changed after
that: the trend DIRECTION CALCULATION changed (price-vs-both-EMAs takes
priority over the old EMA50-vs-EMA200-only comparison) — a shared-input
fix, not a rule change, applying to all 6 symbols. See
[`../INDEX.md`](../INDEX.md) for the full chain of every version.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.9_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## What changed since v2.8

### GBPUSD/USDJPY — Rule 5, Rule 6, Rule 7, and FLIP all disabled

Direct follow-up to the "late signals" investigation from the previous
turn (findings reported, NO changes made at the time, per the user's own
"rules change nahi honge filhal" instruction). After seeing the data,
user's decision:

> *"in dono per rules 5,7 aur flip band kar do yeh total loss de raha
> hain sirf rule 1,2,3,4 rahenge. rule 6 bhi rule 5 ka part hai to woh
> bhi band ho jayega. in short scalping totally band ho jayegi."*

**REASON** (the investigation's own numbers, recapped):

| | GBPUSD | USDJPY |
|---|---|---|
| Rule 7 (reversal) | 0% win, **-373** | 0% win, **-190.95** |
| FLIP | 0% win, **-201** | 0% win, **-105.46** |
| Rule 5 (scalp) | 38.5% win, **-471** (biggest $ loss) | 0% win, **-524.93** (biggest $ loss) |
| Rule 2 (WITH_TREND, unaffected) | 40% win, -208 | 33% win, -3.63 (~breakeven) |

Every Rule 7/FLIP entry in the sample landed **33-884 seconds into its
own M15 candle** — a reactive trigger, never anchored to a candle
boundary the way Rule 2 is (0-4 seconds). That timing pattern is the
literal "late signal" the user described.

**Change**: two new `SymbolConfig` fields, both `True` by default (every
symbol except GBPUSD/USDJPY completely unaffected):
- `SCALPING_ENABLED` — gates `scalp_ok` in both branches of
  `strategy.evaluate_entry()`. When `False`, Rule 5 can never fire.
  Rule 6 (scalp TP handling) and Rule 7 (scalp SL → reversal) need **no
  separate code change at all** — both are triggered inside
  `bot_runner._classify_and_record_close()` only when
  `mode == 'COUNTER_SCALP'`, which can never happen if Rule 5 never
  opens a scalp position in the first place. This is the "Rule 6 is part
  of Rule 5" cascade the user described, confirmed by code inspection,
  not just asserted.
- `FLIP_ENABLED` — makes `strategy.evaluate_flip()` return `None`
  unconditionally when `False`.

Set `scalping_enabled=False, flip_enabled=False` on both `GBPUSD` and
`USDJPY` in `config.py`, each with the full REASON/IMPACT recorded
inline (per v2.8's new standing practice).

**IMPACT**: GBPUSD and USDJPY now ONLY ever trade WITH_TREND (Rule 2) —
this removes the loss sources above entirely, but also removes whatever
wins Rule 5/FLIP occasionally produced (Rule 5 alone still won 5 of 13
trades on GBPUSD) and means these two symbols will simply sit flat
during stretches where Rule 2's own conditions aren't confirmed enough —
no scalp fallback to catch a counter-move, no FLIP to catch a genuine
early reversal. **Fewer total trades on these two symbols, not just
fewer losing ones.** Re-enabling either flag returns to the exact prior
behavior with zero other code changes needed.

**Verified** with a standalone test:
- A textbook-perfect scalp setup on GBPUSD/USDJPY correctly produces
  `HOLD` with reason `"scalping disabled for this symbol (Rule 5)"`.
- The SAME textbook-perfect setup on XAUUSD (control) still fires
  normally — confirms zero effect on other symbols.
- A textbook-perfect FLIP setup returns `None` on GBPUSD/USDJPY, but
  still fires normally on XAUUSD (control).
- A textbook-perfect Rule 2 (WITH_TREND) setup still fires normally on
  GBPUSD — confirms Rules 1-4 are completely untouched.

Dashboard updates:
- Rule 5's card gets the full REASON/IMPACT note; Rule 6/7's cards note
  they're moot on these two symbols (their own trigger can never fire).
- The Rule-coverage matrix: 5 rows that used to be blanket `all_true`
  (scalp entry, scalp SL sizing, scalp TP, scalp TP→continuation gate,
  scalp SL→reversal, FLIP) are now computed from
  `cfg.SYMBOLS[n].SCALPING_ENABLED`/`FLIP_ENABLED` — accurately shows
  GBPUSD/USDJPY as not-applicable instead of asserting something no
  longer true.
- `_build_rules()`'s Rule 5/6/7 `"applies"` dicts changed from
  `all_symbols` to a computed `scalp_symbols` dict, same reasoning.

`docs/current_strategy.md` — Scalp section and FLIP section both updated
with the same REASON/IMPACT writeup.

---

## Stats baseline at this version's save time (account 49825877, demo)

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 64 | 29/35 | 45.3% | -48.70 |
| USA100 | 62 | 45/17 | 72.6% | 143.18 |
| USA30 | 58 | 31/27 | 53.5% | -616.70 |
| XAUUSD | 105 | 63/42 | 60.0% | -2592.00 |
| GBPUSD | 42 | 14/28 | 33.3% | -1552.00 |
| USDJPY | 33 | 11/22 | 33.3% | -98.65 |

Overall: 364 trades, 193W/171L, win rate 53.02%, net P/L -4764.87.

(This baseline is BEFORE this version's fix has a real chance to show
its effect — it's this version's starting point, not its own results.
GBPUSD's and USDJPY's history above still includes all the Rule 5/7/FLIP
losses this version eliminates going forward; a restart is needed to
actually stop those trigger types from firing.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).

---

## FOLLOW-UP, 2026-08-14 — updated IN PLACE, not a new version

**User's explicit instruction**: *"yeh ker k server restart karo aur in
ka wohi wala version update karo jis may rules block kiye they naya
nahi banana"* — this section documents a second round of GBPUSD/USDJPY
changes, applied to this SAME v2.9 folder (`code/` refreshed, a new
stats snapshot added below) rather than a new `v2.10`/`v2.12` folder.
Note this sits chronologically AFTER `v2.10`/`v2.11` were already saved
as separate versions (see `../INDEX.md`) — those two versions' own
changes (trend calculation, USA500/USA100/USA30/XAUUSD SL splits) are
NOT part of this follow-up and are unaffected by it.

### Why: Rule 2 alone was still losing even with Rule 5/6/7/FLIP off

Since the original v2.9 disable above, GBPUSD ran 14 trades at 42.9%
win/-361.00 and USDJPY ran 8 trades at 37.5% win/-145.28 — Rule 2
(WITH_TREND) on its own, with nothing else live on these two symbols.
User (verbatim): *"in ko abhi rehne do in k stats kisi kaam k liye nahi
koi improvement ki gunjaish nazar mahi arahi hai rules block ker k baad
bhi yeh loss hi de rahe hein yeh signal ghalat time per le rahe hein in
k upper following rules lagao"* — four changes, values/trailing-mechanism
only, still no Rule 5/6/7/FLIP re-enable and no Rule 2/4 LOGIC change:

1. **Faster trailing** — switched GBPUSD/USDJPY from the generic
   40%/30%/15% trail to the same %-of-TP staircase mechanism USA100/
   USA30 already use (`_trail_staircase_pct()`, unchanged code, just new
   config values): `TRAIL_STEP_PCT`/`TRAIL_INCREMENT_PCT` = **0.20/0.20**
   on both symbols. Profit now locks in starting at 20% of TP distance
   instead of waiting for 40%.
2. **New reversal-on-WITH_TREND-SL mechanism** — brand new, NOT a
   numbered rule, GBPUSD/USDJPY-only (`cfg.TREND_SL_REVERSAL_ENABLED`):
   `bot_runner._reverse_trend()` fires immediately, zero confirmation,
   the instant a WITH_TREND SL hits — opposite side, sized by the
   symbol's own flat WITH_TREND SL/TP, one attempt per DI regime
   (`BotState.trend_reversal_used`), confirm-before-mutate (same pattern
   as Rule 7's `_reverse_scalp`). Called ADDITIVELY alongside Rule 4's
   own unchanged gate-setting in `_classify_and_record_close` — never
   inside it, never touching `rule4_gate` itself.
3. **SL halved**: `FIXED_SL_POINTS` 0.00100→**0.00050** (GBPUSD),
   0.100→**0.050** (USDJPY).
4. **TP = SL (1:1)**: `TREND_TP_POINTS`/`SCALP_TP_POINTS` also cut to
   0.00050/0.050 to match — was already 1:1 at the old larger size, this
   keeps that same shape at the new smaller size.

### What was already set on the other 4 symbols (per the user's request
### for an example-driven recap)

| Symbol | Rule 2 SL | Rule 5 SL | Rule 7 SL | Trailing |
|---|---|---|---|---|
| USA500 | 5.00 | 2.50 | 5.00 (independent) | Fixed-point CONTINUOUS: open 7800, +1pt→SL 7800 (breakeven), +2pt→SL 7801 |
| USA100 | 30 | 15 | 15 (follows) | %-of-TP STAIRCASE, 20%/20%: TP=30 → SL already in profit at price+6 |
| USA30 | 25 | 50 (held exact) | 25 (independent) | %-of-TP STAIRCASE, 25%/25%: TP=50 → SL already in profit at price+12.5 |
| XAUUSD | 5.00 | 2.00 | 2.00 (follows) | Fixed-point STAIRCASE: every +1.0pt, SL steps +0.5pt (open+0.5, open+1.0, ...) |
| **GBPUSD (this follow-up)** | **0.00050** | n/a (Rule 5 off) | n/a (Rule 7 off) | %-of-TP STAIRCASE, 20%/20% (NEW) |
| **USDJPY (this follow-up)** | **0.050** | n/a (Rule 5 off) | n/a (Rule 7 off) | %-of-TP STAIRCASE, 20%/20% (NEW) |

### IMPACT (per item, per the standing v2.8 REASON+IMPACT practice)

1. Same trade-off as every other trailing speed-up on this bot: locks
   profit in earlier, at the cost of possibly exiting sooner on a trade
   that dips before continuing in its favor.
2. More trades on these two symbols (reacts to every WITH_TREND
   stop-out instead of sitting flat), but each reversal is completely
   unconfirmed — a whipsaw can now produce two losing trades back-to-back
   (the original SL, then the reversal's own SL) where the old behavior
   produced only one.
3. Smaller dollar loss per stop-out, but a tighter stop gets hit by
   ordinary noise more often — a real trade-off, not a pure improvement.
4. 1:1 risk:reward means GBPUSD/USDJPY now need a win rate **above 50%**
   to be net profitable (the old wider TP meant breakeven needed less
   than 50%) — raises the bar for what counts as "working" going
   forward.

Every other symbol (USA500/USA100/USA30/XAUUSD): all fields touched here
(`TRAIL_STEP_PCT`, `TRAIL_INCREMENT_PCT`, `TREND_SL_REVERSAL_ENABLED`)
stayed at their v2.11 values / default `None`/`False` — confirmed
unaffected via standalone test.

**Verified** with a standalone test (`config` field assertions,
`inspect.getsource` checks on the trigger site and regime-flip reset,
`_sl_tp_trend()` sizing sanity for both symbols) — all pass. Also caught
and fixed a real `SyntaxError` mid-implementation (duplicate keyword
arguments from appending new `SymbolConfig(...)` kwargs without removing
the pre-existing ones of the same name) via `python -m py_compile`
before any of this was trusted.

### Baseline for the user's own 24-hour-later comparison

Recorded at the moment this follow-up was applied (account 49825877,
demo), BEFORE this restart — i.e. this is the "after the original v2.9
disable, before this follow-up" checkpoint:

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 71 | 33/38 | 46.5% | -56.08 |
| USA100 | 71 | 50/21 | 70.4% | 108.83 |
| USA30 | 63 | 36/27 | 57.1% | -550.20 |
| XAUUSD | 116 | 70/46 | 60.3% | -3271.00 |
| GBPUSD | 47 | 17/30 | 36.2% | -1657.00 |
| USDJPY | 35 | 12/23 | 34.3% | -111.21 |

Overall: 403 trades, 218W/185L, win rate 54.09%, net P/L -5536.66.

Per-rule breakdown on GBPUSD/USDJPY specifically (since the original
disable, Rule 2/4 only — this is what the 4-part fix above is reacting
to):

| | GBPUSD | USDJPY |
|---|---|---|
| Rule 2 (WITH_TREND) | 14 trades, 42.9% win, **-361.00** | 8 trades, 37.5% win, **-145.28** |

(For reference, the ORIGINAL v2.9-save baseline — before Rule 5/6/7/FLIP
were even disabled — is in the table above this section, and the
per-rule numbers that drove that original disable are: GBPUSD Rule5
14/35.7%/-558.00, Rule7 4/0%/-373.00, FLIP 2/0%/-201.00; USDJPY Rule5
10/10.0%/-471.48, Rule7 4/0%/-190.95, FLIP 1/0%/-105.46.)

A fresh stats snapshot (`trade_history_at_v2.9_followup_2026-08-14.db`)
and refreshed `code/` (all source files as they stand after this
follow-up) are saved alongside the original `v2.9` save-time snapshot in
this same folder — both kept, nothing overwritten, so the ORIGINAL v2.9
disable's own before/after can still be reconstructed if ever needed.

A restart is needed to pick up any of this follow-up's changes — see the
live dashboard `/api/status` after restart to confirm all 6 symbols
running with fresh `attempt` counts.

---

## SECOND FOLLOW-UP, same day, 2026-08-14 — trailing staircase bug fix

**Real bug, caught by the user, in the trailing config set above.**
`TRAIL_STEP_PCT`/`TRAIL_INCREMENT_PCT` had been set EQUAL (0.20/0.20) on
GBPUSD/USDJPY — this meant the FIRST trail step's new SL landed almost
exactly AT live price the instant it triggered (profit just crosses the
step threshold → new SL = open + step ≈ current price), risking an
immediate close or a failed "invalid stops"/"no changes" modify. User:
*"trail lagte hi position close ho jaye gi ya trail fail ho jaye ga, same
live price hone ki wajah se... first trail ko open price se thora upper
rakho jeise tum ne banaya hoa tha [XAUUSD's mechanism]... meine apna
tareeqa sirf samjhane ke liye diya tha, tum ne ghalat implement ker
dya."* — the 20%-with-20%-increment wording from the original request
was only meant to explain the CONCEPT, not an exact literal spec; the
mechanism to actually follow is the one already built correctly for
XAUUSD, where INCREMENT (0.5pt) is deliberately smaller than STEP
(1.0pt) — a 2:1 ratio — so the first trail sits behind live price, never
on top of it.

**Fix**: `TRAIL_STEP_PCT` = **0.25** (the reduced activation level
explicitly requested — "ab us ko kum kerdo 25% par price pohanche to
trail lagna shuru ho jaye"), `TRAIL_INCREMENT_PCT` = **0.125** (half of
step, same 2:1 ratio as XAUUSD's already-correct mechanism) — now on
BOTH GBPUSD and USDJPY. Same correction applied identically to USA100
and USA30 (see `versions/v2.11/NOTES.md`'s own follow-up section — those
two symbols had the exact same bug, at 20%/20% and 25%/25%
respectively). XAUUSD's own points-based values were left UNCHANGED
(never had this bug; its 2:1 ratio was already correct, and its
effective activation of ~18% is already earlier/more aggressive than the
new 25% target, so there was nothing to "reduce" there). USA500's
continuous (non-staircase) trail is unaffected — this bug is specific to
the staircase's discrete-step math.

**Verified** with a standalone test: for every %-based symbol
(USA100/USA30/GBPUSD/USDJPY), the first-step SL now lands with a genuine
POSITIVE gap behind the triggering price (never equal to it), while
still landing comfortably above open price ("thora upper").

`code/` refreshed to the live bot's current full state at this update
(config.py/app.py/docs — this fix only touched config values and
documentation, no bot_runner.py/strategy.py logic changed). A restart is
needed to pick up this correction.

---

## THIRD FOLLOW-UP, 2026-08-15 — trail unified to ONE mechanism (all 6
## symbols); USDJPY's SL/TP raised again

**Trailing**: the %-of-TP staircase fixed just above (25%/12.5%) was
ITSELF superseded within 24 hours — caught live on USA30, not GBPUSD/
USDJPY, but the fix applies identically here since the user asked for
ONE mechanism on every symbol. Full derivation, worked example, and
verification are documented in `versions/v2.11/NOTES.md`'s own second
follow-up section (that's where the bug was diagnosed). Short version:
`TRAIL_STEP_PCT`/`TRAIL_INCREMENT_PCT` removed from both GBPUSD and
USDJPY — both now fall through to `trail_all_positions()`'s generic
branch (activate=25%/lock_back=25%/min_lock=12.5% of TP, CONTINUOUS,
recomputed every tick — not a discrete staircase).

**USDJPY SL/TP raised 0.050 → 0.075**: user, same message: *"USDJPY ka
SL aur TP ajeeb lag raha hai, us per to trail kaam hi nahi kare ga,
itna chota ho gaya hai, us ko increase ker ke 75 per kerdo."* At 0.050
(5 pips), the flat SL/TP had gotten small enough that the trail's %-of-TP
math had almost no meaningful room to operate in. `FIXED_SL_POINTS`/
`TREND_TP_POINTS`/`SCALP_TP_POINTS` all raised to 0.075 — keeps the 1:1
SL=TP shape from the prior follow-up, just bigger. GBPUSD's 0.00050 was
NOT mentioned and stays unchanged.

`code/` refreshed to the live bot's current full state. A restart is
needed to pick up this correction.
