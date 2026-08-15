# Version 2.7 — saved 2026-08-14

**Previous version:** [`../v2.6/NOTES.md`](../v2.6/NOTES.md) — read that
first for XAUUSD's SL unification to a flat 5.00 across every mode. This
file lists ONLY what changed since that save point — it is not a
standalone history of the whole bot.

**Next version:** [`../v2.8/NOTES.md`](../v2.8/NOTES.md) — this version's
own history stops at the point described above (XAUUSD's new staircase
trailing mechanism). Read `v2.8/NOTES.md` for what changed after that:
USA500's SL flattened to 5.00, and a new standing practice (every future
version records REASON + IMPACT, not just WHAT changed). See
[`../INDEX.md`](../INDEX.md) for the full chain of every version.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.7_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## What changed since v2.6

### XAUUSD — new staircase trailing mechanism (not a numbered rule)

User: *"xauusd kafi masla kar raha hai us ka ek reason SL baar baar hit
hona hai humein us ko rokna hoga. trailing stop kafi late update ho raha
hai xauusd k liye, us ko chahiye k jab xauusd 1 point aage barhe to 1st
trailing SL ka increment ho jaye aur woh open price se aage aa jaye.
phir woh 2 increment per trail ko aage barhaye phir 3 per aur trail ka
increment 0.5 kare."*

**Problem**: the generic trail (`trail_all_positions()`, used by every
symbol) doesn't start protecting a position until price has moved 40% of
that position's own TP distance. For XAUUSD's flat 5.5pt TP, that's
2.2 points of room for price to reverse and hit the flat 5.00pt SL
(v2.6) before ANY trailing protection has engaged at all — a real
contributor to XAUUSD's repeated SL hits.

**New design, exactly as specified**: for XAUUSD only, every **1.00
point** of favorable price movement, SL steps forward by **0.5 points**,
starting at the very first step — SL moves PAST open price at step 1
(genuine profit-lock, not just breakeven):

| Favorable move | New SL (BUY) |
|---|---|
| +1.00 pt | `open + 0.5` |
| +2.00 pt | `open + 1.0` |
| +3.00 pt | `open + 1.5` |
| +N.00 pt | `open + 0.5 × N` |

(Mirrored for SELL: `open - 0.5 × N`.) Pure function of current price vs.
entry, recomputed fresh every tick — no memory of previous steps needed,
and the existing monotonic ("never regress") guard still applies exactly
as before.

**Implementation**:
- Two new `SymbolConfig` fields: `TRAIL_STEP_POINTS` and
  `TRAIL_INCREMENT_POINTS`, both `None` by default (every symbol except
  XAUUSD keeps the EXACT generic trailing behavior, byte-for-byte
  unchanged — confirmed directly by reading every symbol's config).
  XAUUSD: `trail_step_points=1.00, trail_increment_points=0.5`.
- New method `SymbolBot._trail_staircase(p, tick, mode)`, selected inside
  `trail_all_positions()` when `cfg.TRAIL_STEP_POINTS` is set, instead of
  the generic TP-distance-based formula.
- Reuses `_modify_sltp()`'s existing protections completely unchanged —
  the min-stop-distance clamp, v2.5's "never regress past the position's
  real current SL" guard, v2.4's "no changes" skip. This override only
  supplies a different target price (`nsl`); nothing about HOW it gets
  sent, validated, or guarded changes.
- Applies to WITH_TREND, scalp, and the scalp-SL reversal alike — same as
  the generic trail, no mode branch (the reversal trade is always
  scalp-sized regardless of its label, and `trail_all_positions()` has
  never branched on mode for exactly that reason).

**Verified** with a standalone test (mocked `mt5.order_send`):
- Step 1/2/3 land exactly on `open ± 0.5/1.0/1.5` for a BUY.
- Below the first step (+0.8pt), nothing is sent.
- Staying within an already-reached step (+1.4pt when SL is already at
  step 1) sends nothing — the monotonic guard correctly treats it as no
  improvement.
- SELL side mirrors correctly (`open - 0.5` at step 1).
- Every other symbol's `TRAIL_STEP_POINTS` confirmed `None` — completely
  unaffected.

Dashboard's Rule-coverage-style "Trailing SL on every open position" row
annotated to note the XAUUSD override exists; `docs/current_strategy.md`'s
Trailing section updated with the full mechanism writeup.

Not part of the numbered-rules process (Rules 1-7) — this is order/risk
infrastructure, same category as the SL/TP sizing and rounding fixes
earlier in this session.

---

## Stats baseline at this version's save time (account 49825877, demo)

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 56 | 27/29 | 48.2% | -36.76 |
| USA100 | 55 | 39/16 | 70.9% | 99.58 |
| USA30 | 50 | 26/24 | 52.0% | -576.50 |
| XAUUSD | 99 | 60/39 | 60.6% | -1752.00 |
| GBPUSD | 34 | 9/25 | 26.5% | -1490.00 |
| USDJPY | 23 | 7/16 | 30.4% | 68.05 |

Overall: 317 trades, 168W/149L, win rate 53.0%, net P/L -3687.63.

(This baseline is BEFORE this version's fix has a real chance to show
its effect — it's this version's starting point, not its own results.
XAUUSD's history above still reflects the old generic-trail behavior; a
restart is needed to pick up the staircase trail.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).

---

## FOLLOW-UP, 2026-08-15 — this version's XAUUSD staircase superseded

**This version's own XAUUSD mechanism (`_trail_staircase()`,
`TRAIL_STEP_POINTS=1.00`/`TRAIL_INCREMENT_POINTS=0.5`) is no longer
selected for any symbol as of this update.** User asked for a unified
trailing mechanism across all 6 symbols (see `versions/v2.11/NOTES.md`'s
own follow-up section for the full derivation and user quotes — same fix
documented there in full since it was diagnosed live on USA30). Short
version: the DISCRETE staircase shape (this version's own design) only
moves SL at fixed jump points and sits flat in between — replaced by a
CONTINUOUS %-of-TP trail (the bot's own pre-existing generic formula,
re-parametrized to activate=25%/lock_back=25%/min_lock=12.5%, applied
identically to all 6 symbols including XAUUSD). `TRAIL_STEP_POINTS`/
`TRAIL_INCREMENT_POINTS` removed from XAUUSD's config; `_trail_staircase()`
itself is left in the code, unused, in case a future symbol needs this
shape again. `code/` refreshed to the live bot's current full state. A
restart is needed to pick up this change.
