# Version 2.4 — saved 2026-08-13

**Previous version:** [`../v2.3/NOTES.md`](../v2.3/NOTES.md) — read that
first for the GBPUSD/USDJPY SL/TP "final fix" (`ROUND_STEP` removed
entirely). This file lists ONLY what changed since that save point — it
is not a standalone history of the whole bot.

**Next version:** [`../v2.5/NOTES.md`](../v2.5/NOTES.md) — this version's
own history stops at the point described below (the generic same-candle
cap removal + local-time timestamp fix). Read `v2.5/NOTES.md` for what
changed after that: Rule 4's own gate had the identical redundant
candle-wait bug that Rule 3/6 got fixed for in v2.2 — missed at the time,
caught live by the user, now fixed too. See
[`../INDEX.md`](../INDEX.md) for the full chain of every version.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.4_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## What changed since v2.3

### 1. Generic same-candle entry cap REMOVED — was silently defeating the Rule 3/6 fix

User showed a real, live case: XAUUSD's WITH_TREND SELL opened at
23:30:05 (server time), hit TP just **31 seconds later** at 23:30:36 —
still the SAME forming M15 candle. The dashboard then kept showing a
fully-confirmed live Rule 2 signal (`-DI 33.5>+DI 10.7, RSI 35.3, red
candle` — everything Rule 3's own confirmation checks for) blocked by
**"Already entered this M15 — waiting next bar"** for the rest of that
candle — even after the user restarted the server.

Traced to `bot_tick()`'s post-execute handling:

```python
if after != before or sig.action.startswith('CLOSE'):
    self.state.last_bar_time = live_snap.bar_time
```

This set `last_bar_time` (the exact field `already_entered_this_bar`
checks) after **ANY** successful entry, TP, SL, or FLIP — completely
generic, never owned by any single numbered rule, and running
independently of Rule 3's/Rule 6's own gates. Since it fired even on a
clean same-candle TP, it kept blocking re-entry for the rest of that
candle regardless of whether Rule 3's confirmation had already cleared —
silently defeating the entire point of v2.2's Rule 3/6 fix. User's
diagnosis, verbatim: *"jab woh rule ka hissa nahi hai yahan per to us ko
tumhein khud hi hata dena chahiye tha pehle"* (since it isn't part of a
rule, you should have removed it yourself already).

**Fix:** removed the generic set entirely from `bot_tick()`.

**Critically preserved, NOT touched:** Rule 4's own explicit, locked
"block ALL entries this candle after a WITH_TREND SL" behavior sets the
SAME `last_bar_time` field, but independently, in its own separate code
path (`_classify_and_record_close`'s SL branch) — this is Rule 4's own
described, dictated design and stays completely intact. `decide()`'s
`already_entered_this_bar` check itself is unchanged infrastructure — it
now only ever becomes `True` via Rule 4's own set, exactly matching
Rule 4's documented behavior with no unrelated side effect layered on
top.

**Deliberately left alone:** one more `last_bar_time` set exists, inside
Rule 7's `_reverse_scalp()` (marks the bar acted-on right after a
reversal trade opens). This is part of Rule 7's own function, wasn't
shown or discussed in this exchange, and touching it would have gone
beyond what was asked — flagged to the user, not changed.

Dashboard updates: Rule 2's and Rule 5's cards used to list "not already
entered this M15 candle" as one of their OWN conditions — both updated
to explain the removal and point to Rule 4's card as the only remaining
same-candle block. Rule 4's own card annotated to note it's now the sole
survivor of this mechanism.

**Pattern for future isolation work:** a field/mechanism reused by a
locked rule (here, Rule 4) can ALSO be written to by an unrelated generic
code path (the old blanket post-execute set) that isn't owned by any
rule at all. When isolating or removing a behavior, check every place a
shared field gets WRITTEN, not just where the rule's own logic reads it
— otherwise a "removed" gate can still silently re-trigger through
another writer nobody thought to check.

### 2. Trade history timestamps — now consistently LOCAL machine time

User: *"open time pehle close time baad mein, aur mere local machine
time se time lo takay mere liye asani ho observation mein"* — prompted
by noticing a trade history row where "Closed" displayed BEFORE "Opened"
chronologically.

Root cause: `opened_at` was captured from MT5's own timestamps
(`position.time` / `deal.time` — the broker SERVER's clock) at three
call sites, while `closed_at` used `datetime.now()` (genuinely local).
This account's broker server clock isn't UTC-synced — confirmed directly
by comparing `mt5.symbol_info_tick().time` against Python's own
`time.time()` at the same instant: **~3 hours ahead** of local. That
offset is exactly what made "Closed" (local time) appear to precede
"Opened" (server time, ~3h in the future relative to local) in the
table.

**Fix:** added two new `SymbolBot` methods:
- `_broker_time_offset()` — seconds to add to a raw MT5 `.time` epoch to
  get its local-equivalent epoch, computed FRESH on every call from a
  live tick vs. `time.time()` (not hardcoded as a fixed ~3h, since
  broker settings or DST could shift it over time).
- `_broker_ts_to_local_str(epoch_seconds)` — applies that offset and
  formats the result identically to how `closed_at` was already being
  formatted.

Replaced all three `datetime.fromtimestamp(x.time)` call sites (the
broker-history-sync reconciliation path's `opened_at`/`closed_at`, and
the live order-placement success handler's `opened_at`) with calls to
the new helper. `closed_at`'s existing `datetime.now()` path (used for
trades the bot detects closing live) was already correct local time —
left unchanged.

Verified directly: converting a live broker tick timestamp through
`_broker_ts_to_local_str()` matches `datetime.now()`'s own formatted
string to the second.

(Left unchanged, out of scope: the "TICK TIME" field in the LIVE
INDICATORS panel still shows raw broker time — that's a different
display, useful for cross-checking against the MT5 terminal directly,
and wasn't part of what was asked.)

---

## Stats baseline at this version's save time (account 49825877, demo)

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
| USA500 | 34 | 13/21 | 38.2% | -41.64 |
| USA100 | 41 | 28/13 | 68.3% | 24.24 |
| USA30 | 38 | 20/18 | 52.6% | -448.20 |
| XAUUSD | 47 | 29/18 | 61.7% | -439.00 |
| GBPUSD | 24 | 5/19 | 20.8% | -982.00 |
| USDJPY | 16 | 5/11 | 31.2% | 278.39 |

Overall: 200 trades, 100W/100L, win rate 50.0%, net P/L -1608.21.

(This baseline is BEFORE this version's two fixes have a real chance to
show their effect — it's this version's starting point, not its own
results. The trade history rows in this baseline still show the
mismatched-clock timestamps this version's fix #2 addresses.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).
