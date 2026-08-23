# Version 2.14 — saved 2026-08-24

**Previous version:** [`../v2.13/NOTES.md`](../v2.13/NOTES.md) — read
that first for USA100's Rule 2 SL settling at 15 after two same-day
reversals. This file lists ONLY what changed since that save point — it
is not a standalone history of the whole bot.

**Next version:** none yet — this is the current version. See
[`../INDEX.md`](../INDEX.md) for the full chain of every version, in
order, with a one-line summary of each.

`code/` is a frozen copy of every source file as it stood at this
version's save time. `stats/trade_history_at_v2.14_save.db` is a frozen
copy of the trade history DB at the same moment. The live bot in `c:\bot`
(not this folder) keeps running and keeps writing to the real
`trade_history.db` — this snapshot is a fixed reference point, not a
place to make further edits.

---

## What changed since v2.13

### Real infrastructure bug found and fixed: MT5 connection never self-healed

Not a rule/strategy change — order/risk infrastructure, same category as
the trailing mechanism, order placement, and deployment fixes earlier in
this session.

**Incident**: the bot's own long-running process (alive since
2026-08-21) was found logging "Not enough rate data" for ALL 6 symbols,
in a tight loop, for an extended period — while a completely fresh,
separate diagnostic script connected to MT5 and fetched rates instantly.
Also separately reported the same day: an MT5 Network-log message,
`"balance management has been disabled - demo account"` — confirmed
harmless (`trade_allowed`/`trade_expert` both still `True`; this message
is about manual balance/deposit operations, unrelated to trading).

**Root cause**: `is_connected()` just returns a cached module-level
`_connected` flag, set ONCE by `connect_mt5()` at bot startup (and again
only inside `_loop()`'s own startup path) — nothing in the main polling
loop (`bot_tick()`) ever re-verifies or refreshes it. If the underlying
MT5 IPC session goes stale for ANY reason (terminal crash/restart, a
dropped connection over a weekend market closure and reopen, etc.),
`bot_tick()` keeps sailing past `if not self.state.connected: return`
believing everything is fine, then fails at the actual rates fetch,
forever — no retry logic existed anywhere in this path.

**User's question that prompted the fix**, verbatim: *"saturday sunday
market band rahe gi to kya yeh her weekend per aesa hi karega? is ka
solution hona chahiye werna yeh to masla karega her baar isi tarah."*
Direct answer: yes, it would have — on every future weekend, or any
other MT5 disconnect, without this fix.

**Fix** (`bot_runner.py`): a new rate-limited `_maybe_reconnect()`
function, called from BOTH failure paths in `bot_tick()` — (1)
`is_connected()` returning `False`, and (2) `is_connected()` returning
`True` but the actual rates fetch still failing (the exact bug that
happened here). It re-runs the same `connect_mt5()` used at startup,
genuinely refreshing `_connected` instead of trusting a stale cached
value. Rate-limited to once per 30 seconds (`_RECONNECT_COOLDOWN_SECONDS`)
since up to 6 symbols' threads can hit this in the same failure window,
and a full `connect_mt5()` (which can relaunch `terminal64.exe` if it
isn't running) has been observed taking up to ~60s in past incidents —
retrying every 2s from 6 threads at once would pile up reconnect
attempts instead of cleanly recovering.

**Verified live, not just compiled**: restarted the bot with the fix in
place (confirmed all 6 symbols started in the same second), then
deliberately killed the running `terminal64.exe` process while leaving
the bot's own python process untouched — a fresh `terminal64.exe`
relaunched within 1 second on its own, and the dashboard's live
`/api/status` (via the real domain, not a local shortcut) confirmed
`connected: true` with live, moving `attempt` counts (~85 per symbol,
consistent with continuous 2-second polling since startup) shortly
after — the bot never needed a manual restart to recover from a killed
terminal.

**IMPACT**: the bot should now self-heal from MT5 disconnects (weekend
closures, terminal crashes, transient IPC drops) within roughly 30-60
seconds on its own, instead of staying stuck showing "Not enough rate
data" until a human notices and restarts it manually. Worth watching the
FIRST real weekend after this to confirm it holds up under that specific
condition (this test killed the terminal directly — a genuine weekend
market-closure-and-reopen cycle hasn't been observed yet with this fix
in place).

---

## Stats baseline at this version's save time (account 49825877, demo)

| Symbol | Trades | W/L | Win% | Net P/L |
|---|---|---|---|---|
(see `c:\bot\docs\current_strategy.md` / live dashboard for current
per-symbol numbers — this version's change is infrastructure-only, no
rule/SL value changed, so there is no new "before/after" comparison to
make for this save point specifically.)

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).
