# Version 2.10 — saved 2026-08-14

**Previous version:** [`../v2.9/NOTES.md`](../v2.9/NOTES.md) — read that
first for GBPUSD/USDJPY's Rule 5/6/7 + FLIP disable. This file lists
ONLY what changed since that save point — it is not a standalone history
of the whole bot.

**Next version:** [`../v2.11/NOTES.md`](../v2.11/NOTES.md) — this
version's own history stops at the point described above (the trend
direction calculation fix). Read `v2.11/NOTES.md` for what changed after
that: a full per-rule SL brainstorm across USA500/USA100/USA30/XAUUSD,
Rule 7 fully decoupled from Rule 5 (architecture change), and 3 new
trailing mechanisms. See [`../INDEX.md`](../INDEX.md) for the full chain
of every version.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.10_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## What changed since v2.9

### Trend DIRECTION CALCULATION changed — not a rule, applies to all 6 symbols

**Background**: user reported a live XAUUSD SELL that lost money and
initially attributed it to SL sizing / rolling DI / same-candle logic
not being applied. Each of those four specific claims was checked
directly against the actual code and the live evidence already gathered
that session:
- "SL 2 ka karo, nahi kiya" — it HAD been 2.00 (scalp-only), then the
  user's own later instruction explicitly superseded it to a uniform
  5.00 (v2.6) — not something left undone.
- "sirf BUY par kiya, SELL par nahi" — `_sl_tp_trend`/`_sl_tp_scalp`
  apply `FIXED_SL_POINTS` symmetrically to both sides; the actual SELL
  trade in question showed a ~5-point SL distance, consistent with the
  flat value, not old ATR-based sizing.
- "rolling DI nahi lagi" — the live signal text shown by the user
  itself read `"+DI 41.7 rising vs prior (36.9)"` — literally the
  rolling DI check firing.
- "same candle wala rule nahi laga" — the logs from the same
  investigation showed `"Rule 4 gate cleared (SELL) — DI 5.8 crossed
  benchmark 5.8"` — the v2.5 benchmark-crossing same-candle fix, firing
  correctly.

All four were confirmed already correct. The REAL cause (identified the
turn before this one): `trend` was computed as a bare `EMA50 > EMA200`
comparison — a 200-bar average lags a sharp reversal badly, so `trend`
can keep reading stale for hours after price/DI/RSI have already turned.

**User's proposed fix** (their own words): *"if live price cross both 50
and 200 ema then it must treat it as with_trend... priority live price
ki honi chahiye... [beech wale case mein] ema wala formula apply hoga."*
Asked me to verify before implementing.

**Verification result**: confirmed this directly targets the exact
observed lag. Recommended (and user confirmed) the one open design
question — the straddle case (price between the two EMAs, not clearly
past both) — stays on the ORIGINAL `EMA50 > EMA200` comparison, unchanged.

**Explicit constraint, stated twice by the user**: *"yaad rakhna is se
rules mein koi aur change nahi hona chahiye, rules nahi change kar rahe
hain sirf direction ki calculation modify ho rahi hai."* This is a
change to the shared INPUT every rule reads
(`strategy.build_snapshot()`'s trend calculation) — Rules 1-7 and FLIP
are all byte-for-byte untouched; they just now receive a more responsive
`trend` value.

**Implementation** (`strategy.build_snapshot()`):

```python
if close > ema50 and close > ema200:
    trend = 'TRENDING_UP'
elif close < ema50 and close < ema200:
    trend = 'TRENDING_DOWN'
elif ema50 > ema200:
    trend = 'TRENDING_UP'
elif ema50 < ema200:
    trend = 'TRENDING_DOWN'
else:
    trend = 'NEUTRAL'
```

Price-vs-both-EMAs checked FIRST (highest priority); the original
EMA50-vs-EMA200 comparison only applies as a fallback when price is
straddling the two EMAs; the `NEUTRAL` edge case (`ema50 == ema200`
exactly) is unchanged.

**Verified** with a standalone test (synthetic OHLC+indicator
DataFrames run through `build_snapshot()` directly, not just the
isolated formula):
- The exact live scenario (price above both EMAs, EMA50 still below
  EMA200) now reads `TRENDING_UP`.
- The mirrored DOWN case (price below both EMAs, EMA50 still above
  EMA200) reads `TRENDING_DOWN`.
- Both straddle cases (price between the EMAs) correctly fall back to
  the old EMA50-vs-EMA200 comparison in each direction.
- A clean, fully-agreed uptrend (price and both EMAs all aligned) still
  reads correctly.

**IMPACT**: trend can now flip earlier during a genuine reversal — the
goal. It can also flip somewhat MORE OFTEN during a choppy/ranging
market where price oscillates around both EMAs, since that's a lower
bar to cross than waiting for the EMAs themselves to cross. Every rule
that acts on `trend` still layers its own ADX/RSI/DI confirmation on
top, so a bare trend flip shouldn't by itself cause a bad entry — but
this is worth watching if choppy-market entry quality seems to regress
anywhere. Applies identically to all 6 symbols — this is shared,
symbol-agnostic code with no per-symbol branching, so there was no way
to scope it narrower even if that had been wanted.

---

## Stats baseline at this version's save time (account 49825877, demo)

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 68 | 32/36 | 47.1% | -47.58 |
| USA100 | 65 | 46/19 | 70.8% | 108.43 |
| USA30 | 60 | 33/27 | 55.0% | -584.70 |
| XAUUSD | 108 | 65/43 | 60.2% | -2837.00 |
| GBPUSD | 44 | 16/28 | 36.4% | -1451.00 |
| USDJPY | 35 | 12/23 | 34.3% | -111.21 |

Overall: 380 trades, 204W/176L, win rate 53.68%, net P/L -4923.06.

(This baseline is BEFORE this version's fix has a real chance to show
its effect — it's this version's starting point, not its own results.
XAUUSD's history above still includes the stale-trend SELL loss this
version's fix targets; a restart is needed to pick up the new trend
calculation.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).
