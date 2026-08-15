# Version 2.3 — saved 2026-08-13

**Previous version:** [`../v2.2/NOTES.md`](../v2.2/NOTES.md) — read that
first for GBPUSD's initial WITH_TREND SL fine-rounding fix, and Rule
3/Rule 6's same-candle lock replaced by confirmation. This file lists
ONLY what changed since that save point — it is not a standalone history
of the whole bot.

**Next version:** [`../v2.4/NOTES.md`](../v2.4/NOTES.md) — this version's
own history stops at the point described below (the GBPUSD/USDJPY SL/TP
final fix). Read `v2.4/NOTES.md` for what changed after that: a generic
same-candle entry cap (unrelated to any numbered rule) removed after it
was found silently defeating the v2.2 Rule 3/6 fix, and trade-history
timestamps fixed to consistently show local machine time. See
[`../INDEX.md`](../INDEX.md) for the full chain of every version.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.3_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## What changed since v2.2

### GBPUSD/USDJPY SL/TP — the "final fix"

User: *"meine tumhein kaha tha k GBPUSD aur USDJPY dono per with_trend
aur scalp aur reversal sub k liye sl 100 tp 100 lagano yani gbpusd k
liye .00100 aur usdjpy k liye .100 lekin yeh abhi tak fix nahi hein
balkey chnag hoti rehti hein. is ko final fix karo mujhe dynamic nahi
chahiye."*

v2.2's GBPUSD fix (`TREND_SL_FINE_ROUNDING`) turned out to be a **partial
patch** — it only exempted WITH_TREND's SL leg from `ROUND_STEP`'s
away-rounding, leaving scalp's SL, and every TP (both modes, both
symbols), still drifting. Root cause, now fully understood: `ROUND_STEP`
(added 9v, 2026-08-12) always rounds AWAY from the reference price on a
coarse grid — and since the configured SL/TP target on both symbols was
the exact SAME size as the grid step (GBPUSD 0.00100 target on a
0.00100 grid; USDJPY 0.100 target on a 0.100 grid), rounding away could
add up to one FULL additional step on every single trade, landing
anywhere in `[target, 2×target)` depending purely on where the entry
price happened to fall relative to the grid. That's the literal
mechanism behind "change hoti rehti hein" — it was never a fixed number,
by design.

**Final fix:** `round_step` removed ENTIRELY from both `GBPUSD` and
`USDJPY` in `config.py` (was `0.00100` / `0.100`). With `cfg.ROUND_STEP`
now `None` for both, `bot_runner._round_price()` unconditionally falls
through to the fine broker-tick rounding branch (GBPUSD `0.00001`,
USDJPY `0.001`) for every SL and TP on these symbols, in every mode —
WITH_TREND, scalp, and the scalp-SL reversal (which always calls
`strategy._sl_tp_scalp()` regardless of its mode label, so it's covered
automatically, same as every previous scalp-sizing fix this session).
Real distance now lands within one broker tick of the exact configured
flat value on every trade, at every entry price — genuinely fixed, not
dynamic.

This also:
- Made GBPUSD's `cfg.TREND_SL_FINE_ROUNDING` (v2.2's partial fix)
  redundant — removed from `GBPUSD`'s config. With `ROUND_STEP` already
  `None`, the `coarse` parameter on `_round_price()` has no grid left to
  apply regardless of its value, so the mode-specific carve-out no longer
  does anything.
- Superseded USDJPY's brief `scalp_fixed_sl_points=0.025` cut (from
  earlier the same day, pre-v2.1) — removed from `USDJPY`'s config.
  Scalp's SL now falls back to `fixed_sl_points` (`0.100`) exactly like
  WITH_TREND does, giving one uniform flat value across all three modes
  as explicitly requested this time: *"sub k liye sl 100 tp 100."*

The underlying `ROUND_STEP`/`TREND_SL_FINE_ROUNDING`/
`SCALP_FIXED_SL_POINTS` mechanisms themselves were NOT ripped out of
`bot_runner.py`/`config.py` — they stay available (harmless, unused for
GBPUSD/USDJPY now) for any symbol that might genuinely want them later
(XAUUSD's `SCALP_FIXED_SL_POINTS=2.00` scalp-only override, untouched by
this request, still uses the same mechanism). Only GBPUSD's and
USDJPY's config VALUES changed — no rule logic, no shared code touched.

Verified with a standalone test: for both symbols, both `WITH_TREND` and
`COUNTER_SCALP` modes, and 5+ different entry prices — SL distance and TP
distance both land within one broker tick of the exact flat target every
single time (GBPUSD: always ~0.00100; USDJPY: always ~0.100), confirming
the "keeps changing" complaint is fully resolved, not just narrowed.
Dashboard's per-symbol table, `docs/current_strategy.md` (three separate
sections: the per-symbol sizing table, the Scalp sizing paragraph, and
the ROUND_STEP mechanism writeup — all three marked SUPERSEDED rather
than silently rewritten, so the fix history stays traceable), and this
project's persistent cross-session memory file all updated to match.

**Pattern for future "still not fixed" reports**: when a user says a
previous fix didn't fully work, check whether that fix addressed a
SYMPTOM of the root cause rather than the root cause itself, rather than
assuming the fix was simply implemented wrong. Here, three same-day
iterations (TP=SL flat -> GBPUSD WITH_TREND-only fine-rounding -> full
`ROUND_STEP` removal) each narrowed the drift before the third one
actually eliminated its source.

---

## Stats baseline at this version's save time (account 49825877, demo)

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 30 | 11/19 | 36.7% | -33.54 |
| USA100 | 38 | 27/11 | 71.0% | 68.04 |
| USA30 | 33 | 17/16 | 51.5% | -483.70 |
| XAUUSD | 42 | 25/17 | 59.5% | -2051.00 |
| GBPUSD | 22 | 5/17 | 22.7% | -822.00 |
| USDJPY | 15 | 4/11 | 26.7% | 207.39 |

Overall: 180 trades, 89W/91L, win rate 49.4%, net P/L -3114.81.

(This baseline is BEFORE this version's fix has a real chance to trade —
it's this version's starting point, not its own results. GBPUSD's and
USDJPY's history above still reflects the pre-fix drifting SL/TP
behavior this version's change addresses.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).
