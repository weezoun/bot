# Current strategy — Version 2 reference (2026-08-11)

## Confirmed rules (numbered, dictated one at a time — LOCKED, see below)

Starting 2026-08-12, rules are being given one at a time by the user and
recorded here numbered, matching the dashboard's single "Rules" section
exactly (numbered cards there are confirmed; unnumbered cards are
pre-existing description not yet individually dictated in this form).
**Once a rule is implemented it is not modified again without explicit
permission** — this is a standing, inviolable instruction, not a
suggestion. Each rule also lives in its OWN isolated function/state (see
"Isolation architecture" below) — editing one must never be able to
affect another.

**Rule 1 — no trade opens on the candle the bot started/restarted on.**
Whenever the bot starts or restarts (fresh process launch, or a resume
via the dashboard's Start button), it captures the bar_time of whatever
M15 candle is forming at that moment and blocks every order-placing
action (BUY, SELL, FLIP's close-then-open) until a genuinely NEW candle
begins — a real next-candle wait, not a fixed delay. Once that new candle
starts, normal signal evaluation resumes with no special carry-over.
Applies identically to all 6 symbols. Implemented in `bot_runner.py`
(`BotState.startup_bar_time` / `startup_gate_cleared`, reset in
`SymbolBot.start()`, enforced in `bot_tick()`). This is a pre-entry gate,
not an entry condition — it never appears inside an opened trade's
`open_reason` since no trade can open while it's active; only rules that
actually trigger/confirm an entry get tagged into a trade's reason text.

## Isolation architecture (2026-08-12, standing requirement)

Explicit instruction from the user: every rule must live in its own
isolated function/state, so editing one rule can never accidentally
affect another. Rule 3's first implementation violated this (a shared
`momentum_gate` dict with a `'reason': 'TP'/'SL'` tag branching inside one
shared function) — caught and corrected immediately. Current architecture:

- **Rule 3** owns `BotState.rule3_gate` and `bot_runner._check_rule3_gate()`
  — a fully self-contained method with its own DI/candle logic, called
  every tick. Nothing else sets, clears, or reads its internals.
- **Rule 4** owns `BotState.rule4_gate` and `bot_runner._check_rule4_gate()`
  — same pattern, entirely separate state and logic from Rule 3.
- **Rule 2** (`evaluate_entry()`) only ever does a trivial presence/side
  check against `rule3_gate`/`rule4_gate` (`gate and gate['side'] == side`)
  — it never computes or duplicates either gate's clearing conditions.
  Editing Rule 3's or Rule 4's own clearing logic can never require
  touching Rule 2, and editing Rule 2 can never require touching either
  gate's clearing logic.
- The old shared `momentum_gate` mechanism is retired for WITH_TREND
  purposes (`_momentum_recovered()` still exists, but is now only used by
  `evaluate_flip()`, always called with `momentum_gate=None`, and by
  scalp's not-yet-formalized reversal-fallback mechanism).
- **Isolation is about WORKING CODE, not diagnostic text** (clarified
  2026-08-12, corrected same day after an overcorrection): rules must not
  call each other's functions or share state/gates — that's the actual
  requirement. Informational text that tells the user which rule is
  currently active (e.g. the dashboard's "Rule 3 gate active" /
  "Rule 4 gate active" messages) is useful and stays — it was briefly
  removed by mistake, then restored. The line to hold is: no rule's
  *function* depends on another rule's function/state to work; a rule's
  *log line or diagnostic message* naming another rule to explain the
  current situation is fine and wanted.

**Rule 2 — WITH_TREND entry** (2026-08-12, merges the user's new wording
with the pre-existing detailed checks into one rule, superseding the old
unnumbered "WITH_TREND entry" card): trend UP/DOWN (not NEUTRAL), ADX >=
ADX_MIN, DI aligned with the trend, RSI inside its band, the **last FULLY
CLOSED candle in the SAME direction** as the trade, AND the **currently
FORMING candle must NOT be forming in the opposite direction**, AND
neither Rule 3's nor Rule 4's gate active for that side, flat position,
one-entry-per-candle, margin gate. Tagged into the trade's `open_reason`
as `"Rule 2: ..."` on every WITH_TREND entry via `evaluate_entry()`.
Applies identically to all 6 symbols.

**Rule 3 — WITH_TREND TP hit** (2026-08-12): existing gate mechanism
confirmed correct as-is, plus one new check — the CURRENTLY FORMING
candle must not be in the opposite direction from the previous candle.
Own isolated gate/function (see above). Originally cleared once: a new
CLOSED candle beyond the TP candle had printed, that side's DI was above
the immediately preceding candle, that closed candle agreed in color, AND
the forming candle wasn't moving opposite. Verified with a standalone
test. Applies identically to all 6 symbols.

**Correction, 2026-08-13: the "wait for a new CLOSED candle" requirement
removed — clears WITHIN the same candle now.** User: a WITH_TREND trade's
TP hitting was blocking the trend from continuing for the rest of that
candle, which was itself hurting trend continuation. Asked for this fixed
on BOTH Rule 3 and Rule 6, but only after PROPER confirmation — RSI, ADX,
ATR, rolling DI, DI, candle color — not by removing the gate outright.
`_check_rule3_gate` no longer requires `closed_snap.bar_time >
gate['bar_time']`; instead it clears the moment ALL of the following are
true on LIVE data: `ADX >= ADX_MIN`, DI dominant in the trade's direction
(`di_plus > di_minus` for BUY) AND rolling (above the immediately
preceding candle), RSI inside the WITH_TREND band (`_rsi_buy_ceiling`/
`_rsi_sell_floor`, same helpers Rule 2 itself uses), ATR strong, and the
CURRENTLY FORMING candle DEFINITELY the required color (`_bullish_candle`/
`_bearish_candle` — an absolute requirement now, stronger than the old
"not opposite" check). No longer takes a `closed_snap` parameter at all
— everything is read from `live_snap`. Verified with a standalone test:
confirmation failing (e.g. RSI too extended) keeps the gate active even
mid-candle; full confirmation clears it immediately, same bar_time as the
TP. Applies identically to all 6 symbols.

**Rule 4 — WITH_TREND SL hit** (2026-08-12): trade recorded to history
(close_reason label — see note below on trailed-into-profit closes).
First, on the SAME candle the SL happened: ALL new entries blocked —
WITH_TREND and scalp, either side (reuses the existing generic
`last_bar_time`/one-entry-per-candle mechanism, not a rule-owned field).
From the next candle onward, BOTH systems are live again, each firing on
its own normal conditions. Additionally, for the SL'd side specifically:
rolling DI must be rising AND the forming candle must DEFINITELY be the
required color (green for BUY, red for SELL) — an absolute requirement,
not a "not opposite" comparison against the previous candle like Rule 3.
Own isolated gate (`rule4_gate`) / function (`_check_rule4_gate`).
Verified with a standalone test (flat forming candle does NOT clear the
gate — only a definite matching color does). Applies identically to all
6 symbols.

**Rule 5 — Scalp (COUNTER_SCALP) entry** (2026-08-12, merges the user's
edits into the pre-existing scalp-entry card): trend UP/DOWN, DI opposes
the trend (counter-trend by definition), RSI inside the scalp band, ATR
strong, **rolling DI** (this side's DI above the immediately preceding
candle), AND the **currently forming candle must definitely be the same
direction as the trade** (red for SELL, green for BUY — an absolute
requirement, not "not opposite"; checked live so a genuine move is
caught early rather than waited out), `scalp_armed` True,
flat/one-per-candle/margin. Tagged into the trade's `open_reason` as
`"Rule 5: ..."`. The scalp_armed re-arm mechanism and the "same gates as
WITH_TREND" cross-reference were both removed from this rule's own
description at the user's direction — Rule 5 describes only what scalp
entry itself does; scalp's re-arm behavior belongs to its own TP/SL
rules (not yet dictated), and flat/margin/one-per-candle are generic
gates, not something to describe by comparison to another rule. Implemented
directly in `evaluate_entry()`'s `scalp_ok`, both branches — no new
isolated gate/function needed, since this isn't a stateful post-close
gate like Rule 3/4, just two more direct conditions alongside the
existing ones (same pattern as Rule 2's own additions to `trend_ok`).
Applies identically to all 6 symbols.

**Correction, same day: RSI and ATR removed from Rule 5's own decision.**
User caught the ATR "strong" filter blocking a live scalp on the
dashboard (USA500, TRENDING_DOWN, ATR weak, +DI(29.4) > -DI(17.8)) and
said Rule 5's decision should rest **only** on DI, rolling DI, and
forming-candle direction. Removed `snap.rsi < RSI_SCALP_SELL_MAX` /
`snap.rsi > RSI_SCALP_BUY_MIN` and `snap.atr_strong` from `scalp_ok` in
both `TRENDING_UP` and `TRENDING_DOWN` branches, and dropped the matching
RSI/ATR lines from `_skip_scalp_sell_reason`/`_skip_scalp_buy_reason` so
the SKIP diagnostic only cites the three checks that still apply. RSI and
ATR fields stay on `Snapshot`/`SymbolConfig` (used elsewhere — WITH_TREND
RSI band, SL/TP sizing) — only Rule 5's own read of them was removed;
nothing shared was deleted. Verified with a standalone test: a scalp with
weak ATR and rolling DI/candle satisfied now fires; the exact dashboard
scenario (rolling DI not yet satisfied) still correctly SKIPs, on DI
grounds alone, confirming the block wasn't only an ATR artifact.

**Correction, same day: literal DI cross removed from Rule 5 too.** User
explained the original reason rolling DI was added: by the time DI
actually crosses (this side's DI > the other side's), the move is often
already well underway — too late for a scalp. The as-implemented `scalp_ok`
still required BOTH the literal cross (`di_minus > di_plus` / `di_plus >
di_minus`) AND rolling DI — so it was still gated on the same slow
condition rolling DI was meant to route around. Removed the literal cross
check entirely from both `TRENDING_UP` and `TRENDING_DOWN` branches;
`scalp_ok` is now just rolling DI (this side's DI rising vs the
immediately preceding candle) AND forming-candle direction AND
`scalp_allowed`. Reason strings updated to drop the now-absent
`-DI>+DI`/`+DI>-DI` phrasing. Verified with a standalone test: a case
where the scalp side's DI is still numerically BELOW the other side's
(no cross yet) but rising vs. the prior candle, with a matching forming
candle, now correctly fires — confirming genuinely earlier entry than
before.

**Correction, 2026-08-13: ADX/RSI/ATR RE-ADDED to Rule 5.** A day after
the removals above, direct data review (prompted by the user asking to
compare XAUUSD's rules/behavior now vs. ~20 hours earlier, since it had
flipped from profit to loss) found a real inflection: XAUUSD was +2,455
across 22 trades before 2026-08-13 06:00, then -3,562 across 16 trades
after — and the losing `COUNTER_SCALP` entries were firing on almost pure
noise: `"-DI 11.9 rising vs prior (11.8)"`, `"-DI 15.5 rising vs prior
(15.5)"` — tiny upticks (as little as 0.1) at weak absolute DI levels
(11-19), with no ADX/RSI/ATR floor left to filter them out since
2026-08-12's removals. User's direct diagnosis: "chopy trades mein enter
ho raha hai yeh" (entering on choppy/noisy conditions) — asked for
ADX/RSI/ATR back specifically as the noise filter, explicit permission to
modify this already-locked rule. Re-added `snap.adx >= cfg.ADX_MIN`,
`snap.rsi < RSI_SCALP_SELL_MAX`/`snap.rsi > RSI_SCALP_BUY_MIN`, and
`snap.atr_strong` to `scalp_ok` in both branches, alongside the rolling-DI
and forming-candle checks (unchanged) — restored the matching lines in
`_skip_scalp_sell_reason`/`_skip_scalp_buy_reason` too. The literal DI
cross stays removed — not asked for, and rolling-DI-catches-it-early is
still the intended design; this layers a noise filter back on top of that,
it doesn't reverse it. Applies identically to all 6 symbols (Rule 5's
standing requirement). Verified with a standalone test reproducing the
exact noisy real trade (ADX ~8, DI 11.9 vs prior 11.8) — now correctly
blocked — plus confirming a genuinely strong-conditions case still fires,
and that RSI/ATR each block independently when only one is weak.

**Correction, same day: ADX_MIN gate removed from Rule 5.** User found it
was blocking scalp entries outright ("ADX ki wajah se trade hi open nahi
hui") and pointed out DI's own calculation is sufficient for a
counter-trend scalp — ADX wasn't adding value there. Previously ADX_MIN
was a single blanket check at the top of `evaluate_entry()`, gating BOTH
scalp and WITH_TREND identically before either was even evaluated;
removed that blanket check and moved `snap.adx >= cfg.ADX_MIN` into
`trend_ok` directly — so it now applies to Rule 2 (WITH_TREND) only,
completely unchanged there, while Rule 5 (scalp) no longer checks ADX at
all. `_skip_trend_buy_reason`/`_skip_trend_sell_reason` updated to
surface an ADX-too-low reason for WITH_TREND specifically, since the old
blanket top-level message is gone. Verified with a standalone test: a
scalp with ADX well below `ADX_MIN` now fires; a WITH_TREND entry with
the same low ADX is still correctly blocked.

**Rule 6 — Scalp TP hit** (2026-08-12, confirmed as-is then extended):
trade recorded to history as a win. Originally: **on the SAME candle: ALL
new entries were blocked — WITH_TREND and scalp, either side** (found
missing in an earlier pass — WITH_TREND wasn't blocked at all right after
a scalp TP; fixed by reusing the existing generic `last_bar_time`
one-entry-per-candle mechanism, same as Rule 4 does). Does NOT re-arm
`scalp_armed` immediately — sets `scalp_continuation_gate` instead. For
scalp specifically, the gate clears via rolling DI (this side's DI above
the immediately preceding candle) AND the currently forming candle
DEFINITELY the required color — checked live, in its own fully
independent implementation (`_check_rule6_gate`), zero shared code with
any other gate. Once satisfied, `scalp_armed` becomes True again, but the
next scalp still independently needs every Rule 5 check — this only
lifts the "already scalped this regime" cap.

**Correction, 2026-08-13 (same change as Rule 3, requested together):**
the blanket same-candle block on ALL entries is REMOVED —
`_rearm_scalp_after_tp` no longer sets `last_bar_time`, so WITH_TREND (and
scalp) are free to fire again immediately on their own normal conditions,
same candle or not. The original reason for the block (a scalp win
getting chased and given back — USA100, 2026-08-11) is now handled by
strengthening `_check_rule6_gate` instead of blocking outright: it also no
longer requires `live_snap.bar_time > gate['bar_time']` (a new candle
starting), and clears the moment full confirmation passes on live data —
`ADX >= ADX_MIN`, this side's DI still dominant (opposing the big trend)
AND rolling, RSI inside the scalp band, ATR strong, AND the forming
candle definitely the required color. The idea: a genuine exhaustion/
reversal should fail this confirmation regardless of which candle it's
on, while genuine continuation should pass it — same-candle timing itself
is no longer the deciding factor. Verified with a standalone test:
confirmation failing keeps both the WITH_TREND block gone (no
last_bar_time set at all) and the scalp gate closed; full confirmation
clears the scalp gate immediately, same bar_time as the TP.

**Correction, 2026-08-13 (same day, follow-up): a SEPARATE generic
same-candle cap was still silently overriding the Rule 3/6 fix above —
removed.** User observed XAUUSD's WITH_TREND TP hit 31 seconds into its
own candle, then the dashboard kept showing a fully-confirmed Rule 2
SELL signal blocked by "Already entered this M15 — waiting next bar" for
the rest of that candle — even after restarting the server. Traced this
to `bot_tick()`'s post-execute handling: `if after != before or
sig.action.startswith('CLOSE'): self.state.last_bar_time =
live_snap.bar_time` — a GENERIC mechanism that set `last_bar_time`
(the same field `already_entered_this_bar` checks) after ANY successful
entry, TP, SL, or FLIP, completely independent of Rule 3/Rule 6's own
gates. Since it fired even on a clean TP, it kept blocking re-entry for
the rest of that candle regardless of whether Rule 3's confirmation had
already cleared — defeating the whole point of the same-day fix above.
User: this cap "rule ka hissa nahi hai" (isn't part of a rule) and should
have been removed already when Rule 3/6 were fixed. Removed the generic
set entirely from `bot_tick()`. `last_bar_time` is now set ONLY by
Rule 4's own explicit, locked "block all entries this candle after an
SL" behavior (`_classify_and_record_close`) — completely untouched, its
own separate code path. One other `last_bar_time` set (inside Rule 7's
`_reverse_scalp`, marking the bar acted-on right after a reversal opens)
was deliberately left alone — it's part of Rule 7's own function, wasn't
shown/discussed in this exchange, and touching it would be outside what
was asked. Rule 2's and Rule 5's dashboard cards, which used to list
"not already entered this M15 candle" as one of their own conditions,
updated to reflect the removal — the "must be flat" check (no two
simultaneous positions) is unaffected and still fully enforced.

**Conflict found and resolved during implementation** (flagged per the
user's explicit invitation to surface anything conflicting): the
pre-existing `scalp_continuation_gate` field/functions were shared
between TWO cases — the actual scalp-TP case (Rule 6) AND a separate,
not-yet-formalized case (a scalp SL whose immediate reversal attempt
didn't end up opening — cap already used / insufficient margin / order
failed; see `_reverse_scalp`). Redesigning Rule 6's clearing logic would
have silently changed that second, un-dictated case too. Split into two
fully separate mechanisms: Rule 6 keeps `scalp_continuation_gate` /
`_check_rule6_gate` (new logic, described above); the other case moved to
its own new field `scalp_no_reversal_gate` / `_check_scalp_no_reversal_gate`,
preserving its EXACT prior behavior (rolling DI + last CLOSED candle
color, via `strategy._momentum_recovered`, unchanged) — Rule 6 does not
affect it. Verified with a standalone test covering both gates
independently, plus a direct isolation check that Rule 6's clearing
function never touches `scalp_no_reversal_gate`.

**Also fixed in passing**: `_check_rule4_gate` had a stray duplicate log
line ("Scalp re-armed...") left over from development — unrelated to
Rule 4's actual logic (which was unaffected), just a leftover incorrect
log statement. Removed.

**Rule 7 — Scalp SL hit** (2026-08-12, merged with the former "Rule 8 —
Reverse entry" the same day — see correction note below): trade recorded
to history as a loss; triggers an immediate reversal attempt into the
opposite side — basis purely DIRECTIONAL (the opposite of whichever
scalp just stopped out), zero RSI/candle-color/DI-cross confirmation,
scalp-tight SL/TP sizing regardless of the mode label `classify_side()`
assigns it internally, trailing off its own actual TP distance once
open. Gated by three preconditions before it's even attempted: the
one-reversal-per-DI-regime cap not already used, `should_take_trade()`
(margin) passing, and `send_order()` actually confirming a real ticket —
the cap is only consumed, and old gates only cleared, once a real ticket
is confirmed open, so a blocked or failed attempt never burns it. Two
outcome handlers for once that reversal is open, added after analysis
confirmed no conflict with Rule 3/Rule 4 (see below):
- **Reversal TP hits** → scalp is explicitly re-armed
  (`_on_reversal_tp`). Unlike an ordinary WITH_TREND TP (where scalp is
  typically already armed), this one directly follows the scalp SL that
  disarmed it — nothing else on this path would re-arm it otherwise, so
  scalp would stay stuck disarmed until a full DI regime flip even
  though the reversal won. Found missing, confirmed as a real gap.
- **Reversal SL ALSO hits** → the existing rolling-DI benchmark
  mechanism (`scalp_rearm_gate` / `_check_scalp_rearm`, unchanged) —
  benchmark = the stronger of the two failure-point DI readings.

**Analysis done before implementing, per the user's explicit request**:
the user proposed a SECOND, separate DI benchmark for WITH_TREND's own
re-entry after the reversal's SL ("with_trend ka benchmark woh DI hoga
jahan se uska reversal start hua"). Flagged as redundant/conflicting: the
reversal is always WITH_TREND-mode, so its SL already flows through
Rule 4's own complete, locked mechanism (same-candle block + rolling DI
+ definite forming-candle color) — adding a second gate for the exact
same re-entry decision would create two mechanisms governing one
outcome. User confirmed: use Rule 4's existing mechanism, no new
WITH_TREND-side gate. The scalp-side benchmark, by contrast, already
matched the pre-existing `scalp_rearm_gate` almost exactly — formalized
as part of Rule 7 with no new logic needed there.

**"One reversal per DI regime" cap** — explicitly discussed and kept
unchanged (`scalp_reversal_used`), not redefined to allow multiple
reversal attempts per regime. Reasoning: the reversal is a deliberately
risk-capped, zero-confirmation reactive trade; loosening the cap would
reintroduce the "major loss" risk this rule was meant to fix.

**Isolation**: the reversal-outcome handling used to be written INLINE
inside Rule 3's and Rule 4's own code blocks (checking `scalp_reversal_di`
right there) — exactly the kind of entanglement flagged before. Extracted
into two new, fully separate functions (`_on_reversal_tp`,
`_on_reversal_sl`), called independently alongside — never from inside —
Rule 3's/Rule 4's own gate-setting code. Rule 3's and Rule 4's own
behavior is byte-for-byte unchanged; verified with a standalone isolation
test that neither new function ever touches `rule3_gate`/`rule4_gate`.

**Correction, same day: "Rule 8 — Reverse entry" merged back into Rule 7.**
It had briefly existed as its own numbered rule, reasoned as parallel to
the Rule 5 vs. Rule 6/7 split (entry mechanics vs. outcome handling). The
user pushed back directly: reversal isn't like scalp entry (Rule 5),
which independently re-evaluates its own conditions every tick and can
fire many separate times on its own; the reversal has NO independent
trigger at all — it only ever fires as a direct, mechanical consequence
of Rule 7's own trigger (a scalp SL), with zero conditions of its own.
Since there's no other path to it and no independent re-evaluation, the
Rule 5-vs-6/7 parallel doesn't actually hold. Merged the "Reverse entry"
content directly into Rule 7 above (trigger mechanics + outcome
handling, one comprehensive rule) — no code changes (the underlying
functions were already separate/isolated internally, that stays), just
the dashboard numbering/presentation. Entry reason text re-tagged
`"Rule 7: ..."`.

**Open question raised alongside Rule 4, not yet acted on**: the user
asked why a trailed-into-profit SL still gets `close_reason = "SL"` in
trade history. Clarified directly (not silently changed): `"SL"`/`"TP"`
is a *proximity* label — whichever level (SL or TP) price was nearer to
when the position vanished — not a win/loss label. Actual win/loss stats
(`trade_store.get_stats`) are computed from real `profit`, independent of
this label, so a trailed SL that closed in profit is already correctly
counted as a win in the stats — only the "Result" column's *label* could
look like "SL = loss" at a glance when it wasn't. No code changed on this
point; flagged for the user to decide if the label itself should change.

---

Two systems per symbol — WITH_TREND and COUNTER_SCALP (scalp) — both driven
off the same M15 snapshot (EMA50/200, ADX, +DI/-DI, RSI, ATR). All 6 symbols
(USA500, USA100, USA30, XAUUSD, GBPUSD, USDJPY) run the **exact same logic**
in `strategy.py` — nothing is symbol-specific in the decision code itself.
Only the **numbers** differ per symbol (`config.py`), because each
instrument's price scale and typical move size is different.

## Gates that apply before either system (same for all 6 symbols)

- **Trend must be UP or DOWN**, not NEUTRAL (50EMA vs 200EMA) — if NEUTRAL,
  bot does nothing at all.
- **ADX >= ADX_MIN (15)** — same value on all 6 symbols, no exceptions. If
  ADX is below 15 on a symbol right now, that's real market condition (weak
  trend), not a bug or a symbol-specific lock.
- **One position at a time per symbol.**
- **One entry per M15 candle.**
- **Margin gate** — no new order if `margin/equity > 10%`.

---

## WITH_TREND

**Entry:** DI agrees with the big trend (+DI>-DI for BUY, -DI>+DI for
SELL), RSI inside a band (40–80 normally, wider to 90/10 if ADX confirms a
strong trend), the **last FULLY CLOSED** M15 candle agrees in color (green
for BUY, red for SELL — corrected 2026-08-11, see below), and the
rolling-DI gate (below) is clear.

**Sizing:** SL = ATR × 0.75 (all symbols) **except USA30**, which uses a
flat 50pt SL regardless of ATR (see "USA30 is different" below). TP = a
**fixed points value** per symbol (not ATR-based) — see the table.

**On TP hit:** profit is secured. The bot does **not** immediately look for
another same-direction WITH_TREND entry — the rolling-DI gate (below) opens
up for that side, blocking re-entry until it clears.

**On SL hit:** same rolling-DI gate opens up, for the same reason (avoid
walking straight back into the same losing move).

**Trailing** (every open position, all modes — see "Trailing" section below):
once profit reaches 40% of that position's OWN actual TP distance, SL
trails to stay 30% of TP behind current price, guaranteeing at least 15%
of TP locked in. Runs every tick, so it keeps advancing as price keeps
moving in favor.

---

## Scalp (COUNTER_SCALP)

**Entry (Rule 5):** ADX >= ADX_MIN, RSI inside the scalp band, ATR
"strong", rolling DI (this side's DI above the preceding candle — no
requirement the side already be dominant over the other, unlike a literal
cross), and the currently forming candle definitely the same direction as
the trade (red for SELL, green for BUY), and `scalp_armed` is currently
True. RSI/ATR were removed 2026-08-12, then RE-ADDED 2026-08-13 — data
showed rolling-DI-alone fired on pure noise in choppy conditions (e.g.
XAUUSD entries like "-DI 11.9 rising vs prior 11.8"); user asked for
ADX/RSI/ATR back as the noise filter. The literal DI cross stays
removed — rolling DI catching a move before it fully crosses is still
the intended earlier-entry design; ADX/RSI/ATR layer a noise filter back
on top of that, they don't reverse it.

**Sizing:** SL = `max(ATR × 0.8, a per-symbol floor)` **except USA30**
(flat 50pt, same override as WITH_TREND there), **USA100/GBPUSD/USDJPY**
(flat SL, same `FIXED_SL_POINTS` override as WITH_TREND on those symbols
too, applying uniformly to WITH_TREND AND scalp AND reversal — see
per-symbol table above; USDJPY briefly had a scalp-only 0.025 cut,
superseded 2026-08-13 back to the uniform flat value), and **XAUUSD**
(scalp/reversal-ONLY flat 2.00pt override via `SCALP_FIXED_SL_POINTS` —
WITH_TREND SL on XAUUSD stays ATR-based, unlike USA100/GBPUSD/USDJPY
where the same override number applies to both modes; added 2026-08-13,
requested directly). TP = fixed points per symbol, unaffected by any of
these SL overrides. **Trails just like WITH_TREND now** (see
"Trailing" below) — previously scalps were
explicitly excluded from trailing and could run to profit then give it
all back; fixed 2026-08-11.

**On TP hit (Rule 6):** does **not** re-arm immediately. Sets up its own
gate — rolling DI (this side's DI above the preceding candle) AND the
forming candle definitely the required color, checked live — before
another same-direction scalp is allowed. Previously this re-armed
same-candle, which is what caused the USA100 loss-after-TP found
directly; then fixed via a rolling-DI+closed-candle gate; now Rule 6
formalizes the clearing condition to match WITH_TREND's post-SL style
(Rule 4), as its own fully independent mechanism.

**On SL hit → immediate reversal:** the bot tries the *opposite* direction
once, right away, with a **tight (scalp-sized) SL regardless of direction**
— even though the opposite of a counter-trend scalp is usually the
with-trend direction, this reversal is a **zero-confirmation** reactive
trade (no RSI/candle/DI-cross check, just "which way is the big trend"),
so its risk is deliberately capped small. Limited to **one attempt per DI
regime** (`scalp_reversal_used`). This reversal trade also trails once
open, using its own actual (scalp-tight) TP as the trailing reference —
even on the majority of cases where `classify_side()` labels it
'WITH_TREND' internally, since the label was never what its SL/TP were
actually sized from (see "Trailing" below).

**If that reversal ALSO hits SL** (both the scalp and its reversal failed):
no third blind attempt. Instead, a benchmark gets set for scalp re-arm =
whichever of the two failure-point DI readings was stronger. From here on,
scalp re-arms early via **either**: DI crosses that benchmark, or DI rises
2 candles in a row — whichever comes first. The bot otherwise just falls
through to the normal, fully-confirmed evaluate_entry() path.

**If a scalp SLs and the reversal DOESN'T actually open a position** —
three distinct exits inside `_reverse_scalp()`, found together via a full
audit after the first one surfaced from a live report (USA100,
2026-08-11): (1) reversal cap already used this regime, (2) insufficient
margin (`should_take_trade()` false), (3) `send_order()` itself fails
(broker rejection, no tick data, etc.). All three used to just return with
**no re-arm gate set at all**, leaving `scalp_armed` stuck False until a
full DI regime flip (+DI/-DI crossing) — which can take a long time, or
never happen, in a persistently one-sided market (this is exactly what
was observed: DI stayed -DI-dominant for an extended stretch and scalping
silently stopped with nothing watching to re-arm it). (3) had a second,
subtler problem: state (`scalp_reversal_used`, the gates, `scalp_armed`)
used to be mutated BEFORE calling `send_order()`, so a failed order still
burned the one-per-regime reversal cap and left `scalp_reversal_di`
holding a "pending reversal" that would never actually close — a stale
record a later, unrelated WITH_TREND close could have matched against.

Fixed by making all three exits fall through to the same rolling-DI +
last-closed-candle-color gate a scalp TP uses (`scalp_continuation_gate`
via `_rearm_scalp_if_continuing`), and by only mutating state AFTER
`send_order()` confirms a real ticket — the same confirm-before-mutate
pattern `bot_tick()` already used correctly for fresh scalp entries
(`if after > before: ...`), which `_reverse_scalp()` had never matched.

---

## Trailing (corrected 2026-08-11 — now applies to every position)

`bot_runner.trail_all_positions()` runs every tick against every open
position for the symbol, regardless of mode label. Previously it only
trailed positions tagged `mode == 'WITH_TREND'` in `position_modes` —
scalps, and by coincidence some reversal trades, were skipped entirely and
could run into real profit with no protection, then give it all back.

For each position, the trailing math is now sized off **that position's
own actual TP distance** (`abs(p.tp - p.price_open)`, read straight from
MT5), not a `cfg.TREND_TP_POINTS` lookup keyed by mode label. This matters
specifically for the scalp-SL reversal trade: `classify_side()` usually
labels it `'WITH_TREND'` (since the opposite of a counter-trend scalp is
normally the big-trend direction), but `_reverse_scalp()` always sizes its
SL/TP scalp-tight regardless of that label. A mode-keyed lookup would have
trailed it against the WRONG (trend-sized) TP the moment `SCALP_TP_POINTS`
and `TREND_TP_POINTS` ever diverge for a symbol — reading the real `p.tp`
is correct for WITH_TREND, COUNTER_SCALP, FLIP, and the reversal trade all
at once, no mode branch needed.

Thresholds unchanged: activate at 40% of that TP distance, trail 30%
behind current price, guarantee at least 15% locked in.

---

## FLIP — regression found and fixed, 2026-08-12

User asked directly "FLIP ka abhi kya kaam hai, aur jis rule par apply
hona tha wahan apply kyun nahi hua?" — real bug found in my own earlier
work: when Rule 3/Rule 4 were split out of the old shared `momentum_gate`
(same day), `evaluate_flip()` was left checking nothing at all —
`decide()` hardcoded `momentum_gate=None`, silently disabling the gate
instead of rewiring it to `rule3_gate`/`rule4_gate`. This reintroduced
the EXACT same-candle-re-entry bug originally found and fixed on
2026-08-11 (a WITH_TREND TP/SL could immediately reopen the same side via
FLIP, bypassing the block a fresh Rule 2 entry would correctly hit).
Root cause: I over-applied an earlier, narrower correction ("don't
discuss FLIP while defining Rule 2") to mean "FLIP is exempt from these
gates entirely" — it never meant that; FLIP's own gate-respecting
behavior predates the rule-numbering process and was never meant to be
removed. Fixed: `evaluate_flip()` now takes `rule3_gate`/`rule4_gate`
directly (same trivial presence/side-check pattern as Rule 2), and
`decide()` passes them through instead of hardcoding `None`. FLIP's own
confirmation criteria (DI flip/strong + RSI) are unchanged — it still
does NOT carry Rule 2's last-closed-candle-color checks, only the gate.
Verified with a standalone test. FLIP remains outside the numbered-rule
list (not Rule 2/3/4, its own separate mechanism) — this fix only
restores its pre-existing gate-respecting behavior.

## Rolling DI — where it's actually used

**Superseded 2026-08-12 by the isolation architecture above, and the
corresponding dashboard card removed as redundant** (the user asked
directly whether it was still needed once Rules 3/4/5/6/7 each carried
their own rolling-DI description — answer: no, every relevant mechanism
is now documented on its own rule's card). Kept here only as historical
reference: Rule 3, Rule 4, Rule 6, and Rule 7 each now have their OWN
dedicated rolling-DI + candle-color logic, not a shared function.
`strategy._momentum_recovered(side, live_snap, closed_snap, gate)` still
exists with its original logic (new CLOSED candle past the gate + DI
rising vs. the preceding candle + that closed candle agreeing in color),
but is now called from only **one** place, not a numbered rule:
`bot_runner._check_scalp_no_reversal_gate()`. `evaluate_flip()` no longer
calls `_momentum_recovered()` at all as of the FLIP fix above — it checks
`rule3_gate`/`rule4_gate` directly, the same simple presence-check
pattern as Rule 2.

**Which rule does `_check_scalp_no_reversal_gate` belong to?** (asked
directly, 2026-08-12) It lives inside `_reverse_scalp()` — Rule 7's own
function — and fires for the three cases where Rule 7's reversal attempt
does NOT end up opening a position (cap already used / insufficient
margin / order failed). So it's physically Rule 7's code, but its
specific mechanics (rolling DI + last CLOSED candle color, via the
original `_momentum_recovered`) have never been individually
dictated/confirmed by the user the way the rest of Rule 7's content was —
the approved card describes the three preconditions and that a blocked
attempt "never burns the cap", but not what happens to `scalp_armed`
afterward. Left as pre-existing, unformalized behavior until the user
confirms whether to fold it into Rule 7 explicitly.

Rule 2's own last-closed-candle + forming-candle checks (`evaluate_entry`'s
`trend_ok`) are implemented directly in that function now, not via
`_momentum_recovered` — see Rule 2 above.

Separately, `_check_scalp_rearm()` — Rule 7's own function (not shared) —
drives the scalp-rearm-after-both-SL'd case described in Rule 7 above.

---

## Per-symbol numbers (everything else is identical logic)

| Symbol | TP (both modes) | SL basis | Notes |
|---|---|---|---|
| USA500 | 5.5 pts | 0.75×ATR / max(0.8×ATR, 3.0) | original tuning |
| **USA100** | **30 pts** | **flat 30 pts (FIXED_SL_POINTS, bypasses ATR)** | TP/SL both fixed 2026-08-12 (was 20pts TP / ATR-based SL), requested directly, values only |
| **USA30** | **50 pts** | **flat 50 pts (FIXED_SL_POINTS, bypasses ATR)** | its real min-stop-distance tracks spread, not the broker's stated value — ATR-sized SL kept racing it |
| **XAUUSD** | 5.5 pts | WITH_TREND: 0.75×ATR / max(0.8×ATR, 3.0) unchanged. **Scalp + reversal: flat 2.00 pts (SCALP_FIXED_SL_POINTS, bypasses ATR)** | scalp/reversal SL fixed 2026-08-13, requested directly — WITH_TREND and all TP untouched |
| **GBPUSD** | **0.00100** | **flat 0.00100 (FIXED_SL_POINTS, bypasses ATR), ALL modes — WITH_TREND, scalp, reversal** | Final fix 2026-08-13: `ROUND_STEP` (the pip-grid rounding that was making SL/TP drift up to ~2x on every trade) REMOVED entirely — SL/TP now round on the fine broker tick grid only, landing within ~1 tick of exactly 0.00100 every time, no more variation |
| **USDJPY** | **0.100** | **flat 0.100 (FIXED_SL_POINTS, bypasses ATR), ALL modes — WITH_TREND, scalp, reversal** | Final fix 2026-08-13: the brief scalp-only 0.025 cut and `ROUND_STEP` (pip-grid rounding, same drift issue as GBPUSD) both REMOVED — one uniform flat 0.100 for every mode, landing within ~1 tick every time |

`ADX_MIN`, `ADX_STRONG_TREND`, and all RSI bands are identical (15, 25,
40–80/90/10 etc.) across all 6 — these are ratios, not price-scale
dependent, so there was never a reason to vary them.

---

## Full config audit (2026-08-11) — requested directly after an unverified claim

A full audit was run after a prior "yes, all rules apply uniformly"
answer turned out to have a real gap (the scalp re-arm issue above) that
was never actually checked. Method: grepped `strategy.py`/`bot_runner.py`
for any `symbol ==` / `SYMBOL ==` branch — zero matches, confirming the
decision code has no per-symbol special-casing at all; every rule listed
in this document runs identically for all 6 symbols by construction, only
the `config.py` numbers differ. Then every symbol's config numbers were
checked against live ATR:

- **GBPUSD's TP was genuinely broken**: `0.005` (~10.4x mean ATR, no
  comment justifying it) vs. every other floating symbol sitting in the
  0.55x-1.15x range or carrying an explicit override/request comment.
  Matched the observed result exactly — 0 wins / 3 losses, TP essentially
  unreachable. Fixed to `0.00040` (re-derived from current ATR, nudged up
  for headroom over the broker's min-stop-distance).
- USA500/USA100/USDJPY's ratios also look "off" the 0.68x formula, but
  each has an existing, commented reason (USA500: backtest-derived fixed
  TP, ATR has since drifted; USA100: already flagged "still far, re-check"
  in its own comment; USDJPY: explicitly requested widening) — not hidden
  bugs, just documented deviations.

The dashboard's bottom **Rule coverage** table (`/`, `app.py._build_rule_matrix()`)
is the standing, checkable version of this — one row per rule, one column
per symbol, computed fresh from live `config.py` on every page load so it
can never assert something false.

---

## Other active mechanisms not directly asked about, but live right now

- **FLIP** (`evaluate_flip`): if the big trend is UP and a SELL is
  currently open (usually a scalp), closes it and opens a full-size
  WITH_TREND BUY if DI+RSI+ADX all confirm strongly. This is a *different*
  full-confirmation path from the scalp-SL reversal — it requires the same
  bar/DI/candle checks a fresh WITH_TREND entry needs.
- **Order placement robustness** (all symbols, but matters most on
  wide-spread/fast-moving ones like USA30): SL/TP are clamped against the
  broker's real minimum stop distance (max of its stated `trade_stops_level`
  and the current spread — the stated value is sometimes just wrong), with
  a safety margin, and a retry with a wider margin + fresh price if the
  first attempt still gets "Invalid stops". SL/TP are also rounded to the
  symbol's real tradable price grid (`trade_tick_size`, from
  `mt5.symbol_info()`), not just its display `digits` (`bot_runner._round_price`,
  fixed 2026-08-11) — USA30 confirmed directly: `trade_tick_size` is 0.1 but
  `digits` implies 0.01 is fine. SL/TP are derived from `live_snap.close`,
  a live bid/ask MID (for dashboard indicators to move live) — averaging
  two 0.1-grid prices with an odd tick-count spread lands the mid exactly
  half a tick off-grid, and `round(x, 2)` alone never fixes that, so the
  broker kept rejecting a plainly-far-enough SL/TP as "Invalid stops"
  regardless of distance or retry margin. Every other configured symbol
  currently has `trade_tick_size == point`, so this was silent everywhere
  except USA30.
- **Pip-level SL/TP rounding for USDJPY and GBPUSD** (`cfg.ROUND_STEP`,
  added 2026-08-12, requested directly): a deliberate pip-level display
  preference, not a broker-grid validity fix like the one above — both
  symbols' `trade_tick_size` already matches their `digits` exactly
  (confirmed directly via `mt5.symbol_info()`: USDJPY 0.001, GBPUSD
  0.00001), so there was no broker rejection risk to begin with. USDJPY's
  SL/TP now round to the nearest 0.100 (100 points = 10 pips), GBPUSD's to
  0.00100 (also 100 points = 10 pips). Critically, `_round_price()` rounds
  AWAY from the reference price (entry for a fresh order, current price
  for a trail) — never to the nearest grid point — because some of these
  symbols' computed distances are smaller than the rounding step itself
  (USDJPY's scalp SL floor is 0.046, well under the 0.100 step); rounding
  to nearest could have shrunk that down to as little as ~0.012 in the
  worst case, a near-invalid stop. Rounding away only ever widens the
  distance the strategy computed, never shrinks it below the configured
  floor. Every other symbol (`cfg.ROUND_STEP is None`) is completely
  unaffected — verified with a standalone test that USA500's rounding
  behavior is byte-for-byte identical to before this change.
  **Follow-up, 2026-08-13**: a live USDJPY WITH_TREND position showed SL
  close (0.122) but TP blown out to 0.578 — TP's flat 0.5 was already ~5x
  the ATR-based SL even before this rounding added more on top. User asked
  for TP at SL's level, then chose to remove ATR entirely for BOTH
  USDJPY and GBPUSD SL (see per-symbol table above: both now
  `FIXED_SL_POINTS`, TP shrunk to match). Rounding-away is still not
  perfectly symmetric — verified directly, USDJPY's flat 0.100/0.100
  pre-rounding worked out to SL 0.122 / TP 0.178 post-rounding in one
  example, ~1.5x apart instead of the old ~5x — since away-from-entry
  rounding can add up to one more step unevenly to each side depending on
  where the entry price falls on the grid. Flagged to the user as a
  residual imperfection, not claimed as an exact 1:1 fix.
  **Follow-up, 2026-08-13**: for GBPUSD specifically, WITH_TREND's SL
  (flat 0.00100) is the SAME size as `ROUND_STEP` itself — the
  away-rounding could add up to another full 0.00100, landing up to
  ~0.00200 from entry (nearly double). User: "GBPUSD ka stoploss bohat
  door ja raha hai... .00100 tak le kar ao WITH_TREND ke liye." Added
  `cfg.TREND_SL_FINE_ROUNDING` (GBPUSD only, `True`) — `_round_price()`
  gained a `coarse: bool` parameter; when `False`, skips `ROUND_STEP`
  entirely and falls through to the fine broker-tick rounding, keeping
  the real distance close to the configured flat value. Threaded through
  `_build_order_request()`/`send_order()` (now takes/passes `mode`) and
  `_modify_sltp()`/`trail_all_positions()` (mode looked up from
  `position_modes`) — applied ONLY to WITH_TREND's SL leg; TP, and
  scalp's SL, still use the normal coarse away-rounding, unchanged.
  USDJPY (same `ROUND_STEP`/`FIXED_SL_POINTS` shape) has the identical
  structural exposure but was NOT touched — not asked for, flagged
  separately to the user as a similar-pattern risk. Verified with a
  standalone test: GBPUSD WITH_TREND SL now lands within a couple pips of
  the flat 0.00100 target instead of up to 0.00190+; GBPUSD's scalp SL
  and TP, and USDJPY entirely, are byte-for-byte unchanged.
  **SUPERSEDED, 2026-08-13, same day — FINAL FIX, `ROUND_STEP` REMOVED
  ENTIRELY for both symbols.** All three follow-ups above turned out to
  be partial patches around the same root cause. User: "meine tumhein
  kaha tha... GBPUSD aur USDJPY dono par WITH_TREND aur scalp aur
  reversal sab ke liye SL 100 TP 100 lagana... yeh abhi tak fix nahi hain
  balke change hoti rehti hain... mujhe dynamic nahi chahiye, is ko final
  fix karo." `ROUND_STEP` deleted from both `SymbolConfig`s (was 0.100 /
  0.00100) — with it `None`, `_round_price()` unconditionally falls
  through to fine broker-tick rounding (0.001 / 0.00001) for EVERY SL/TP
  on these symbols, WITH_TREND and scalp/reversal alike, landing within
  one tick of the exact flat target on every single trade — no more
  away-from-entry drift, no more mode-specific carve-out needed. This
  also made `cfg.TREND_SL_FINE_ROUNDING` (the GBPUSD-WITH_TREND-only fix
  immediately above) redundant — removed too, since fine rounding now
  applies everywhere on this symbol regardless of `coarse`. USDJPY's
  brief scalp-only 0.025 SL cut (see per-symbol table) was ALSO
  superseded in the same instruction — reverted to the uniform flat 0.100
  used by every mode; `scalp_fixed_sl_points` removed from USDJPY's
  config, scalp now falls back to `fixed_sl_points` like WITH_TREND does.
  The `ROUND_STEP`/`TREND_SL_FINE_ROUNDING` mechanisms themselves stay in
  `bot_runner.py`/`config.py` (harmless, unused, available if a future
  symbol genuinely wants pip-grid display rounding) — only these two
  symbols' config values changed. Verified with a standalone test across
  both symbols, both modes (WITH_TREND and COUNTER_SCALP, which covers
  the reversal too), and multiple different entry prices: SL and TP
  distance is now consistently the exact configured flat value (within
  one broker tick), never drifting, confirming the "keeps changing"
  complaint is resolved.
- **Trail SL "No changes" spam fixed, 2026-08-13** — found directly on
  GBPUSD: `Trail SL FAILED ticket=... -> 1.34853: 10025 No changes` on
  every tick. `trail_all_positions()` decides whether to trail based on
  the RAW, pre-rounding target SL (moves every tick as price moves) vs.
  the position's real current SL — but once a symbol's rounding grid
  (`ROUND_STEP` or the broker's own tick size) is coarser than that
  tick-to-tick movement, many different raw targets round to the SAME
  price, which can already be exactly what's on the position. Sending
  that again is correctly rejected by the broker as retcode 10025 ("No
  changes") — harmless, but was logged as "FAILED" every single tick,
  pure noise. Not specific to `ROUND_STEP` symbols, so fixed generally in
  `_modify_sltp()`: computes the rounded SL/TP first, compares against the
  position's actual current SL (now passed in), and skips the request
  entirely (no log) when they already match; also added a
  `TRADE_RETCODE_NO_CHANGES` branch as a second safety net for any case
  that reaches `order_send` anyway. Verified with a standalone test:
  matching case sends nothing, a genuinely different target still sends
  normally.
- **Trade history persistence** — every closed trade is written to a
  per-account SQLite table immediately (survives restarts), commission/swap
  gets reconciled in from MT5's real deal history once available, and
  duplicate-ticket inserts are now impossible (UNIQUE constraint).
- **Trade history timestamps now consistently LOCAL machine time,
  2026-08-13** — user spotted a trade history row showing "Closed" BEFORE
  "Opened" and asked for both on local time for easy observation. Root
  cause: `opened_at` was captured from MT5's own `position.time`/
  `deal.time` (broker server clock) in three places, while `closed_at`
  used `datetime.now()` (local) — and the broker server clock on this
  account isn't UTC-synced, running ~3h ahead of local (confirmed
  directly: `mt5.symbol_info_tick().time` vs. `time.time()` at the same
  instant). Added `SymbolBot._broker_time_offset()` (computed fresh each
  call — broker/DST could drift, not hardcoded) and
  `_broker_ts_to_local_str()`, used at all three `opened_at`/broker-deal
  `closed_at` call sites instead of a bare `datetime.fromtimestamp()`.
  Verified directly: converting a live broker tick timestamp through the
  new helper matches `datetime.now()` to the second.
- **Per-account separation** — demo and live history are in physically
  separate tables; switching accounts can never mix them.
- **Account reconciliation panel, added 2026-08-13** (`app._account_reconciliation`):
  user noticed Balance(97586.44) vs. initial deposit(100000) vs. the
  dashboard's own Net P/L(-697.05) didn't add up — a ~1717 gap with
  nothing on the dashboard explaining it. Walked the account's FULL
  history via `mt5.history_deals_get()` (all-time, not scoped to our own
  DB): found this account has 7 MORE deposit/withdrawal operations after
  the initial one (net +5736.66 — plain demo account top-ups/withdrawals,
  not trading activity at all), and the REAL all-time trading P/L across
  all 607 trade deals is -8150.22, while the dashboard's tracked Net P/L
  only covers trades since the last time this session cleared the local
  DB (2026-08-12 15:22 sync_cutoff) — so -7453.17 of real, genuine
  trading loss exists in the MT5 account's own history but was invisible
  on the dashboard, having been deliberately deleted from the local copy
  by an earlier "clear the DB" request. Verified: `net_deposits (5736.66)
  + alltime_trade_pl (-8150.22) = 97586.44` reconciles EXACTLY to the live
  balance — nothing is actually missing, it just wasn't being shown.
  Added three new metrics to the Account panel: **Net deposits**,
  **All-time P/L**, **Untracked P/L** (= all-time P/L minus the
  dashboard's own tracked Net P/L). Cached 30s server-side
  (`_reconcile_cache`) since it walks the full account deal history —
  cheap today (~600 deals) but no reason to redo it on every 2s dashboard
  poll. **Follow-up, same day**: the first layout put these 3 in their
  own separate `cols-3` grid below the main 9, plus an explanatory
  paragraph underneath — user reported the sizing looked broken (long
  labels like "NET DEPOSITS/WITHDRAWALS" wrapping badly in the narrow
  `span-4` panel) and asked to fix it and remove the paragraph. Fixed by
  merging all 12 metrics into the SAME `metrics cols-3` grid (now 4 rows
  of 3 instead of 3+1) so every tile sizes identically, and shortening
  the 3 new labels ("Net deposits", "All-time P/L", "Untracked P/L") to
  fit the column width; removed the paragraph entirely.
