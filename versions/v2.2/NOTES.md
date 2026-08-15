# Version 2.2 — saved 2026-08-13

**Previous version:** [`../v2.1/NOTES.md`](../v2.1/NOTES.md) — read that
first for Rule 5's ADX/RSI/ATR restoration and the start of this
versioning chain. This file lists ONLY what changed since that save
point — it is not a standalone history of the whole bot.

**Next version:** [`../v2.3/NOTES.md`](../v2.3/NOTES.md) — this version's
own history stops at the point described below (GBPUSD's WITH_TREND SL
fine-rounding fix, and Rule 3/Rule 6's same-candle lock replaced by
confirmation). Read `v2.3/NOTES.md` for what changed after that: the
GBPUSD/USDJPY SL/TP "final fix" that removed `ROUND_STEP` entirely (this
version's GBPUSD fix turned out to be a partial patch, superseded there).
See [`../INDEX.md`](../INDEX.md) for the full chain of every version.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.2_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## What changed since v2.1

### 1. GBPUSD — WITH_TREND SL rounding fix

User: *"GBPUSD ka stoploss bohat door ja raha hai us ko .00100 tak le
kar ao WITH_TREND k liye."*

Root cause: `ROUND_STEP` (set to `0.00100` for GBPUSD, 9v) rounds SL/TP
AWAY from the reference price on a coarse grid — but GBPUSD's WITH_TREND
SL target is itself exactly `0.00100` (9y, the same size as the grid
step). Rounding away from a reference that isn't already on-grid can add
up to one FULL extra step, so the real distance could land anywhere up to
`~0.00200` — nearly double the intended `0.00100`, exactly matching "SL
bohat door ja raha hai."

Fix: added `cfg.TREND_SL_FINE_ROUNDING` (new `SymbolConfig` field, `True`
for GBPUSD only, `False`/default for every other symbol). Gave
`bot_runner._round_price()` a new `coarse: bool = True` parameter — when
`False`, it skips the `ROUND_STEP` grid entirely and falls straight
through to the existing fine broker-tick rounding, keeping the real
distance close to the configured flat value (tick-size precision only,
not a 10-pip jump).

Threaded `mode` through the call chain so the rounding call can tell
WITH_TREND apart from scalp:
- `send_order()` now passes its own `mode` argument into
  `_build_order_request(..., mode=mode)` (both the first attempt and the
  Invalid-Stops retry).
- `_build_order_request()` computes
  `sl_coarse = not (mode == 'WITH_TREND' and cfg.TREND_SL_FINE_ROUNDING)`
  and rounds the SL leg with that; TP is untouched (still always coarse).
- `_modify_sltp()` (trailing) takes the same new `mode` parameter and
  applies the identical `sl_coarse` logic to the trailed SL.
- `trail_all_positions()` looks up `mode = self.state.position_modes.get(p.ticket, "")`
  per position and passes it through.

Scoped to ONE (symbol, mode, leg) combination — GBPUSD, WITH_TREND, SL
only. GBPUSD's scalp SL and every TP still round on the coarse
`ROUND_STEP` grid exactly as before (9v/9y, unchanged). Every other
symbol is completely unaffected — `TREND_SL_FINE_ROUNDING` defaults
`False`, so `sl_coarse` always evaluates `True` for them regardless of
`mode`, identical to pre-2.2 behavior.

**USDJPY has the identical structural exposure** (`ROUND_STEP=0.100` ==
`FIXED_SL_POINTS=0.100` for WITH_TREND) but was **not** touched — the
user asked about GBPUSD specifically; flagged as a similar-pattern risk
for the user's awareness, not fixed preemptively.

Verified with a standalone test: GBPUSD WITH_TREND SL now rounds to
within one broker tick of the flat `0.00100` target (was landing as far
as `0.00190` before); GBPUSD's scalp-SL rounding and TP rounding are
byte-for-byte unchanged; USDJPY (control, flag not set) unaffected.

### 2. Rule 3 and Rule 6 — same-candle lock REMOVED, replaced by confirmation

**Both are locked rules, modified with explicit permission, in one
combined instruction covering both.**

User's diagnosis: a WITH_TREND trade's TP hitting (Rule 3) was blocking
that side from re-entering until a genuinely NEW CLOSED candle printed,
and a scalp TP (Rule 6) was blocking ALL new entries outright for the
rest of that candle — both were preventing the trend from continuing
right after a clean win. Explicit instruction: fix this on BOTH rules,
but via PROPER CONFIRMATION — RSI, ADX, ATR, rolling DI, DI, candle
color — not by simply deleting the gate. Same-candle re-entry should be
ALLOWED once genuinely confirmed, never blocked purely by candle timing.

**Rule 3** (`bot_runner._check_rule3_gate`):
- Dropped the `closed_snap.bar_time > gate['bar_time']` hard wait
  entirely — the function no longer takes a `closed_snap` parameter at
  all, only `live_snap`.
- Clears the instant ALL of the following are true on live data:
  `ADX >= ADX_MIN`; DI dominant in the trade's own direction
  (`di_plus > di_minus` for BUY) AND rolling (above the immediately
  preceding candle); RSI inside the WITH_TREND band, via the SAME
  `_rsi_buy_ceiling`/`_rsi_sell_floor` helpers Rule 2's own entry uses
  (newly imported into `bot_runner.py`); ATR strong; and the CURRENTLY
  FORMING candle DEFINITELY the required color (`_bullish_candle`/
  `_bearish_candle` — an absolute requirement now, stronger than the old
  "not opposite" check).
- Can clear within the SAME candle as the TP that set the gate — no
  candle-advance requirement of any kind remains.

**Rule 6** (`bot_runner._rearm_scalp_after_tp` / `_check_rule6_gate`):
- `_rearm_scalp_after_tp` no longer sets `self.state.last_bar_time` — the
  blanket "block ALL new entries, WITH_TREND and scalp, either side,
  this candle" mechanism is gone entirely.
- `_check_rule6_gate` dropped its `live_snap.bar_time > gate['bar_time']`
  wait (didn't even require a new candle to *start*, let alone close).
- Clears via the same style of full confirmation as Rule 3, mirrored for
  scalp's own context: `ADX >= ADX_MIN`; this side's DI still dominant
  OPPOSING the big trend (the scalp definition, e.g. `di_minus > di_plus`
  during an UP trend) AND rolling; RSI inside the SCALP band
  (`RSI_SCALP_SELL_MAX`/`RSI_SCALP_BUY_MIN`); ATR strong; forming candle
  definitely the required color.
- The original reason for the blanket block (a scalp win getting chased
  and given back — found directly, USA100, 2026-08-11) is now handled by
  this stronger confirmation requirement instead of an outright block:
  the reasoning is that a genuine exhaustion/reversal should FAIL this
  confirmation regardless of which candle it lands on, while genuine
  continuation should pass it — same-candle timing itself is no longer
  the deciding factor.

Both rules stayed fully isolated per this project's standing principle —
separate functions, no shared code between Rule 3's and Rule 6's own
confirmation logic even though they're conceptually similar (duplication
is the accepted tradeoff, same as every other rule pair in this codebase).

Dashboard cards (Rule 3, Rule 6) and `docs/current_strategy.md` both
updated to describe the new behavior; old "waits for next candle"
language replaced throughout.

Verified with a standalone test: confirmation failing (e.g. RSI too
extended, or weak ADX) keeps both gates active even mid-candle, with
`last_bar_time` confirmed untouched by Rule 6's TP handling; full
confirmation clears both gates immediately, same `bar_time` as the TP
that set them.

---

## Stats baseline at this version's save time (account 49825877, demo)

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 30 | 11/19 | 36.7% | -33.54 |
| USA100 | 38 | 27/11 | 71.0% | 68.04 |
| USA30 | 32 | 17/15 | 53.1% | -438.20 |
| XAUUSD | 41 | 25/16 | 61.0% | -1373.00 |
| GBPUSD | 22 | 5/17 | 22.7% | -822.00 |
| USDJPY | 15 | 4/11 | 26.7% | 207.39 |

Overall: 178 trades, 89W/89L, win rate 50.0%, net P/L -2391.31.

(This baseline is BEFORE either of this version's two fixes has a real
chance to trade — it's this version's starting point, not its own
results. GBPUSD's history above still reflects the "SL too far" problem
this version's fix #1 addresses; XAUUSD's history still reflects the
pre-Rule-5-fix noisy period described in v2.1.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).
