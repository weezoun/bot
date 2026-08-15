# Version 2.1 — saved 2026-08-13

**Previous version:** [`../v2/NOTES.md`](../v2/NOTES.md) — read that first for
everything up to and including the Account panel sizing fix (2026-08-13).
This file lists ONLY what changed since that save point — it is not a
standalone history of the whole bot.

**Next version:** [`../v2.2/NOTES.md`](../v2.2/NOTES.md) — this version's
own history stops at the point described below (Rule 5's ADX/RSI/ATR
restoration + the versioning chain itself starting). Read `v2.2/NOTES.md`
for what changed after that: GBPUSD's WITH_TREND SL rounding fix, and
Rule 3/Rule 6's same-candle lock replaced by confirmation. See
[`../INDEX.md`](../INDEX.md) for the full chain of every version, in
order, with a one-line summary of each — use that to find which version
introduced or last changed any given rule instead of searching through
each version's full NOTES.md by hand.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.1_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## What changed since v2

### 1. Rule 5 — ADX/RSI/ATR RE-ADDED (a locked rule, modified with explicit permission)

User asked to compare XAUUSD's rules/behavior "now vs ~20 hours ago"
since it had flipped from profit to loss. Investigated with real trade
data (not guesswork) — found the actual inflection point:

| | Before 2026-08-13 06:00 | After 2026-08-13 06:00 |
|---|---|---|
| Trades | 22 | 16 |
| Wins/Losses | 18W / 4L | 6W / 10L |
| Net P/L | **+2,455** | **-3,562** |

The losing `COUNTER_SCALP` entries were firing on near-pure noise —
`"-DI 11.9 rising vs prior (11.8)"`, `"-DI 15.5 rising vs prior (15.5)"`
— tiny (as little as 0.1) upticks at weak absolute DI levels (11-19),
because 2026-08-12's removal of ADX/RSI/ATR from Rule 5 left rolling-DI-
alone with no floor to filter out chop. Important nuance: this was NOT a
rule regression WITHIN the loss window — Rule 5 had been in this exact
(ADX/RSI/ATR-free) form since 2026-08-12 ~15:30, and was profitable for
~15 hours under it before the 06:00 flip. So the real lever was reduced
signal quality exposed by choppier market conditions, not a code change
that happened at the flip point itself.

Reported this data-backed finding to the user WITHOUT changing Rule 5
(it's locked). User responded with explicit permission: *"rule 5 se
ADX/RSI/ATR wapis lagane se agar noise kam ho jaegi... unko rule 5 par
wapis laga do, mere khayal mein asal reason yehi hai."*

Re-added to `strategy.py`'s `scalp_ok` (both `TRENDING_UP`/`TRENDING_DOWN`
branches), alongside the existing rolling-DI + forming-candle checks:
- `snap.adx >= cfg.ADX_MIN`
- `snap.rsi < cfg.RSI_SCALP_SELL_MAX` / `snap.rsi > cfg.RSI_SCALP_BUY_MIN`
- `snap.atr_strong`

The literal DI-cross (`di_minus > di_plus` / `di_plus > di_minus`,
removed 2026-08-12) was **NOT** restored — the user asked only for
ADX/RSI/ATR back, and rolling-DI-catches-it-before-the-cross is still the
intended earlier-entry design. This is a noise filter layered back on
top of that design, not a reversal of it. Matching lines restored in
`_skip_scalp_sell_reason`/`_skip_scalp_buy_reason` so SKIP diagnostics
cite all four checks again.

Applies identically to all 6 symbols — Rule 5's standing cross-symbol
requirement. The fix isn't XAUUSD-only even though XAUUSD's data is what
surfaced it.

Verified with a standalone test:
1. The exact noisy real trade (ADX ~8, DI 11.9 vs prior 11.8) — now
   correctly blocked on ADX.
2. A genuinely strong-conditions case (ADX 25, RSI 55, ATR strong, DI
   rising 18->20) — still fires.
3. RSI-only and ATR-only block cases, confirming each check is
   independently enforced.

Dashboard's Rule 5 card, the "ADX minimum gate" row in the Rule coverage
table, and `docs/current_strategy.md` (both the Rule 5 write-up and the
"Entry (Rule 5)" summary further down) all updated to match.

### 2. Versioning became a proper chain

This version folder itself is the first entry in the new pattern — see
`../INDEX.md`. Previously `v2/` was refreshed in place after every
change, so it could only ever show "current state," never "what changed
at checkpoint N." From now on: each meaningful checkpoint gets its own
`v<N>[.<M>]/` folder with `code/`, `stats/`, and a `NOTES.md` that lists
ONLY the delta since the previous version (not a repeat of that version's
full history) plus Previous/Next pointers, chained together and indexed
in `versions/INDEX.md`.

---

## Stats baseline at this version's save time (account 49825877, demo)

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 28 | 10/18 | 35.7% | -36.74 |
| USA100 | 36 | 25/11 | 69.4% | 18.79 |
| USA30 | 32 | 17/15 | 53.1% | -438.20 |
| XAUUSD | 38 | 24/14 | 63.2% | -1107.00 |
| GBPUSD | 21 | 4/17 | 19.1% | -836.00 |
| USDJPY | 15 | 4/11 | 26.7% | 207.39 |

Overall: 170 trades, 84W/86L, win rate 49.4%, net P/L -2191.76.

(This baseline is BEFORE Rule 5's ADX/RSI/ATR restoration has a chance to
trade — it's this version's starting point, not its own results yet. Note
also this total still includes the pre-06:00-flip and post-flip XAUUSD
trades described above, plus history from before that DB clear point —
it is not scoped to any single sub-window.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).
