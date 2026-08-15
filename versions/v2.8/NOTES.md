# Version 2.8 — saved 2026-08-14

**Previous version:** [`../v2.7/NOTES.md`](../v2.7/NOTES.md) — read that
first for XAUUSD's new staircase trailing mechanism. This file lists
ONLY what changed since that save point — it is not a standalone history
of the whole bot.

**Next version:** [`../v2.9/NOTES.md`](../v2.9/NOTES.md) — this version's
own history stops at the point described above (USA500's SL flattened to
5.00, and the new REASON+IMPACT standing practice starting). Read
`v2.9/NOTES.md` for what changed after that: GBPUSD/USDJPY's late-signal
investigation and the resulting Rule 5/6/7 + FLIP disable on those two
symbols. See [`../INDEX.md`](../INDEX.md) for the full chain of every
version.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.8_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## New standing practice, starting this version: REASON + IMPACT, not just WHAT

User: *"mein changes ka reason bhi bata raha hoon to har version mein jo
changes ho rahi hain un ke impact ka reason bhi likho, takay mein dobara
in ko change karwana chahoon to same reason dobara implement na ho."*

From this version onward, every config/code change gets documented with
TWO things, both in the inline code comment at the change site and in
the version's own `NOTES.md`:

1. **REASON** — the user's own stated problem, kept close to verbatim,
   not smoothed into something vaguer.
2. **IMPACT** — the trade-off or side effect the change introduces, so a
   future request to revisit it starts from an already-known trade-off
   instead of rediscovering (or blindly re-implementing) the same thing.

## What changed since v2.7

### USA500 — SL flattened to 5.00, both modes

**REASON** (user's words, verbatim): *"USA500 per SL bohat qareeb lag
raha hai jis ki wajah se trades bohat jaldi close ho rahi hain."* —
USA500's SL was ATR-based (`0.75× ATR` for WITH_TREND, `max(0.8×ATR,
3.0)` for scalp, no fixed floor override) and was landing too close to
entry, so ordinary price noise was closing trades before the intended
move had room to develop. User gave an exact target: open `7815` → BUY
SL `7810` (-5) / SELL SL `7820` (+5) — a flat 5-point gap, no ATR
scaling at all.

**Change**: `fixed_sl_points=5.00` added to USA500's config — same
`FIXED_SL_POINTS` mechanism already used by USA30/USA100/GBPUSD/USDJPY/
XAUUSD. Applies to WITH_TREND, scalp, and the scalp-SL reversal alike
(reversal always calls `_sl_tp_scalp()` regardless of its mode label, so
it's covered automatically). TP untouched — still 5.5, both modes; only
SL was asked for.

**IMPACT**: SL distance is now CONSTANT regardless of current
volatility.
- On a low-ATR day: MORE room than ATR-based sizing would have given —
  fewer premature stops, the intended fix.
- On a genuinely high-ATR/fast day: this could now be TIGHTER than
  ATR-based sizing would have produced, since ATR-based SL widens
  automatically when the market speeds up and a flat number does not.
- **If USA500 starts stopping out specifically on fast/volatile days**,
  that's the OPPOSITE failure mode from what this change fixes — the
  fix for that scenario is NOT "the SL is too close again" (already
  addressed here), it's that a flat value doesn't scale up with
  volatility. Consider a symbol-specific floor or a hybrid
  (ATR-based with a wider minimum) instead of just re-flattening a
  different number.

Verified with a standalone test reproducing the user's exact example:
entry 7815 → WITH_TREND BUY SL 7810.00, SELL SL 7820.00 (both modes
confirmed).

Dashboard's per-symbol sizing table and `docs/current_strategy.md`
updated with both the change and its trade-off note (following the new
REASON + IMPACT practice above).

---

## Stats baseline at this version's save time (account 49825877, demo)

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 58 | 27/31 | 46.5% | -40.51 |
| USA100 | 56 | 40/16 | 71.4% | 109.18 |
| USA30 | 52 | 27/25 | 51.9% | -615.10 |
| XAUUSD | 99 | 60/39 | 60.6% | -1752.00 |
| GBPUSD | 36 | 11/25 | 30.6% | -1385.00 |
| USDJPY | 26 | 8/18 | 30.8% | -59.50 |

Overall: 327 trades, 173W/154L, win rate 52.91%, net P/L -3742.93.

(This baseline is BEFORE this version's fix has a real chance to show
its effect — it's this version's starting point, not its own results.
USA500's history above still reflects the old ATR-based SL; a restart is
needed to pick up the flat 5.00.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).
