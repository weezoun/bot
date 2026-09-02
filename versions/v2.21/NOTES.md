# v2.21 — 2026-09-02

Previous version: [v2.20](../v2.20/NOTES.md)

## What changed since v2.20

XAUUSD (Gold) only — a real redesign of Rule 7's (Scalp SL hit) reversal
mechanism, done as an explicit, user-named exception to the standing
2026-08-29 XAUUSD freeze (see `versions/v2.18/NOTES.md` — the freeze only
blocks changes the user does NOT name; this one was named directly, and
is scoped to Gold's own Rule 7 only, nothing else on this symbol).

### Why this was revisited

The v2.20 indices analysis (`SCALP_SL_PROFIT_SKIP_REVERSAL`) prompted the
user to ask for the full immediate-<5s scalp-SL-to-reversal breakdown on
XAUUSD too, split loss-triggered vs. profit-triggered (previously only
given as a one-line summary — flagged as incomplete). Fresh data pulled
from `trade_history.db`:

| | Count | Reversal win% | Net reversal leg | Combined net (scalp+reversal) |
|---|---|---|---|---|
| Scalp SL LOSS → reversal | 12x | 8% | **-1,689.00** | **-3,988.00** |
| Scalp SL PROFIT → reversal | 18x | 44% | -234.00 | +2,230.00 (positive only because the scalp leg itself was profitable) |

Both outcomes are net-negative on the reversal leg itself for Gold — the
opposite of the indices, where the loss-triggered case is net-positive
(why they were deliberately left alone in v2.20).

### Design process (three rounds, each corrected by the user before landing)

**Round 1 (loss-triggered only)**: walked through exactly how Rule 4
works (never forces a trade — only BLOCKS a fresh same-side entry until
a cooldown + DI/candle confirmation clears, then the bot's own normal
signal logic decides). User confirmed: *"sl loss hit k liye same rule4
wali strategy ko copy karenge — yeh final ho gaya."* Implemented as a new
`rule7_reversal_gate` (own field, own clearing function
`_check_rule7_reversal_gate`, copied from `rule4_gate`'s exact shape:
`RULE4_MIN_COOLDOWN_SECONDS` floor + benchmark-cross-fast-path OR
rolling-DI+candle-slow-path), threaded through
`strategy.evaluate_entry`/`evaluate_flip`/`decide` as a new `rule7_gate`
parameter (same trivial presence-check pattern as `rule3_gate`/
`rule4_gate`). Deployed as `SCALP_SL_LOSS_REVERSAL_COOLDOWN`.

Also included, in this first round, an extra mechanism the user asked
for mid-discussion: re-arming the scalp's own ORIGINAL side via Rule 6's
existing `scalp_continuation_gate`/`_check_rule6_gate`, so a return to
the original scalp direction wouldn't be stuck disarmed until a full
DI-regime flip.

**Round 2 (profit-triggered)**: user asked to extend the same design to
a profit-closed scalp SL, after reviewing Rule 3's mechanics for
comparison (Rule 3 = WITH_TREND TP, no cooldown floor, full ADX/DI/RSI/
ATR/candle confirmation — contrasted directly against Rule 4's shape,
which the loss-side gate already copies). User's initial framing: *"rule
3 per jo checks lage hoye hein woh rule 6 per lag gaye aur jo checks
rule 4 mein lage hoye hein woh rule 7 par lag jayenge"* — read at the
time as: extend the existing two-gate (Rule 4 copy for reversal + Rule 6
reuse for continuation) design to cover profit too.

**Round 3 (same-day correction, before anything beyond config.py's
comments were deployed for round 2)**: user caught two things wrong with
the round-1 design once round 2 exposed them: *"rule 6 us se link nahi
hai"* (Rule 6 is Scalp TP — has nothing to do with an SL discussion at
all, remove it entirely) and clarified the real intent: *"sl with loss
hit... rule 4 mein diye gaye rules copy ho jayenge rule 7 mein, aur sl
with profit hit hone per woh rule copy ho jayenge jo rule 4 mein hain"*
— Rule 4's mechanism, and ONLY Rule 4's, gets copied into Rule 7, for a
loss- or profit-closed scalp SL alike. No Rule 6 involvement, in either
direction.

### What actually shipped (final, this version)

- `config.SCALP_SL_REVERSAL_COOLDOWN` (renamed from
  `SCALP_SL_LOSS_REVERSAL_COOLDOWN` — dropped "LOSS", now covers both
  outcomes), `True` for XAUUSD only, `False` (default, no effect)
  everywhere else.
- `bot_runner._classify_and_record_close`'s `COUNTER_SCALP` branch: for
  XAUUSD, ANY scalp SL close (profit or loss) now calls
  `_gate_scalp_reversal()` instead of `_reverse_scalp()` — no more
  forced, zero-confirmation reversal on Gold at all.
- `_gate_scalp_reversal()` (renamed from
  `_gate_scalp_reversal_after_loss`, Rule 6 linkage removed entirely)
  sets ONE isolated gate, `rule7_reversal_gate` — blocks a fresh
  WITH_TREND entry on the REVERSAL (opposite) side only. Own dedicated
  field + clearing function (`_check_rule7_reversal_gate`), zero shared
  state with `rule4_gate` — but deliberately the SAME shape, copied
  directly.
- The scalp's own ORIGINAL side is not touched by any of this — no new
  mechanism was added for it in the final design. It relies on whatever
  already existed before this version (regime-flip re-arm being the only
  generic fallback) — this is a known, accepted trade-off of the final,
  simplified design, not an oversight.
- A resulting WITH_TREND entry on the reversal side, once the gate
  clears, is a normal Rule 2 entry — no longer tagged "Rule 7" in
  `open_reason` (nothing was forced), and the reversal's own tight sizing
  (`REVERSAL_FIXED_SL_POINTS`) / one-per-DI-regime cap
  (`scalp_reversal_used`) no longer apply to this path, since no forced
  entry happens at all anymore on Gold.
- Trailing SL and the scalp re-arm mechanism itself (Rule 6's own logic)
  are completely untouched by any of this, per direct instruction.

**Verified**: standalone isolation test (cooldown floor, both clearing
paths, side-scoping, independence from `rule3_gate`/`rule4_gate`) run
before every deploy in this round — no MT5 connection made at any point,
per the standing safety rule. `python -m py_compile` clean on every
touched file. Dashboard (Rule 7 card, `app.py`) and
`docs/current_strategy.md` both updated to match the final design.
Restarted the demo bot twice this round (once per corrected round) —
each time verified via `Get-NetTCPConnection -LocalPort 5050` port
ownership before touching any process, live bot (`c:\bot - Live`)
confirmed untouched both times.

**IMPACT**: Gold no longer takes a forced, unconfirmed reversal trade
after ANY scalp SL — the reversal side only opens if the bot's own
normal WITH_TREND signal genuinely confirms it after a cooldown, exactly
matching Rule 4's existing, already-proven design. Expected to eliminate
the -3,988.00 (loss-triggered) and -234.00 (profit-triggered) reversal-
leg drag seen in the pre-change data — real effect to be confirmed
against live trades going forward. The scalp's own original-side
re-entry speed after an SL is unchanged from before this version (no new
mechanism added there in the final design).

## Baseline at save time

- `stats/trade_history_at_v2.21_save.db` — snapshot taken at restart,
  immediately after the final (round-3-corrected) deployment and
  verification.

## Next version

(none yet)
