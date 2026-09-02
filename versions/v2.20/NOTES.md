# v2.20 — 2026-09-01/02

Previous version: [v2.19](../v2.19/NOTES.md)

## What changed since v2.19

### Symbols now grouped into 3 explicit performance-isolated buckets

User's own framing: "mein sub ko alag alag un ki performance k hisab se
isolate karon ga... hamre pass 3 diffrent patterns ho jaein ge: 1. gold,
2. usa500/usa100/usa30, 3. currency pairs." Gold was already isolated
(v2.18). This version formalizes **indices** (USA500/USA100/USA30) as
its own group too — **currency pairs (GBPUSD/USDJPY) explicitly get NO
change this round**, per direct instruction.

### New mechanism: Scalp SL profit-close skips the immediate reversal (indices only)

This grew directly out of the Rule 4 loss-cooldown impact analysis
(discussed same session — that mechanism proved net-beneficial for
WITH_TREND). The user asked whether the same profit/loss-conditional
idea could extend to Rule 5 (scalp) and Rule 7 (reversal).

**Data pulled before deciding** (all-time, immediate <5s scalp-SL→reversal
pairs):

| Symbol | Loss-triggered reversal | Profit-triggered reversal |
|---|---|---|
| USA500 | 19x, 74% win, net **+3.00** | 19x, 63% win, net -8.36 |
| USA100 | 13x, 69% win, net **+34.53** | 18x, 56% win, net -16.70 |
| USA30 | 8x, 88% win, net **+81.10** | 27x, 52% win, net **-147.70** |
| XAUUSD | 12x, 8% win, net **-1,689.00** | 18x, 44% win, net -234.00 |

**Key finding**: for the 3 indices, loss-triggered immediate reversal is
net-POSITIVE and profit-triggered is net-NEGATIVE — the OPPOSITE pairing
from XAUUSD (where both are negative, loss catastrophically so). This is
why XAUUSD gets no change here (frozen anyway, v2.18) and the indices get
an asymmetric fix matching their own data.

**Reversal (Rule 7) loss-side design — proposed by the user mid-discussion,
then explicitly walked back once the data above was shown.** User's
initial fuller proposal (verbatim): "ager sl loss may hit ho... 3 minute
ka cooldown... andhi opposite direction ki trades ban ho jaein gi... ager
uska rolling DI SL k time se ziada hoa to reversal open kerde otherwise
wait kare... ek regime may ek hi reversal allow hai yeh aeise hi rahega"
— a real cooldown+confirmation gate for the LOSS-triggered reversal path,
mirroring Rule 4's own shape. But after seeing the data (loss-triggered
reversal is net-POSITIVE for all 3 indices), the user's own explicit
correction was: "indices per loss triggered immediate reversal acha kaam
ker raha hai us ko rehne do as-is... sl in loss hit to existing immediate
wala system implemented rahega" — i.e. the loss-side stays EXACTLY as it
is today (immediate, zero-confirmation), specifically BECAUSE the data
showed it already works well for these 3 symbols. This is a genuine,
data-informed decision NOT to build the cooldown+confirmation redesign
for indices — not a deferred/open item.

**What was actually implemented** (`config.SCALP_SL_PROFIT_SKIP_REVERSAL`,
new per-symbol flag, `True` for USA500/USA100/USA30 only, `False`
default everywhere else — XAUUSD and GBPUSD/USDJPY completely
unaffected):
- A COUNTER_SCALP position whose **trailing SL closes it while still in
  PROFIT** now skips `_reverse_scalp()`'s immediate/zero-confirmation
  reversal entirely, and instead re-arms scalp via the exact SAME
  mechanism Rule 6's own TP outcome already uses (`scalp_continuation_gate`
  / `_check_rule6_gate`, completely unchanged, NOT duplicated — new thin
  function `_rearm_scalp_after_profit_sl` exists only for accurate log
  text, calls into the identical existing state/clearing logic).
- A **loss-closed** scalp SL is **completely unaffected** — still the
  existing, unchanged `_reverse_scalp()` immediate reversal, exactly as
  before this version.
- Rule 7's "one reversal per DI regime" cap (`scalp_reversal_used`) is
  untouched, per explicit instruction ("yeh aeise hi rahega").
- The existing scalp re-arm system itself (Rule 6's gate/clearing logic)
  was NOT touched or modified in any way, per explicit instruction.

**IMPACT**: for USA500/USA100/USA30 only, removes the historically-net-
negative "reversal after a profitable scalp exit" pattern entirely,
letting scalp re-arm through its own proven confirmation gate instead.
The historically-net-positive "reversal after a losing scalp exit"
pattern is fully preserved, unchanged.

## Baseline at save time

- `stats/trade_history_at_v2.20_save.db` — snapshot taken at restart,
  after deployment and verification.

## Next version

[v2.21](../v2.21/NOTES.md) — XAUUSD-only Rule 7 (Scalp SL hit) redesign:
the immediate, zero-confirmation reversal is replaced with a Rule-4-
shaped gate (cooldown + DI/candle confirmation) for both a loss- and a
profit-closed scalp SL alike, per real data showing both outcomes
net-negative for Gold on the reversal leg.
