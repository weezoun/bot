# v2.18 — 2026-08-29

Previous version: [v2.17](../v2.17/NOTES.md)

## What changed since v2.17

**No code change — a standing-instruction/policy change, recorded as its
own version because it's significant enough to need a clear "as of here"
marker in the history.**

### XAUUSD frozen — excluded from all future rule/logic tuning

User's own words: "xauusd acha perform ker raha hai us may kisi change ki
zaroorat nahi mazeed... sub se pehle xauusd ko us k tamam rules k sath
isolate kerdo... owh running position may rahe ga bus rules us k lock ho
ker isolate ho jaein ge ab xauusd baqi sub k rules follow nahi kare."

**REASON**: real data over the two most recent weeks showed XAUUSD
clearly outperforming (week of 23-29 Aug: 607 trades, net +11,084.00 —
see that session's day-by-day and per-rule breakdown) while USA500,
USA100, USA30, GBPUSD, and USDJPY were all still net-negative for the
week. The user is about to start a round of testing/experiments aimed at
bringing those 5 symbols to profit, and doesn't want that testing to have
any chance of touching XAUUSD's already-working setup.

**What this actually means going forward**: XAUUSD keeps trading exactly
as it does right now — nothing stops, nothing about its own behavior
changes. What changes is the standing default for FUTURE rule/logic work:
`CLAUDE.md`'s point 1 ("applies to all 6 symbols unless the user scopes
it to specific ones") is now inverted specifically for XAUUSD — any
future rule/logic change applies to USA500/USA100/USA30/GBPUSD/USDJPY by
default, and is skipped for XAUUSD unless the user explicitly names it
too. Recorded in `CLAUDE.md` (new section, "XAUUSD is frozen") and in the
`bot-rules-numbering-process` memory file, so this survives across
sessions without needing to be re-stated.

**No code/config value changed** — XAUUSD's SL/TP/trailing values were
already fully isolated per-symbol by the existing `SymbolConfig`
architecture; this version exists purely to lock in the point-in-time
decision and the data that justified it.

## Baseline at save time

- `stats/trade_history_at_v2.18_save.db` — snapshot at the moment this
  decision was recorded.
- XAUUSD week of 23-29 Aug: 607 trades, 49.3% win, **net +11,084.00**.
- The other 5 symbols, same week: USA500 -114.99, USA100 -779.52, USA30
  -581.30, USDJPY -2,013.96, GBPUSD -2,983.00 (all net-negative).

## Next version

[v2.19](../v2.19/NOTES.md) — first round of experimental SL/TP changes
on USA500/USA100/USA30 (all unified to 1:1 R:R at either 2.50 or 25,
per symbol), following directly from this freeze. XAUUSD untouched.
