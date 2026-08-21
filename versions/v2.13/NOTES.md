# Version 2.13 — saved 2026-08-21

**Previous version:** [`../v2.12/NOTES.md`](../v2.12/NOTES.md) — read
that first for the USA500/XAUUSD Rule 2 SL cuts and the 1-week
observation plan this version's own change comes out of. This file
lists ONLY what changed since that save point — it is not a standalone
history of the whole bot.

**Next version:** none yet — this is the current version. See
[`../INDEX.md`](../INDEX.md) for the full chain of every version, in
order, with a one-line summary of each.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.13_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## What changed since v2.12

### USA100 — Rule 2 (WITH_TREND) SL widened, mid-week (breaks the 1-week plan on purpose) — reversed direction same day

v2.12 explicitly set a 1-week no-further-changes observation window.
This change breaks that window deliberately, at the user's own direct
request, after real live evidence made it worth acting on early rather
than waiting out the full week:

- **2026-08-20**: USA100's WITH_TREND had its best day in a while — 46
  trades, 82.6% win, +152.15.
- **2026-08-21 (next day)**: flipped hard — only 6 WITH_TREND trades,
  33.3% win, **-92.50**.
- Same day, a real trade-log dump (requested directly by the user, who'd
  independently noticed a "choppy market, DI keeps flipping, price
  corrects immediately" pattern live) showed **18 WITH_TREND SELL
  trades in an 11-minute window, same DI reading (-DI 34.7>+DI 20.9)
  repeated across many of them** — strong evidence Rule 4's
  benchmark-crossing "fast path" (added 2026-08-13, see `v2.5`) was
  re-firing on ordinary DI noise in a choppy stretch, since that path has
  no candle-color confirmation at all. Rapid same-side re-entry, each one
  risking a full SL, is expensive regardless of what's causing the
  re-entries.

**First attempt, reversed within the same version before it ran**: user
initially asked to CUT Rule 2's SL 30.0 → 15.0 ("dekhte hein woh kia
kerta hai"), then reconsidered before restart: *"mere khayal may hum sl
ko tight ker rahe hein is k bajaye yeh karo k sl ko agey barha do 50 per
kerdo, kum ker k to aur ziada trade lelega choti moves per aur ziada
bahar nikale ga."* REASON for the reversal: a tighter SL makes the
DIAGNOSED problem worse, not better — during a rapid-reentry burst, a
smaller stop is easier for ordinary short-term noise to reach, so cutting
it would make each rapid re-entry MORE likely to get stopped on chop, not
less. **Final change**: `fixed_sl_points` (Rule 2 only): USA100 30.0 →
**50.0** — widened, not cut, the opposite lever from USA500/XAUUSD's own
SL cuts earlier this version chain, deliberately, since the diagnosis
here is different (entry frequency/noise-sensitivity, not "losses cost
too much relative to wins"). Rule 5 (15.0, cut in `v2.11`) is untouched
either way — this only ever changed Rule 2.

**IMPORTANT — this is explicitly NOT a fix for the underlying re-entry
pattern.** Rule 4's fast path itself (the diagnosed root cause of the
rapid re-entries) was NOT touched this round — only Rule 2's SL size.
User's own framing treats this as an experiment: the bet is that fewer of
the rapid re-entries reach a full 50-point adverse move than reached the
original 30, so stop-outs during a choppy burst should become LESS
frequent even though each one now costs more when it does happen.

**IMPACT**: bigger loss per Rule 2 stop-out when one happens, but the
intent is fewer stop-outs overall during exactly the rapid-reentry
condition that prompted this — genuinely untested, worth watching
closely rather than assuming either direction is correct.

---

## Stats baseline at this version's save time (account 49825877, demo)

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 458 | 221/237 | 48.2% | -245.49 |
| USA100 | 362 | 251/111 | 69.3% | -119.44 |
| USA30 | 321 | 193/128 | 60.1% | -854.10 |
| XAUUSD | 740 | 381/359 | 51.5% | -1109.00 |
| GBPUSD | 203 | 54/145 | 26.6% | -5454.00 |
| USDJPY | 196 | 75/121 | 38.3% | -2438.80 |

Overall: 2281 trades, 1175W/1102L, win rate 51.51%, net P/L -10805.83.

(This baseline is BEFORE today's USA100 SL cut has a real chance to show
its own effect — it's this version's starting point, not its own
results. A restart was already done and verified — all 6 symbols
reconnected instantly, USA100's new 15.0 Rule 2 SL confirmed live.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).
