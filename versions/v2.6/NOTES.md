# Version 2.6 — saved 2026-08-13

**Previous version:** [`../v2.5/NOTES.md`](../v2.5/NOTES.md) — read that
first for Rule 4's redundant-check removal + benchmark-crossing fast
path, and the USDJPY/GBPUSD trailing-SL backward-regression fix. This
file lists ONLY what changed since that save point — it is not a
standalone history of the whole bot.

**Next version:** [`../v2.7/NOTES.md`](../v2.7/NOTES.md) — this version's
own history stops at the point described above (XAUUSD SL unified to a
flat 5.00). Read `v2.7/NOTES.md` for what changed after that: a new
staircase trailing mechanism for XAUUSD, replacing the generic
TP-distance-based trail. See [`../INDEX.md`](../INDEX.md) for the full
chain of every version.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.6_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## What changed since v2.5

### XAUUSD SL unified to a flat 5.00, all modes

User: *"gold ka SL scalp aur with_trend kam kar ke 5 par fix karo v2.6"*
— explicit new version this time (the previous two fixes, requested
right after, were kept as v2.5 at the user's direction; this one gets
its own bump).

XAUUSD previously had a **split** SL design: scalp + reversal used a
flat 2.00-point override (`SCALP_FIXED_SL_POINTS`, added 2026-08-13),
while WITH_TREND stayed on its original ATR-based sizing
(`0.75 × ATR`). User asked to cut BOTH down to a flat 5.00, uniformly.

**Change**: `SCALP_FIXED_SL_POINTS` removed from XAUUSD's config;
`FIXED_SL_POINTS=5.00` added instead — the same mechanism
USA30/USA100/GBPUSD/USDJPY already use, applying identically to
WITH_TREND, scalp, and the scalp-SL reversal (which always calls
`strategy._sl_tp_scalp()` regardless of its mode label, so it's covered
automatically, same as every previous scalp-sizing fix this session).
TP untouched — still 5.5 points, both modes; only SL was asked for.

Verified with a standalone test: both `_sl_tp_trend()` and
`_sl_tp_scalp()` now return exactly 5.00 points of SL distance for
XAUUSD regardless of ATR (tested with `atr=999` to prove ATR is fully
bypassed), for both BUY and SELL; TP confirmed unchanged at 5.5.

Dashboard's per-symbol sizing table (now driven by the same
`FIXED_SL_POINTS`-presence check every other flat-SL symbol uses — no
new dashboard code needed) and `docs/current_strategy.md` (the per-symbol
table and the Scalp "Sizing" paragraph, both updated to describe XAUUSD
as fully uniform now, alongside USA30/USA100/GBPUSD/USDJPY) both reflect
the change. `SCALP_FIXED_SL_POINTS` itself stays available in
`config.py`/`strategy.py`, unused right now — ready if any symbol wants
a scalp-only override again later.

Values-only change — no rule or strategy logic touched.

---

## Stats baseline at this version's save time (account 49825877, demo)

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 40 | 17/23 | 42.5% | -43.89 |
| USA100 | 47 | 33/14 | 70.2% | 58.98 |
| USA30 | 43 | 22/21 | 51.2% | -526.70 |
| XAUUSD | 56 | 33/23 | 58.9% | -1579.00 |
| GBPUSD | 27 | 7/20 | 25.9% | -932.00 |
| USDJPY | 18 | 7/11 | 38.9% | 346.74 |

Overall: 231 trades, 119W/112L, win rate 51.52%, net P/L -2675.87.

(This baseline is BEFORE this version's fix has a real chance to show
its effect — it's this version's starting point, not its own results.
XAUUSD's history above still reflects the old split-SL design; a
restart is needed to pick up the flat-5.00 change.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).
