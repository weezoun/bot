# Version 2.13 — saved 2026-08-21

**Previous version:** [`../v2.12/NOTES.md`](../v2.12/NOTES.md) — read
that first for the USA500/XAUUSD Rule 2 SL cuts and the 1-week
observation plan this version's own change comes out of. This file
lists ONLY what changed since that save point — it is not a standalone
history of the whole bot.

**Next version:** [`../v2.14/NOTES.md`](../v2.14/NOTES.md) — 2026-08-24,
a real infrastructure fix: the bot's MT5 connection never re-checked
itself once running, so any disconnect (weekend closure, terminal
crash) left it stuck forever showing "Not enough rate data" — a
rate-limited auto-reconnect was added and verified live. Not a rule/SL
change. See [`../INDEX.md`](../INDEX.md) for the full chain of every
version, in order, with a one-line summary of each.

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

### SECOND REVERSAL, same day — settled back to 15.0

The 50.0 widening above was reversed again, same day, before generating
much of its own data — user checked real stats and reconsidered once
more: *"ager hum sl ko 50 kerdein to woh us ko bhi hit ker lega, to
behter hai k us ko 15 hi kerdo, 50 ko to hum pehle bhi ek baar try ker
chuke hein shayad us k baad hi kum ker k 30 kia tha, ab 15 kerdo jeise
scalp aur reverse k liye hai."* Key new information: 50 had apparently
been tried on this exact symbol before (predating this session's own
records) and is what led to it being cut to 30 in the first place — so
widening back to 50 risked repeating a value already found not to work,
rather than testing something new.

**Final value**: `fixed_sl_points` = **15.0** — now uniform with Rule
5/7 (both already 15.0 since `v2.11`), matching the shape USA500/XAUUSD
were brought to on 2026-08-18. Same day, same lever, three values tried
in sequence: 30 (original) → 15 (tried) → 50 (tried) → **15 (settled)**.

Restarted and verified again after this final change — all 6 symbols
started in the same second, confirmed healthy. `code/` and
`stats/trade_history_at_v2.13_save.db` refreshed to reflect this final
state (not the 50.0 mid-point) — the version folder always reflects
where things actually ended up, not every intermediate value tried along
the way.

**Note for future sessions**: this SL value has now been argued for in
BOTH directions (tighter and wider) with real reasoning behind each, on
the same day. If it comes up again, check the actual before/after trade
data first rather than re-deriving either argument from scratch — see
`config.py`'s own comment on this field for the same reminder.

---

## Stats baseline at this version's save time (account 49825877, demo)
## — captured AFTER both reversals, at the final settled 15.0 value

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 460 | 223/237 | 48.5% | -243.12 |
| USA100 | 364 | 252/112 | 69.2% | -127.89 |
| USA30 | 326 | 196/130 | 60.1% | -873.60 |
| XAUUSD | 748 | 384/364 | 51.3% | -1560.00 |
| GBPUSD | 203 | 54/145 | 26.6% | -5454.00 |
| USDJPY | 196 | 75/121 | 38.3% | -2438.80 |

Overall: 2298 trades, 1184W/1110L, win rate 51.52%, net P/L -11282.41.

(This baseline is BEFORE today's final USA100 SL settle [15.0] has a
real chance to show its own effect — a handful of trades landed while
the brief 50.0 experiment was live, included in the totals above like
any other real trade, not backed out. A restart was already done and
verified after the FINAL change — all 6 symbols reconnected instantly,
USA100's Rule 2 SL confirmed at 15.0 live.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).
