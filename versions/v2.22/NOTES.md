# v2.22 — 2026-09-03/04

Previous version: [v2.21](../v2.21/NOTES.md)

## What changed since v2.21

A large, multi-part session covering: a new ATR-removal round (Rule 3/5/6,
grown to all 6 symbols), a brand-new condition-based check replacing that
idea across Rules 2-7, currency pairs realigned to indices, and a real
bug found and fixed in Gold's Rule 7 redesign (v2.21) once it started
seeing live traffic.

### 1. ATR check removed — Rule 5/6, then Rule 3, then all 6 symbols

Started scoped to Rule 5 (scalp entry) + Rule 6 (scalp TP re-arm), 5
non-XAUUSD symbols only — mirroring Rule 2's own entry condition, which
has never checked ATR at all: *"jaise hum ne with_trend mein ATR ka
check nahi lagaya hoa usi tarah scalp ke andar se bhi ATR check remove
karo."* New `cfg.SCALP_ATR_CHECK_ENABLED` flag (later renamed).

**Grew twice, same day**: (1) found while implementing — Rule 3
(WITH_TREND TP hit)'s own re-arm gate DID check ATR, even though Rule 2
never has, contradicting the request's own premise. Flagged, then user
confirmed: *"rule 3 se bhi remove karo."* (2) User separately named
XAUUSD explicitly (*"xauusd per bhi apply karo"*), exempting this from
the standing 2026-08-29 freeze. Flag renamed `ATR_CHECK_ENABLED` (dropped
"SCALP" — misleading once a WITH_TREND rule reads it too) and set
`False` on all 6 symbols. ADX/RSI stay unconditional everywhere.

**History worth knowing** (recorded in config.py, flagged to the user):
this exact change (remove ATR from Rule 5) was tried once before,
2026-08-12, and reverted the very next day (v2.1) after real data showed
XAUUSD flipping from +2,455 to -3,562 profit on noisy, low-ADX scalp
entries. This round is the user's own explicit decision to retest, not
new data overturning that finding.

### 2. NEW check: block on `condition == 'RANGING'`, Rules 2/3/4/5/6/7, all 6 symbols

User asked how `snap.condition` (NORMAL/RANGING/VOLATILE) is calculated
and whether it's used anywhere — a full-codebase search confirmed it was
computed every tick (`strategy.build_snapshot`: VOLATILE if ATR > 1.2x
its own 50-bar mean; else RANGING if bar-to-bar price move < 0.25x ATR;
else NORMAL) but never read by any rule at all — purely a dashboard
display value until now.

User's direct instruction: *"ATR ki jagah yeh check hona chahiye, normal
aur volatile ki surat mein trade allow, ranging ki surat mein trade
block, aur yeh sub rules per apply hoga: 2,3,4,5,6,7 aur sub symbols ke
liye."* This REPLACES the ATR idea with a different signal entirely —
`ATR_CHECK_ENABLED` above is untouched (still `False` everywhere), this
is a new, separate mechanism. New `cfg.CONDITION_CHECK_ENABLED` flag,
default `True`, applied uniformly (no per-symbol exception).

Implemented independently in each rule's own isolated code (zero shared
function/state): Rule 2/5 entry conditions, Rule 3/6 gate confirmation
sets, Rule 4/Rule 7's XAUUSD-gate (whole-clear gating — neither clearing
path matters during RANGING), and Rule 7's classic forced reversal
(`_reverse_scalp`, RANGING now skips it entirely, falling through to the
existing no-reversal re-arm gate — the one path with zero other
confirmation, so this matters most there).

### 3. Currency pairs (GBPUSD/USDJPY) realigned to match indices

Requested directly: *"currency pairs ko ab align kerte hein... bilkul
indices ke jeisa bana do un per tamam 6 rules apply hon ge jeise indices
per ho rahe hein, un per scalping ban ki hoi hai woh bhi open kerdo."*
Values-only for now — SL/TP levels explicitly deferred to a follow-up
round, not touched.

- `SCALPING_ENABLED`/`FLIP_ENABLED` reverted `False` → `True` on both
  symbols (were disabled 2026-08-14 after real "late signals" data —
  that finding stays true historically; this is a policy decision to
  retest, not a reversal of it).
- `TREND_SL_REVERSAL_ENABLED` reverted `True` → `False` on both. This
  substitute mechanism (`_reverse_trend`, immediate WITH_TREND-SL
  reversal) existed only because Rule 5/6/7 had no scalp position to
  ever trigger from — now that they're back, its justification is gone;
  keeping it on would mean reacting to a WITH_TREND SL with both it AND
  Rule 4's own gated re-entry simultaneously, unlike indices.
- **Then**, separately: *"gold ke tamam rules ko follow kare... currency
  per rules lagane hein gold wale, indices wale nahi."* `SCALP_SL_
  REVERSAL_COOLDOWN = True` added to GBPUSD/USDJPY (Gold's own Rule 7
  mechanism — cooldown-gated, no forced reversal) — deliberately NOT
  indices' `SCALP_SL_PROFIT_SKIP_REVERSAL` (that flag is built from
  indices-specific trade data that doesn't exist for these two yet).
- Verified: trailing SL already unified across all 6 symbols (zero
  fixed/staircase overrides anywhere) — nothing to change there.
- Fixed in passing: `_gate_scalp_reversal`'s log text hardcoded
  "(XAUUSD)" — now generic, since GBPUSD/USDJPY trigger it too.

### 4. Real bug found and fixed: Gold's Rule 7 scalp-side had NO re-arm path

Spotted live, via the dashboard: XAUUSD kept showing "already scalped
this DI regime" long after `condition` itself had moved from RANGING to
NORMAL — the real blocker was `scalp_armed`, not `condition`. Root
cause: v2.21's "no Rule 6 involvement" correction to `_gate_scalp_
reversal` had removed the ONLY re-arm path the scalp's own side had —
`scalp_armed` (set `False` the instant any scalp opens) could then only
ever come back via a full DI-regime flip, "which can take a long time or
never happen" — the exact class of bug this project's history has hit
before (on Rule 6/7's own original design).

**Two attempts, same day**: first, re-armed `scalp_armed` immediately
with no gate at all — caught as wrong (Rule 6 has never been an
unconditional auto-re-arm; it's always required full ADX/DI/rolling-DI/
RSI/candle confirmation, since 2026-08-13, specifically to avoid chasing
an already-exhausted move — the original USA100 2026-08-11 incident).
**Final fix**: `_gate_scalp_reversal` now sets `scalp_continuation_gate`
(Rule 6's own field) instead — reusing `scalp_continuation_gate`/
`_check_rule6_gate` verbatim, UNCHANGED, identical to how indices'
`_rearm_scalp_after_profit_sl` already does it. This does NOT reopen the
"no Rule 6 involvement" correction — that was specifically about Rule
7's own REVERSAL-gating logic (`rule7_reversal_gate`, which stays 100%
Rule-4-shaped, completely untouched); this is the separate scalp's-own-
side concern, which naturally reuses Rule 6's own proven mechanism.

Also corrected same day: `_gate_scalp_reversal`'s cooldown floor
(`RULE4_MIN_COOLDOWN_SECONDS`) had been applied UNCONDITIONALLY
regardless of profit/loss — didn't match Rule 4's own actual pattern
(skip the floor on profit-close). Fixed to mirror Rule 4's own line
exactly: `time.time() if profit < 0 else None`; `_check_rule7_reversal_
gate` now skips the floor entirely when `sl_time is None`.

### 5. Dashboard: Trade History "Summary" toggle

New date-wise breakdown per symbol (Date / Total Trades / Trades in
Profit / Total Profit / Trades in Loss / Total Loss / Day P/L), covering
the ENTIRE history, no range limit — `trade_store.get_daily_summary`,
new `/api/trades/summary` route, dashboard toggle button reusing the
existing symbol dropdown. Existing trade-list view untouched, still the
default. Shown newest-first (descending) — a frontend-only reverse
(`trade_store`'s own query stays oldest-first, untouched).

### 6. Investigated but NOT changed: the one-reversal-per-DI-regime cap

User asked for a genuine data-driven look at `scalp_reversal_used` (Rule
7's classic one-attempt-per-regime cap) now that auto-reversal is gone
on 3 of 6 symbols. Findings: the cap is now **dead code** for XAUUSD/
GBPUSD/USDJPY (`_reverse_scalp` — the only place that checks it — is
never reached on any of the three anymore, always routed to
`_gate_scalp_reversal` instead). For the 3 indices (where it's still
live, loss-triggered scalp SL only): 167 loss-triggered scalp SLs
combined, only 29% (48) got an immediate reversal, 71% skipped (almost
certainly the cap, not margin/order-fail) — when it DID fire, 73% win,
+113.01 net, but per-symbol edge varies widely (USA500 +$0.18/trade,
essentially noise; USA100 +$3.03/trade; USA30 +$5.55/trade). No change
made — presented as data for the user to decide against, given the
uneven per-symbol edge (loosening the cap risks compounding a thin/noisy
USA500 edge without evidence the skipped 71% would perform the same).

## Verification

Every code change this round verified with a standalone test before
deploying (no MT5 connection made at any point, per the standing safety
rule): `test_scalp_atr.py`/`test_atr_all6.py` (ATR bypass, all 6
symbols), `test_condition_check.py` (RANGING blocks/NORMAL-VOLATILE
allow, all 6 call sites), `test_rule7_profit_cooldown.py` (profit vs
loss cooldown floor), `test_scalp_rearm_fix2.py` (weak setup stays
disarmed, strong confirmed setup re-arms via the real Rule 6 gate),
`verify_currency_align.py`/`verify_trailing.py` (GBPUSD/USDJPY config
matches indices' rule-enablement, SL/TP values untouched, trailing
already unified). `python -m py_compile` clean on every touched file.

Restarted the demo bot once, held deliberately until market close (an
open position was running) per direct instruction — verified via
`Get-NetTCPConnection -LocalPort 5050` port ownership before touching
any process; live bot (`c:\bot - Live`) confirmed untouched throughout
(independently restarted itself at least twice this session, on its own
watchdog cycle — no action taken on it per the standing scope boundary).

## Baseline at save time

- `stats/trade_history_at_v2.22_save.db` — snapshot taken at restart,
  immediately after deployment and verification.

## Next version

(none yet)
