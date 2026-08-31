# v2.19 — 2026-08-29

Previous version: [v2.18](../v2.18/NOTES.md)

## What changed since v2.18

First round of experimental SL/TP changes on the three currently-losing
symbols selected for testing (XAUUSD excluded per v2.18's freeze). Values
only — no rule/logic touched anywhere.

### USA500

- Rule 7 (REVERSE) SL: **5.00 → 2.50** (`reversal_fixed_sl_points`)
- TP unified to **2.50** across all three rules (was 5.5 for Rule 2 via
  `trend_tp_points`, and 5.5 for Rule 5/7 via `scalp_tp_points`)
- Rule 2/Rule 5 SL untouched (already 2.50 each)

**Final USA500 levels**: Rule 2 = 2.50/2.50, Rule 5 = 2.50/2.50, Rule 7 =
2.50/2.50 — uniform 1:1 across the board.

### USA100

**CORRECTED same day** — first pass unified everything to 25; the
user's actual intended number was **15**, corrected immediately before
any real data was collected on the 25 value. Final, as actually deployed:

- ALL SL and TP, all three rules, unified to **15**:
  - Rule 2 SL: 30 → 15, Rule 2 TP: 30 → 15
  - Rule 5 SL: unchanged at 15, Rule 5 TP: 30 → 15
  - Rule 7 SL: (inherits Rule 5's 15, unchanged); Rule 7 TP: 30 → 15
    (follows Rule 5's TP, as it always has)

**Final USA100 levels**: Rule 2 = 15/15, Rule 5 = 15/15, Rule 7 = 15/15.
Worth watching closely — Rule 2's SL alone at 15 was already tried once
before (v2.13, settled there after two reversals, later reverted to 30 in
v2.15 after "no faida" over ~4 real days) — this round revisits that same
number, now alongside a matching TP=15 everywhere too, which wasn't part
of that earlier trial.

### USA30

- ALL SL and TP, all three rules, unified to **25** first:
  - Rule 2 SL: unchanged (already 25), Rule 2 TP: 50 → 25
  - Rule 5 SL: 50 → 25 (was deliberately held wider/independent since
    2026-08-14 as this symbol's best-performing rule — that distinction
    is gone now), Rule 5 TP: 50 → 25
  - Rule 7 SL: unchanged (already 25), Rule 7 TP: 50 → 25 (follows Rule 5)
- **Then, later the same day, SL cut again to 15 (TP left at 25)**: "usa30
  k sl tamam 15 per kerdo." All three rules' SL: 25 → 15. TP untouched at
  25 — no longer 1:1, now ~1.67:1 reward:risk (25 TP vs 15 SL). Rule 5's
  SL in particular has now moved 50 → 25 → 15 in the same day.

**Final USA30 levels**: Rule 2 = SL 15/TP 25, Rule 5 = SL 15/TP 25,
Rule 7 = SL 15/TP 25.

**REASON** (user's own words, verbatim): "USA500 reversal rule 7 k liye
sl ko 2.5 kerdo. with_trend/Scalp/Reverse ka tp 2.5 kerdo. USA100 aur
USA30 per tamam sl/tp 25 per set kerdo." No further reasoning given
beyond the direct instruction — these are experimental values to observe
against real trade data, not conclusions drawn from prior analysis (unlike
most earlier SL/TP changes in this project's history, which were each
preceded by a specific per-rule stats review). Flagged explicitly here so
a future review knows this round was exploratory.

**IMPACT**: all three symbols move to (or stay at) 1:1 R:R across every
rule. USA500's Rule 7 loss-per-stop-out shrinks (was double Rule 2/5's).
USA100's Rule 2 stop-outs get cheaper (30→25) but Rule 5/7's get more
expensive (15→25) while their TP shrinks (30→25, wins secured faster but
smaller). USA30's Rule 5 loses its "deliberately wider, best-performing"
status entirely — worth watching closely, since that was this symbol's
one clear strength before this change.

**Confirmed separately, same session**: all 6 symbols' trailing SL
already uses the unified continuous %-of-TP mechanism (25% activate / 25%
lock-back / 12.5% min-lock) with zero fixed-rate overrides remaining
anywhere in `config.py` — nothing needed changing there, this was a
verification only, in response to the user asking that trailing SLs
advance by percentage, not a fixed rate.

**Verified**: `python -m py_compile` clean; loaded `config.SYMBOLS` directly
and printed each symbol's actual resolved SL/TP values to confirm they
match exactly (see table above) before restarting. Restarted the bot —
caught and cleaned up a real duplicate-process situation first (two
`pythonw.exe` + two `terminal64.exe` already running from earlier in the
session, likely another restart that didn't fully clean up before a new
one started; identified the live one via `Get-NetTCPConnection -LocalPort
5050`, killed everything, relaunched once cleanly). Confirmed after
restart: single process, `bot.lock` held, all 6 symbols `connected: true`.

## Baseline at save time

- `stats/trade_history_at_v2.19_save.db` — snapshot taken at restart,
  immediately after deployment and verification.

## Next version

(none yet)
