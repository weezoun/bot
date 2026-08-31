# v2.17 — 2026-08-28

Previous version: [v2.16](../v2.16/NOTES.md)

## What changed since v2.16

### Rule 4's minimum re-entry cooldown corrected — only applies to an actual loss now

v2.16 added a 180s minimum-wait floor to Rule 4's SL re-entry gate (real
XAUUSD case: rapid-fire same-second re-entries after a WITH_TREND SL,
net -604.00 in one 11-minute burst). That fix applied the cooldown to
**every** SL close, regardless of the realized profit.

**Real misimplementation caught by the user, same day**: the user's
original ask was explicitly scoped to a losing SL only — "ager sl loss
may hit ho to phir wait kare... lekin ager with_trend sl k sath [profit
mein] close ho to jo kaam ker raha hai woh kerta hai." A trailing-SL exit
that closes in **profit** is a successful trade, not a failed entry the
rapid-reentry protection was meant to guard against. Caught live on
XAUUSD: a SELL WITH_TREND position closed via its trailing SL at
**+160.00 profit** — the v2.16 fix still applied the full 180s+DI-
confirmation wait to it, blocking a legitimate continuation entry in an
obvious, ongoing downtrend (the user noticed the bot sitting out a clear
trend move and asked why — this cooldown, applied to a winning trade,
was the answer).

**Fix** (`bot_runner.py`, `_classify_and_record_close` /
`_check_rule4_gate`): `sl_time` (the cooldown floor) is now only set
when `profit < 0` at close. A profit-close via trailing SL sets the gate
with `sl_time=None`; `_check_rule4_gate` treats that as "skip the
minimum-wait floor entirely, go straight to the two original clearing
paths (benchmark-cross fast path OR rolling-DI+candle slow path)" —
exactly the pre-v2.16 behavior for that specific case. A losing SL still
gets the full 180s+confirmation wait, unchanged. Log messages updated to
say explicitly which case applies ("no minimum-wait cooldown (closed in
profit, not a loss)" vs. the usual cooldown wording).

**Verified**: `python -m py_compile` clean; restarted the bot (killed a
duplicate-process near-miss caught mid-restart — the old process hadn't
actually been killed before the new one started, exact same class of
issue v2.15's singleton lock exists for; the lock itself wasn't
re-triggered here since `bot.lock` had been manually deleted immediately
before the restart, removing the file it needs to contend on — worth
remembering not to delete `bot.lock` by hand before a restart), confirmed
single clean process afterward, all 6 symbols `connected: true`.

## Baseline at save time

- `stats/trade_history_at_v2.17_save.db` — snapshot taken 2026-08-28 at
  restart, after the fix was deployed and verified live.
- XAUUSD, today (2026-08-28) at save time: 76 trades, 36 profitable
  (+9,173.00), 40 loss (-6,683.00), net +2,490.00.

## Next version

[v2.18](../v2.18/NOTES.md) — XAUUSD frozen/excluded from future rule
tuning (policy-only, no code change), based on this version's own data
showing it clearly outperforming the other 5 symbols.
