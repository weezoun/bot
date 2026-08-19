# Version 2.12 — saved 2026-08-18

**Previous version:** [`../v2.11/NOTES.md`](../v2.11/NOTES.md) — read
that first for the original per-rule SL brainstorm (USA500/USA100/USA30/
XAUUSD) and the trailing-mechanism unification that followed it. This
file lists ONLY what changed since that save point — it is not a
standalone history of the whole bot.

**Next version:** none yet — this is the current version. See
[`../INDEX.md`](../INDEX.md) for the full chain of every version, in
order, with a one-line summary of each.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.12_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## What changed since v2.11

### Per-rule before/after comparison against the 2026-08-15 benchmark

Between v2.11's save (2026-08-15) and today, enough real trades
accumulated to compare each rule's own performance BEFORE vs AFTER that
version's changes (the trailing unification, and — for GBPUSD/USDJPY
specifically — the SL halving/reversal mechanism from `v2.9`'s follow-up
chain). Full per-rule table:

| Symbol | Rule | Before (n/win%/net) | After (n/win%/net) |
|---|---|---|---|
| USA500 | WITH_TREND | 19/47.4%/-9.40 | 42/76.2%/-3.31 |
| USA500 | SCALP | 24/33.3%/-42.74 | 9/22.2%/-15.51 |
| USA500 | REVERSAL | 13/76.9%/+13.56 | 5/60.0%/-2.40 |
| USA100 | WITH_TREND | 21/76.2%/+59.02 | 36/77.8%/+36.00 |
| USA100 | SCALP | 22/68.2%/+31.57 | 10/60.0%/-11.45 |
| USA100 | REVERSAL | 13/53.8%/-62.70 | 4/75.0%/+13.75 |
| USA30 | WITH_TREND | 19/42.1%/**-401.00** | 36/66.7%/**+87.40** |
| USA30 | SCALP | 20/75.0%/**+181.70** | 12/50.0%/**-142.80** |
| USA30 | REVERSAL | 13/61.5%/-94.80 | 6/66.7%/-26.30 |
| XAUUSD | WITH_TREND | 62/62.9%/-168.00 | 79/70.9%/-833.00 |
| XAUUSD | SCALP | 30/60.0%/-1531.00 | 12/50.0%/-315.00 |
| XAUUSD | REVERSAL | 13/53.8%/-135.00 | 6/33.3%/-484.00 |
| GBPUSD | WITH_TREND | 15/46.7%/-356.00 | 15/**13.3%**/-503.00 |
| GBPUSD | TREND_REV (new) | — | 8/25.0%/-188.00 |
| USDJPY | WITH_TREND | 8/37.5%/-145.28 | 24/41.7%/-240.64 |
| USDJPY | TREND_REV (new) | — | 4/50.0%/-81.69 |

### USA500 / XAUUSD — Rule 2 (WITH_TREND) SL cut

**REASON** (pattern visible in the table above, both symbols): WITH_TREND
win rate improved noticeably after v2.11 (USA500 47.4%→76.2%, XAUUSD
62.9%→70.9%) but dollar P/L stayed flat-to-negative or got WORSE
(USA500 -9.40→-3.31, roughly flat; XAUUSD -168.00→**-833.00**, much
worse) — classic sign of small, frequent wins and occasional large
losses. User: *"mere hisab se usa500 aur usa30 ka result acha hona
chahiye tha sirf win rate barhne se faida nahi hai eventually yeh dono
loss may hein usa500 ka sl 2.5 kerdo with_trend per scalp per already
hum ne kum kia hoa hai. aur xauusd ka sl bhi with_trend 2 per kerdo."*

**Change**: `fixed_sl_points` (Rule 2 only — Rule 5/7 untouched):
- USA500: 5.00 → **2.50** (now matches Rule 5's already-cut 2.50; Rule 7
  stays independently at 5.00, untouched)
- XAUUSD: 5.00 → **2.00** (now matches Rule 5/7's already-cut 2.00 —
  Rule 7 follows Rule 5 automatically here since XAUUSD has no
  independent `REVERSAL_FIXED_SL_POINTS` set)

**IMPACT**: smaller dollar loss per Rule 2 stop-out on both symbols —
same trade-off as every other SL cut on this bot: does not by itself
change win rate, only the cost of being wrong. Rule 5/7's own SL values,
and every other symbol, completely unaffected — confirmed via direct
config inspection after the edit.

### USA30 — flagged, NOT acted on yet

Same table shows USA30's WITH_TREND (the rule that WAS cut in v2.11)
flipped from the worst performer (-401.00) to genuinely profitable
(+87.40) — the SL cut clearly worked there. But its SCALP (Rule 5, whose
own config was NOT touched in v2.11 or here) flipped the opposite
direction: from the best performer (+181.70, 75% win) to the worst
(-142.80, 50% win). Flagged for the user, explicitly left alone per the
standing plan below — unclear yet whether this is a real behavioral
shift or ordinary week-to-week market variance, and Rule 5's own config
is untouched either way so there's nothing to "revert."

### GBPUSD — flagged, NOT acted on yet

WITH_TREND's win rate collapsed further post-fix (46.7%→13.3%), and the
new `TREND_REV` mechanism (from `v2.9`'s follow-up) isn't compensating
(25% win, -188.00). Small combined sample (23 trades) so nothing changed
this round, but this is the worst-performing symbol by far if the trend
holds through the observation week below.

### STANDING PLAN — 1 week, no further changes unless asked

User, after seeing the full before/after table: *"kuch din tak aeise hi
chalne dete hein, roz hum isi terha comparison karein ge her din ka,
takay 1 week ka complete record hoga... koi din acha ho koi bura ho to
ek din ke data par faisla nahi karein ge."* Explicit decision to let
today's config run untouched for a full week, comparing daily against
the reference point below, rather than reacting to single-day noise
(including the two flagged-but-unactioned items above). No further
rule/SL/trailing changes should be proposed or made during this window
unless the user asks — daily requests are for comparison/reporting only.
Also recorded in the `bot-rules-numbering-process` memory file for
cross-session continuity.

---

## Stats baseline at this version's save time (account 49825877, demo)
## — ALSO the reference point for the 1-week observation above

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 130 | 71/59 | 54.6% | -88.85 |
| USA100 | 124 | 90/34 | 72.6% | 217.33 |
| USA30 | 125 | 73/52 | 58.4% | -715.60 |
| XAUUSD | 215 | 134/81 | 62.3% | -5530.00 |
| GBPUSD | 71 | 21/49 | 29.6% | -2408.00 |
| USDJPY | 64 | 24/40 | 37.5% | -440.44 |

Overall: 729 trades, 413W/315L, win rate 56.65%, net P/L -8965.56.

(This baseline is BEFORE today's USA500/XAUUSD SL cut has a real chance
to show its own effect — it's this version's starting point AND the
week-long observation's day-0 reference, not its own results. A restart
was needed to pick up the SL cut — already done and verified, all 6
symbols reconnected cleanly.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).
