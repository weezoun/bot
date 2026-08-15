# Version 2 — saved 2026-08-11

**FROZEN 2026-08-13 — this version's history stops here.** Every change
made from this point on is logged in the NEXT version's own `NOTES.md`
instead of being appended here (see `../v2.1/NOTES.md`, and
`../INDEX.md` for the full chain of every version). This file still
covers everything up to and including the dashboard-sizing fix
(2026-08-13, the entry just above "Full strategy reference" near the end
of this file) — read `v2.1/NOTES.md` for what changed after that,
starting with Rule 5's ADX/RSI/ATR restoration.

Snapshot of the bot at the point the two "final summary" corrections were
applied. `code/` is a frozen copy of every source file as it stood at save
time; `stats/` is a frozen copy of the trade history DB at the same moment
(the account's results BEFORE this version's fixes had a chance to trade —
i.e. this is Version 2's starting baseline, not its own results yet).

The live bot in `c:\bot` (not this folder) keeps running and keeps writing
to the real `trade_history.db` — this snapshot is a fixed reference point
to compare against later, not something that stays in sync automatically.

## What changed vs. the previous (unversioned) state

1. **Candle-color checks now use the LAST FULLY CLOSED candle everywhere,
   not the live/forming one.** Two parts, found in sequence:
   (a) `_momentum_recovered()` (the post-SL/TP re-entry gate) originally
   checked the in-progress candle's colour on every tick, so a transient
   mid-candle green/red state (which could still reverse before that
   candle closed) was enough to unlock re-entry — now waits for an entire
   candle to close after the SL/TP candle, and checks THAT closed candle's
   colour, a genuine extra-candle wait. (b) Found right after, directly
   from a live trade (XAUUSD ticket 1284485196): a completely FRESH
   WITH_TREND entry (no gate involved at all) had the SAME live-candle bug
   in its own base check — it fired 3 seconds into a brand-new candle off
   that candle's transient live-green tick, then that same candle finished
   red and the trade was stopped out. `evaluate_entry()`'s base
   `trend_ok` candle check now also uses `closed_snap`. Both paths are
   consistent now. See `strategy._momentum_recovered` / `evaluate_entry`.

2. **SL/TP now rounded to the broker's real tradable price grid
   (`trade_tick_size`), not just `digits`.** Found right after this
   version's first two fixes, while investigating a persistent USA30
   "Invalid stops" that survived the retry-with-wider-margin logic. Root
   cause: USA30's real tick grid is 0.1, but `digits=2` implies 0.01 is
   fine — SL/TP are derived from a live bid/ask MID price, which lands
   exactly half a tick off-grid whenever the spread has an odd number of
   0.1-ticks, and no amount of distance-margin or `round(x, 2)` fixes an
   off-grid price. `bot_runner._round_price()` now snaps every SL/TP to
   `trade_tick_size` before sending. Confirmed via `mt5.order_check()`
   with the exact off-grid values seen live: rejected before the fix,
   `retcode=0 Done` after. Every other configured symbol currently has
   `trade_tick_size == point`, so this was silent everywhere except USA30.

3. **Scalp re-arm gap, all 3 instances (found via full audit after a live
   report): `_reverse_scalp()` could leave `scalp_armed` stuck False
   indefinitely.** Live report (USA100, 2026-08-11): -DI stayed dominant
   with no regime flip, yet the bot wouldn't scalp SELL at all despite
   conditions being met — `scalp_armed` had no active gate watching to
   re-arm it. First instance found and fixed (reversal cap already used
   this regime, branch just logged and returned with no gate) — then,
   because the earlier "final summary" had claimed this whole mechanism
   was uniformly wired everywhere and it demonstrably wasn't, did a full
   audit of every `_reverse_scalp()` exit rather than stopping at the one
   report. Found two more identical gaps in the same function:
   insufficient margin (`should_take_trade()` false), and `send_order()`
   itself failing — both also returned bare with no gate. The
   send_order-failure case had a second, subtler problem: state
   (`scalp_reversal_used`, the gates, `scalp_armed`) was mutated BEFORE
   calling `send_order()`, so a failed order still burned the
   one-per-regime reversal cap and left `scalp_reversal_di` holding a
   "pending reversal" that would never close — stale data a later,
   unrelated WITH_TREND close could have matched against. Fixed all
   three: every non-success exit now falls through to the same rolling-DI
   + last-closed-candle-color gate a scalp TP uses
   (`_rearm_scalp_if_continuing`, generalized with a `trigger` label), and
   state is only mutated AFTER `send_order()` confirms a real ticket —
   the same confirm-before-mutate pattern `bot_tick()` already used
   correctly for fresh scalp entries, which `_reverse_scalp()` alone had
   never matched.

4. **Trailing SL now applies to every open position, not just WITH_TREND.**
   Scalps (COUNTER_SCALP) and the scalp-SL immediate-reversal trade used
   to be skipped entirely (`if mode != 'WITH_TREND': continue`) and could
   run into real profit with zero protection. `bot_runner.trail_all_positions()`
   (renamed from `trail_with_trend_positions`) now trails every position,
   sized off THAT position's own actual TP distance read from MT5
   (`abs(p.tp - p.price_open)`) rather than a mode-keyed config lookup —
   correct even for the reversal trade, which classify_side() usually
   labels 'WITH_TREND' but which is always sized scalp-tight in practice.

5. **Dashboard: Trade History table now has a per-symbol filter dropdown**
   (`templates/dashboard.html`) — was merged-only before, requiring manual
   scrolling to find one symbol's trades. Backend (`/api/trades?symbol=`)
   already supported this; only the UI control was missing.

6. **GBPUSD's TP was a real, live bug — ~10.4x its own mean ATR, no
   justification anywhere.** Found via a full config.py audit (requested
   directly, 2026-08-11, after a claim that "all rules are applied
   uniformly" turned out to have an unverified gap). Every other floating
   symbol's TP tracks ~0.6-1.2x its own mean ATR (or is an explicit,
   commented override — USA30's fixed points, USDJPY's requested
   widening); GBPUSD alone had no such note and sat at 10.4x — a ~50-pip
   target on a pair averaging ~5-pip M15 ATR, essentially unreachable.
   Matches the observed result exactly: 0 wins / 3 losses. Re-derived from
   current live ATR (`~0.68x mean ATR`), then nudged up slightly for
   headroom above the broker's real min-stop-distance. `0.005` -> `0.00040`.

7. **Dashboard: new "Rule coverage" table at the bottom of the page**
   (`app.py._build_rule_matrix()` + `templates/dashboard.html`) — every
   rule in the strategy, one row each, with a column per symbol showing
   whether it's actually applied. Computed fresh from live `config.py` on
   every page load (never hand-typed), so it can't go stale or assert
   something false — requested directly as a standing, checkable
   reference after the GBPUSD gap above.

8. **New standing process, 2026-08-12: user dictates rules one at a time,
   numbered ("Rule 1", "Rule 2", ...), applied identically to all 6
   symbols, tagged into trade reasons when they trigger an entry, and
   LOCKED — not modified again without explicit permission once
   implemented.** Recorded as a persistent memory
   (`bot-rules-numbering-process.md`) so this survives context
   compaction/future sessions. Dashboard gained a new "Confirmed rules"
   section (`app.py._build_numbered_rules()`) above the older "Detailed
   rule flow" cards, which it supersedes incrementally.
   **Rule 1 — no trade opens on the candle the bot started/restarted on**:
   waits for a genuinely new candle (bar_time change, not a fixed delay)
   before allowing any order-placing action. `BotState.startup_bar_time`/
   `startup_gate_cleared`, reset in `SymbolBot.start()`, enforced in
   `bot_tick()`.

   **Follow-up fix, same day:** the `/` dashboard route had no `Cache-Control`
   header at all (only `/api/*` did) — a normal browser refresh could keep
   serving a stale cached copy of the page even after app.py restarted
   with new template content (found directly: user restarted, Rule 1
   still didn't show up until a hard-refresh). Added the same `_no_cache()`
   wrapper to the `/` route so this can't recur for future rules.

9a. **Dashboard restructured, 2026-08-12: "Confirmed rules" and "Detailed
   rule flow" merged into ONE section** (`app.py._build_rules()`), per the
   user's explicit instruction — numbered rules ("Rule 1", "Rule 2", ...)
   and not-yet-confirmed legacy cards now live in the same list, in the
   same place, so future rules just update this one section going
   forward instead of two separate ones.

9b. **Rule 2 — WITH_TREND entry**, added 2026-08-12: merges the user's new
   wording (last CLOSED candle same direction + currently FORMING candle
   must NOT be forming the opposite direction — this second check is NEW,
   not previously implemented) with the pre-existing detailed WITH_TREND
   entry checks (trend gate, ADX, DI alignment, RSI band, momentum_gate,
   flat/one-per-candle/margin gates) into a single rule, replacing the old
   unnumbered "WITH_TREND entry" card. Implemented in `strategy.py`
   (`evaluate_entry()`'s `trend_ok`, both branches) and verified with a
   standalone test (forming-candle-opposite-direction case correctly
   blocks, flat/same-direction forming candle correctly allows). Entry
   reason text now prefixed `"Rule 2: ..."` so it's tagged in the trade's
   `open_reason`, per the standing tagging instruction.

   **Correction, same day:** an initial draft of Rule 2 added an unrequested
   note about FLIP being a separate mechanism — user corrected this
   directly ("mujhse aage mat bhaago, jitni baat kar raha hun us tak raho")
   and it was removed. Standing lesson: stick strictly to what's asked in
   each rule, don't fold in adjacent-but-unasked-for context.

9c. **Standing process memory updated** (`bot-rules-numbering-process.md`)
   to record Rule 2 and the single-section dashboard structure, so this
   survives context compaction/future sessions.

9e. **Isolation architecture, 2026-08-12 — major correction.** The user
   pointed out directly that Rule 3's first implementation (a shared
   `momentum_gate` dict with a `'reason': 'TP'/'SL'` tag, branched inside
   one shared `_momentum_recovered()` function) violated an explicit
   standing requirement: every rule must be a fully isolated
   function/state, so editing one can never affect another. Refactored
   immediately: Rule 3 now owns `BotState.rule3_gate` +
   `bot_runner._check_rule3_gate()` (fully self-contained DI/candle logic);
   Rule 4 (below) owns `rule4_gate` + `_check_rule4_gate()`, entirely
   separate. Rule 2 (`evaluate_entry`) only does a trivial presence/side
   check against each gate (`gate and gate['side']==side`) — it never
   computes or duplicates their clearing conditions. The old shared
   `momentum_gate` is retired for WITH_TREND; `_momentum_recovered()`
   still exists but is now used only by `evaluate_flip()` (always passed
   `None`, a no-op) and scalp's `_check_scalp_continuation()` — neither
   part of any numbered rule.

9f. **Rule 3 — WITH_TREND TP hit**, added 2026-08-12 (re-verified after the
   isolation refactor): existing gate mechanism confirmed correct, plus
   one new check — forming candle must not be opposite direction from the
   previous candle. Own isolated gate/function (see 9e). Verified with a
   standalone test covering rule3_gate, rule4_gate, and no-gate cases.

9g. **Rule 4 — WITH_TREND SL hit**, added 2026-08-12: trade recorded to
   history as a loss-labeled close_reason (see note below). Same-candle
   block on ALL new entries (WITH_TREND + scalp, either side) via the
   existing generic `last_bar_time` mechanism. From the next candle,
   both systems live again on their own conditions; additionally, for the
   SL'd side specifically: rolling DI rising AND forming candle
   DEFINITELY the required color (green/red — an absolute requirement,
   not "not opposite" like Rule 3). Own isolated gate/function
   (`rule4_gate` / `_check_rule4_gate`). Verified with a standalone test —
   including confirming a flat forming candle does NOT clear the gate
   (only a definite matching color does), and that Rule 4's own clearing
   check never touches `rule3_gate`.

9h. **Rule 5 — Scalp (COUNTER_SCALP) entry**, added 2026-08-12: existing
   scalp-entry conditions (trend, ADX, DI-opposes-trend, RSI band, ATR
   strong) confirmed, plus two new checks — rolling DI (this side's DI
   above the preceding candle) AND the currently forming candle must
   definitely be the same direction as the trade (absolute requirement,
   checked live, not "not opposite"). User also had two clarifying edits
   to the card's WORDING (not new checks): removed the scalp_armed
   re-arm-mechanism detail (irrelevant to describing entry itself — that
   belongs to scalp's own TP/SL rules, not dictated yet) and removed the
   "same general gates as WITH_TREND" cross-reference (per the isolation
   principle — describe only what Rule 5 itself does). Implemented
   directly in `evaluate_entry()`'s `scalp_ok` (both branches) — no new
   isolated gate needed since this is a direct per-tick condition, not a
   stateful post-close gate like Rule 3/4. Verified with a standalone
   test (DI-not-rising blocks; wrong-direction forming candle blocks;
   both-satisfied fires with `"Rule 5:"` tagged into the reason).

9i. **Rule 6 — Scalp TP hit**, added 2026-08-12: existing behavior
   (win-record, `scalp_continuation_gate` instead of immediate re-arm,
   scalp_armed lifting only the "already scalped" cap not a full bypass
   of Rule 5) confirmed correct as-is. Clearing condition redesigned at
   the user's direction to match Rule 4's STYLE (rolling DI + forming
   candle DEFINITELY the required color, checked live) — own fully
   independent implementation (`_check_rule6_gate`), zero shared code
   with Rule 4.

   **Conflict found and resolved** (user explicitly invited flagging
   conflicts): the pre-existing `scalp_continuation_gate` was actually
   shared between Rule 6 (scalp TP) AND a separate, not-yet-formalized
   case (scalp SL whose reversal attempt didn't open — cap/margin/order-
   fail fallbacks in `_reverse_scalp`). Redesigning it for Rule 6 would
   have silently changed that other, un-dictated case too. Split into two
   fully independent mechanisms: Rule 6 keeps `scalp_continuation_gate` /
   `_check_rule6_gate`; the other case got its own new field
   `scalp_no_reversal_gate` / `_check_scalp_no_reversal_gate`, preserving
   its EXACT prior behavior unchanged. Verified with a standalone test
   covering both gates independently plus direct isolation confirmation.

   **Also fixed in passing**: `_check_rule4_gate` had a stray duplicate
   log line left over from development, unrelated to Rule 4's actual
   logic — removed (this was previously misdiagnosed as "live process
   log bleed" in an earlier test run; now confirmed to have been a real,
   if harmless, bug in the log statement only).

9j. **Textual cross-references cleaned up, same day.** User asked directly:
   "did you not completely isolate Rule 6?" — pointed out that although
   Rule 6's CODE was functionally isolated (no shared state/function
   calls, verified by test), several code comments/docstrings and one
   dashboard card still NAMED other rules by number to explain
   themselves (e.g. `_check_rule6_gate`'s docstring said "same style as
   WITH_TREND's post-SL gate", `_rearm_scalp_after_sl_no_reversal` said
   "NOT part of Rule 6", the "Scalp — SL hit" card said "separate from
   Rule 6's"). Asked whether to remove these too — chose yes, everywhere.
   Swept `bot_runner.py`, `strategy.py`, and `app.py` for every "Rule N"
   mention; kept only genuine SELF-references (a rule's own code/log
   naming its own number — e.g. `"Rule 6: Scalp TP..."` in Rule 6's own
   log line, which is the standing trade-reason-tagging requirement, not
   a cross-reference) and removed every mention of a DIFFERENT rule's
   number from comments, docstrings, and dashboard card text (including
   the `_skip_trend_*_reason` messages, which used to say "Rule 3 gate
   active"/"Rule 4 gate active" — now generic "blocked by the post-TP/SL
   re-entry gate"). Re-ran the full regression suite (Rules 1-6) after
   the cleanup — all pass, confirming this was purely textual, zero
   functional change.

9k. **Correction, same day: the textual cleanup (9j) overcorrected —
   user pushed back.** "Rule 3 gate active"/"Rule 4 gate active" in the
   dashboard's "why blocked" text is USEFUL diagnostic info (tells the
   user which rule is currently applying) and should never have been
   removed — restored immediately. The real isolation boundary the user
   meant all along is **working code**: rules must not call each other's
   functions or share state — that's it. Diagnostic/log text naming
   another rule is fine and wanted. Also fixed a real gap surfaced in the
   same message: Rule 6 (Scalp TP hit) never blocked WITH_TREND on the
   same candle as the TP — only scalp's own re-arm was gated, so
   WITH_TREND could fire immediately. Added the same "block ALL new
   entries this candle" step Rule 4 uses (via the generic `last_bar_time`
   mechanism) to `_rearm_scalp_after_tp`; WITH_TREND is then free again
   from the next candle with no extra check. Verified with a standalone
   test. **User also asked me to stop bringing up a different rule's
   specifics when discussing the current one** (I'd over-explained the
   separate, not-yet-formalized "scalp SL, reversal didn't open"
   mechanism while fixing Rule 6) — noted as a standing communication
   preference, not a code change.

9l. **Rule 7 — Scalp SL hit**, added 2026-08-12, with a full pre-implementation
   analysis (user explicitly asked to check for conflicts before writing
   code). Two new outcome handlers: reversal TP → scalp explicitly
   re-armed (`_on_reversal_tp`, a genuine gap — nothing else re-armed it
   on this path); reversal SL → existing `scalp_rearm_gate` benchmark
   mechanism (unchanged, already matched what the user described).
   Proposed second WITH_TREND-side DI benchmark rejected as redundant
   with Rule 4 (which already handles any WITH_TREND SL, including the
   reversal) — user confirmed, no new gate added. "One reversal per DI
   regime" cap explicitly discussed and kept (`scalp_reversal_used`
   unchanged) to preserve the reversal's risk-capped design intent.
   Extracted the reversal-outcome logic that used to live INLINE inside
   Rule 3's/Rule 4's own code into two new standalone functions, called
   alongside (never from inside) Rule 3/Rule 4's own gate-setting —
   verified their behavior is byte-for-byte unchanged with a standalone
   isolation test.

9m. **Rule 8 — Reverse entry**, added 2026-08-12: the user asked whether
   this pre-existing card was still needed given Rule 7 now exists —
   answered before acting: yes, not redundant (Rule 7 = reversal's
   outcome handling; Rule 8 = the reversal's own entry mechanics, same
   split as Rule 5 vs Rule 6/7). Content verified unchanged/still
   accurate — just formalized as a numbered rule + entry reason text
   prefixed `"Rule 8: ..."`.

9n. **"Rolling DI — every place it's actually used" card removed**,
   2026-08-12: user asked directly whether it was still needed now that
   Rules 3/4/5/6/7 each carry their own rolling-DI description —
   answered before acting: no, redundant, its content is now duplicated
   across those individual cards. The two facts unique to it (FLIP
   currently inert re: rolling DI; `scalp_no_reversal_gate` still uses
   the old shared mechanism) are minor and already in code comments.
   Removed from the dashboard; kept as historical note in
   `docs/current_strategy.md`. Dashboard now shows exactly 8 cards, all
   numbered (Rules 1-8) — no unformalized/leftover cards remain.

9o. **Real regression found and fixed, 2026-08-12: FLIP silently stopped
   respecting rule3_gate/rule4_gate.** User asked directly what FLIP does
   and why it wasn't applying the gate it was supposed to. Root cause:
   when Rule 3/Rule 4 were split out of the old shared `momentum_gate`
   (same day), `evaluate_flip()` was left checking nothing — `decide()`
   hardcoded `momentum_gate=None`, reintroducing the EXACT same-candle
   re-entry bug originally fixed 2026-08-11 (a WITH_TREND close could
   immediately reopen the same side via FLIP). Caused by over-applying an
   earlier, narrower correction ("don't discuss FLIP while defining
   Rule 2") to mean "FLIP is exempt from these gates" — it never meant
   that. Fixed: `evaluate_flip()` now takes `rule3_gate`/`rule4_gate`
   directly (same presence-check pattern as Rule 2); `decide()` passes
   them through instead of hardcoding None. FLIP's own DI/RSI
   confirmation criteria unchanged; still no Rule 2 candle-color checks.
   Verified with a standalone regression test. FLIP itself stays outside
   the numbered-rule list.

9p. **Clarified: `_check_scalp_no_reversal_gate` belongs to Rule 8's code**
   (lives inside `_reverse_scalp`) but its specific mechanics were never
   individually dictated by the user — Rule 8's approved card describes
   the three preconditions but not this fallback's own behavior. Left
   as-is, unformalized, pending the user's decision on whether to fold it
   into Rule 8 explicitly.

9q. **Correction, same day: "Rule 8 — Reverse entry" merged back into
   Rule 7.** User asked why it was a separate rule at all when Rule 7
   already exists to handle the reversal, given the reversal only ever
   fires from one place. Re-examined the earlier reasoning (parallel to
   Rule 5 vs Rule 6/7) and agreed it didn't hold: unlike Rule 5 (scalp
   entry), which independently re-evaluates its own conditions every
   tick and can fire many separate times, the reversal has NO
   independent trigger of its own — it only ever fires as a direct,
   mechanical consequence of Rule 7's own trigger (a scalp SL), with
   zero conditions of its own. Merged the "Reverse entry" content
   (directional basis, scalp-tight sizing, three preconditions,
   trailing) directly into Rule 7's card as one comprehensive rule. No
   code changes — the underlying functions were already isolated
   internally and stay that way — purely a dashboard
   numbering/presentation correction. Entry reason text re-tagged
   `"Rule 7: ..."` (was briefly `"Rule 8: ..."`). Dashboard now shows
   exactly 7 cards, all numbered (Rules 1-7).

9r. **Rule 5 correction: ADX_MIN gate removed from scalp.** User found it
   was blocking scalp entries outright with no benefit ("DI ki
   calculation kaafi hai"). Previously ADX was a single blanket check at
   the top of `evaluate_entry()` gating both scalp AND WITH_TREND
   identically. Removed that top-level check; `snap.adx >= cfg.ADX_MIN`
   moved into `trend_ok` (Rule 2) directly — Rule 2 unchanged, Rule 5 no
   longer checks ADX at all. `_skip_trend_*_reason` updated to surface
   the ADX-too-low reason for WITH_TREND specifically now that the old
   blanket message is gone. Verified with a standalone test (scalp fires
   with ADX far below `ADX_MIN`; WITH_TREND with the same low ADX still
   correctly blocked). Dashboard's old "Rule coverage" table's ADX row
   also relabeled for accuracy.

   **User feedback on the refactor process itself, addressed directly
   (not a rule)**: worried that removing shared `momentum_gate` might have
   silently dropped functionality. Confirmed nothing was lost — TP/SL's
   old combined logic is now fully present, just split into Rule 3's and
   Rule 4's own isolated functions. Asked whether the trivial one-line
   rolling-DI arithmetic (duplicated in both) should be factored into a
   shared stateless utility (like `_bullish_candle`) — user chose to
   leave it duplicated, matching the isolation principle literally.

   **Question raised alongside Rule 4, answered but not acted on**: why
   does a trailed-into-profit SL still show `close_reason = "SL"`?
   Clarified: that label is a proximity indicator (which level price was
   nearer to), not a win/loss label — actual stats already correctly use
   real `profit`. No code changed; flagged for the user to decide if the
   label itself should be split (e.g. "SL (profit)" vs "SL (loss)").

9s. **Demo trade history DB cleared, 2026-08-12 (twice).** User stopped the
   bot and asked for a fresh start with zero pre-existing trade history
   ahead of running the new rule set. First clear: 155 rows deleted from
   `trade_history_49825877`, `sync_cutoff` set to clear time for all 6
   symbols so the periodic broker-history re-sync wouldn't just re-import
   everything. User then noticed a USA100 position on the dashboard right
   after restart and asked "bot restart karte hi yeh trade kaise start ho
   gaye, is ko to wait karna tha next candle ka" — investigated via
   `mt5.positions_get()` `.time` vs. the bot process's actual start time
   (accounting for the ~3h server/local offset already established
   earlier in this session) and confirmed it was NOT a new/premature
   entry: the position had opened ~3-4 minutes before the new process
   even started (leftover from the previous run, before the user stopped
   it), and the dashboard's own ACTION read `MANAGE` (an existing
   position being managed), not `BUY` — no bug found. User then closed it
   manually, confirmed no open positions remained, and asked for a second
   clear: 1 leftover row deleted (that same trade's close having synced
   in after the first clear), `sync_cutoff` reset again for all 6
   symbols. DB is now at 0 rows, 0 open positions, ready for a clean
   restart. No code changed by this entry.

9t. **Rule 5 correction: RSI and ATR removed from the scalp decision.**
   User saw the dashboard blocking a live USA500 scalp on ATR ("weak")
   and said Rule 5's decision should rest **only** on DI, rolling DI, and
   forming-candle direction — mirrors the 9r ADX removal, same rationale
   (a filter blocking good entries with no benefit). Removed
   `snap.rsi < RSI_SCALP_SELL_MAX` / `snap.rsi > RSI_SCALP_BUY_MIN` and
   `snap.atr_strong` from `scalp_ok` in both `TRENDING_UP` and
   `TRENDING_DOWN` branches of `evaluate_entry()`; removed the matching
   RSI/ATR lines from `_skip_scalp_sell_reason`/`_skip_scalp_buy_reason`
   so the SKIP diagnostic only lists checks that still apply. Nothing
   shared touched — `RSI_SCALP_*` config fields and `Snapshot.atr_strong`
   still exist and are used elsewhere (WITH_TREND RSI band, SL/TP
   sizing); only Rule 5's own read of them was removed. Verified with a
   standalone test: (1) the exact dashboard scenario (rolling DI not yet
   satisfied, weak ATR) still correctly SKIPs — confirming the block was
   legitimately DI-based, not an ATR artifact; (2) a case with rolling DI
   and forming candle satisfied but ATR still weak now correctly fires.
   Dashboard Rule 5 card and `docs/current_strategy.md` updated to match.

9u. **Rule 5 correction: literal DI cross removed too, 2026-08-12.** User
   explained the original reason rolling DI existed: waiting for an actual
   DI cross (`di_minus > di_plus` / `di_plus > di_minus`) is too slow —
   by the time it happens, the move is already well along. `scalp_ok`
   (after the 9t RSI/ATR removal) still required BOTH the literal cross
   AND rolling DI, so the same slowness rolling DI was meant to solve was
   still gating it. Removed the literal cross check entirely from both
   `TRENDING_UP`/`TRENDING_DOWN` branches of `evaluate_entry()`; `scalp_ok`
   is now just rolling DI (this side's DI rising vs. the immediately
   preceding candle) AND forming-candle direction AND `scalp_allowed` —
   no requirement the side already be numerically dominant over the
   other. Matching `-DI>+DI`/`+DI>-DI` phrasing dropped from the entry
   reason strings and from `_skip_scalp_sell_reason`/
   `_skip_scalp_buy_reason`. Verified with a standalone test: a case where
   the scalp side's DI is still below the other side's (no cross yet) but
   rising vs. the prior candle, with a matching forming candle, now
   correctly fires. Dashboard card + `docs/current_strategy.md` updated.
   Scope confirmed explicitly by the user: only Rule 5, no other rule
   touched.

9v. **Pip-level SL/TP rounding added for USDJPY/GBPUSD, 2026-08-12.** Not
   part of the numbered-rules process — this is order-placement
   infrastructure (`bot_runner._round_price`), shared code, unrelated to
   any single rule's logic. User asked for USDJPY's SL/TP to round to
   0.100 (100 points/10 pips) and GBPUSD's to 0.00100 (also 10 pips).
   Checked first whether this was a broker-grid mismatch like USA30's
   (2026-08-11 fix) — it wasn't: `mt5.symbol_info()` confirmed both
   symbols' `trade_tick_size` already exactly matches `digits` (USDJPY
   0.001, GBPUSD 0.00001), so this is purely the user's own pip-level
   preference, not a validity fix. Flagged a real risk before
   implementing: USDJPY's scalp SL floor (0.046) and GBPUSD's (0.00024)
   are both smaller than the requested 0.100/0.00100 step, so naive
   "round to nearest" could shrink an already-tight stop down to a
   fraction of its intended distance (worst case ~0.012 for USDJPY,
   nearly a non-stop). User confirmed they were speaking in pip terms
   (the figures ARE pip figures) but that didn't remove the shrinkage
   risk, so implemented the safe version without re-blocking on another
   question: `cfg.ROUND_STEP` (new, optional, `None` for every other
   symbol) + `_round_price()` now takes a `reference` price and rounds
   AWAY from it (floor if below, ceil if above) whenever `ROUND_STEP` is
   set, instead of to nearest — so the computed SL/TP distance only ever
   grows, never shrinks below what the strategy intended. Both call sites
   (`_build_order_request` — reference = the broker's actual stops
   reference price, bid for BUY/ask for SELL, same value `min_dist` is
   already validated against; `_modify_sltp` — reference = current trail
   price) updated to pass it through. Verified with a standalone test:
   USDJPY/GBPUSD tight-SL cases always round further away, never closer,
   for both BUY and SELL; USA500 (no `ROUND_STEP`) produces byte-for-byte
   identical output to the pre-change rounding, confirming zero effect on
   every other symbol.

9w. **USA100 TP/SL fixed at flat 30pts, 2026-08-12.** Not a rule change —
   config-values-only, user explicit: "rules ko change nahi karna, sirf in
   ki values change karni hain." `scalp_tp_points`/`trend_tp_points`:
   20.0 -> 30.0 (TP was already fixed-points for every symbol, not
   ATR-based — just the number changed). SL: added `fixed_sl_points=30.0`
   (same mechanism USA30 already uses) so SL also bypasses ATR entirely at
   a flat 30pts instead of the old `scalp_sl_atr_mult`/`trend_sl_atr_mult`
   ATR-based sizing. No dashboard/strategy code touched — the "Rule
   coverage" table and all rule cards read `cfg.SYMBOLS` live, so the new
   values show up automatically with zero risk of a stale hardcoded
   reference.

9x. **Worked SL/TP rounding examples given for GBPUSD/USDJPY, 2026-08-12**
   (no code change, explanation only): user gave two example BUY setups
   and asked to confirm the 9v `ROUND_STEP` rounding (both symbols'
   figures already sat at an exact 10-pip DISTANCE from entry, but the
   ABSOLUTE price levels weren't on the 0.00100/0.100 grid, so rounding
   still moves them). Computed directly via `_round_price()`: GBPUSD BUY
   @1.34890 (SL 1.34790/TP 1.34990) -> SL rounds to 1.34700 (dist grows
   0.00100 -> 0.00190), TP rounds to 1.35000 (dist grows 0.00100 ->
   0.00110). USDJPY BUY @159.251 (SL 159.151/TP 159.351) -> SL rounds to
   159.100 (dist grows 0.100 -> 0.151), TP rounds to 159.400 (dist grows
   0.100 -> 0.149). Confirms rounding always widens, matching 9v's
   away-from-entry design.

9y. **USDJPY/GBPUSD SL made flat, TP shrunk to match, 2026-08-13.** User
   flagged a live USDJPY WITH_TREND position (open 159.522, SL 159.400
   dist 0.122, TP 160.100 dist 0.578) — SL close, TP blown far out, "TP ko
   SL k level per hona chahiye." Root cause: TP was already fixed at 0.5
   (widened deliberately 2026-08-11), ~5x the ATR-based SL (~0.09-0.12)
   even before 9v's ROUND_STEP grid rounding added more on top by chance
   of where the raw price fell relative to the grid. Asked the user to
   scope the fix via 3 questions (answered in sequence): (1) USDJPY, both
   modes, fixed number (not dynamic TP=SL matching) — (2) started to ask
   for a specific number, user redirected: "ATR se hatao is ko, jaise
   USA100 aur USA30 mein fixed hai waise rakho GBPUSD aur USDJPY dono
   mein" — wants the SAME fixed_sl_points pattern (no ATR at all)
   applied to BOTH USDJPY AND GBPUSD, not just USDJPY — (3) picked
   "USDJPY 0.100" (the ROUND_STEP grid value itself) when offered as the
   recommended option. Applied the same reasoning to GBPUSD (0.00100, its
   own ROUND_STEP) without a 4th question, flagged clearly so the user can
   correct if wrong. Both symbols: `scalp_tp_points`/`trend_tp_points`
   changed to match `fixed_sl_points` (USDJPY 0.5->0.100, GBPUSD
   0.00040->0.00100); `fixed_sl_points` added (USDJPY 0.100, GBPUSD
   0.00100) so SL bypasses ATR entirely, same mechanism USA30/USA100 use.
   Verified directly with a standalone test reproducing the live example:
   raw pre-rounding SL/TP are now both exactly 0.100 (USDJPY) / 0.00100
   (GBPUSD); post-ROUND_STEP-rounding they land close but not perfectly
   equal (USDJPY worked out to SL 0.122 / TP 0.178 in the test — ~1.5x
   apart instead of the old ~5x) since away-from-entry rounding can still
   add up to one extra step unevenly to each side depending on where entry
   falls on the grid. Documented this residual asymmetry honestly in
   config.py's comments and to the user rather than claiming a perfect
   1:1 fix — flagged as something to revisit if exact symmetry matters
   more than this. Values-only change, no rule/strategy logic touched.

9z. **XAUUSD scalp+reversal SL fixed at flat 2.00pts, 2026-08-13, values
   only.** User explicit: "sirf scalp aur reversal ka SL ATR ki
   calculation se hata kar 2.00 points per fix karna hai... everything
   else will remain same no change required." Different shape from every
   previous flat-SL fix (USA30/USA100/GBPUSD/USDJPY all used
   `FIXED_SL_POINTS`, which overrides BOTH scalp AND trend SL together) —
   here WITH_TREND's ATR-based SL must stay completely untouched, only
   scalp's SL changes. Added a NEW, more specific field,
   `SCALP_FIXED_SL_POINTS` (default `None` for every other symbol), read
   only by `strategy._sl_tp_scalp()` — `_sl_tp_trend()` never looks at it,
   so WITH_TREND is structurally incapable of being affected. The reversal
   (Rule 7's `_reverse_scalp()`) needed no separate change at all: it
   already always calls `_sl_tp_scalp()` directly regardless of the mode
   label `classify_side()` returns (a design already in place since
   2026-08-11, specifically so scalp and its reversal always share
   identical sizing) — so this one field automatically covers both
   scalp AND reversal, exactly as asked, with zero new code path. TP
   (`SCALP_TP_POINTS`, still 5.5) completely untouched. Verified with a
   standalone test reproducing the user's exact example (open 4565.00 ->
   SL 4563.00, both BUY and SELL) plus a control case confirming
   WITH_TREND SL on XAUUSD is still byte-for-byte ATR-based, unchanged.

9za. **Trail SL "No changes" log spam fixed, 2026-08-13** — user reported
   `[GBPUSD] Trail SL FAILED ticket=1286946977 -> 1.34853: 10025 No
   changes` and asked to fix generally if it affects all symbols. Root
   cause: `trail_all_positions()` gates the call to `_modify_sltp()` on
   the RAW pre-rounding target SL vs. the position's real current SL
   (moves every tick as price moves, so the gate almost always passes),
   but `_modify_sltp()` then rounds that target — once a symbol's grid
   (`ROUND_STEP`, added 9v/9y, or a broker's own `trade_tick_size`, USA30
   9-something) is coarser than tick-to-tick price movement, many
   different raw targets round to the price ALREADY on the position,
   which the broker correctly rejects as retcode 10025 ("No changes") —
   harmless, but logged as "FAILED" every tick, pure noise. Not
   ROUND_STEP-specific, so fixed for every symbol: `_modify_sltp()` now
   takes the position's actual current SL (`current_sl`, passed from
   `trail_all_positions()`'s `p.sl`), computes the rounded target FIRST,
   and returns early — no request sent, nothing logged — when it already
   matches. Added `mt5.TRADE_RETCODE_NO_CHANGES` (confirmed = 10025) as a
   second safety net inside the result-handling branch too, in case some
   other path still reaches `order_send` with an unchanged value.
   Verified with a standalone test (mocked `order_send`): a matching
   target sends nothing; a genuinely different target still sends
   normally, unaffected.

9zb. **Account reconciliation panel added, 2026-08-13.** User found a
   ~1717 gap between (initial deposit 100,000 - current balance 97,586.44
   = 2,413.56) and the dashboard's own Net P/L (-697.05), and asked where
   it went since nothing on the dashboard explained it. Investigated with
   `mt5.history_deals_get()` over the account's FULL history (not scoped
   to our own DB): found 8 total balance operations, not just the initial
   deposit — 7 more demo deposits/withdrawals after it, net +5,736.66,
   plain account top-ups, not trading. Also found the REAL all-time
   trading P/L (all 607 trade deals ever) is -8,150.22, while the
   dashboard's tracked Net P/L only covers trades since the last DB clear
   (sync_cutoff 2026-08-12 15:22, from this session's 9-series fresh-start
   requests) — so -7,453.17 of real trading loss exists in MT5's own
   history but is invisible on the dashboard, since we deliberately
   deleted those trade records from our local copy earlier. Verified the
   full reconciliation is EXACT: `net_deposits(5,736.66) +
   alltime_trade_pl(-8,150.22) = 97,586.44` matches the live balance to
   the cent — nothing was actually missing, just not shown. Implemented:
   new `app._account_reconciliation()` (cached 30s, walks full deal
   history via `mt5.history_deals_get()`), wired into `/api/status` as a
   new `reconcile` payload key, three new Account-panel metrics (Net
   deposits/withdrawals, All-time trade P/L, Untracked P/L) plus an
   explanatory line in `dashboard.html`. Verified end-to-end with a
   standalone script reproducing the exact live numbers and confirming
   the balance identity holds. Not part of the numbered-rules process —
   pure account/dashboard transparency feature, no strategy logic touched.

9zc. **USDJPY scalp+reversal SL cut further, 0.100 -> 0.025, 2026-08-13,
   values only.** User: "sirf scalp ka SL aur scalp reversal ka SL kum
   karke .025 karna hai, pehle .100 laga hua hai" — explicitly scoped to
   scalp+reversal only, same shape as the XAUUSD 2.00pt fix earlier the
   same day (9z). Set `scalp_fixed_sl_points=0.025` on USDJPY's config
   (already had `fixed_sl_points=0.100` from 9y, which stays exactly as
   is and now only governs WITH_TREND, since `_sl_tp_scalp` checks
   `SCALP_FIXED_SL_POINTS` before `FIXED_SL_POINTS`). No new code needed —
   the `SCALP_FIXED_SL_POINTS` mechanism and `_reverse_scalp`'s
   already-always-calls-`_sl_tp_scalp` behavior (from 9z) both already
   existed and needed zero changes, just a new config number. TP
   untouched (still flat 0.100, both modes). Verified with a standalone
   test: scalp BUY/SELL SL both land at flat 0.025 distance, WITH_TREND
   SL stays exactly flat 0.100, completely unaffected.

9zd. **Account panel sizing fixed, explanatory text removed, 2026-08-13.**
   User: "is ki sizing kharab ho gayi hai us ko theek karo aur neeche jo
   text likha hai us ko remove karo" — screenshot showed the 3 new
   reconciliation metrics (9zb) in their own separate 3-column grid below
   the main 9, with long labels ("NET DEPOSITS/WITHDRAWALS") wrapping
   badly in the narrow `span-4` panel, plus the explanatory paragraph
   looking visually disconnected. Fixed: merged all 12 metrics into ONE
   `metrics cols-3` grid (4 rows of 3 instead of 9+3 in two separate
   grids) so every tile is sized identically to the rest of the panel;
   shortened the 3 labels to fit ("Net deposits/withdrawals" -> "Net
   deposits", "All-time trade P/L" -> "All-time P/L", "Untracked P/L"
   unchanged); removed the explanatory `<p>` entirely, as asked. No JS/
   backend changes needed — same element IDs (`netDeposits`, `alltimePl`,
   `untrackedPl`), same `/api/status` `reconcile` payload from 9zb.

9d. **Dashboard: "Detailed rule flow" section added below the coverage
   table** (`app.py._build_process_rules()`) — the same standing
   reference, but as full behavioral rules instead of single-line config
   checks: WITH_TREND entry conditions, what happens on WITH_TREND TP/SL,
   scalp entry conditions, what happens on scalp TP/SL, the reversal
   trade's own basis and checks, and every rolling-DI call site (both
   mechanisms: the strict `_momentum_recovered` — 7 sites — and the
   looser benchmark/2-candle `_check_scalp_rearm` — 1 site, only after a
   scalp+reversal double-loss). Each card lists which symbols it applies
   to, same verified-not-typed guarantee as the table above it.

Full strategy reference: `code/docs/current_strategy.md` (kept in sync
with the live bot going forward — read the live copy at
`c:\bot\docs\current_strategy.md` for anything after this save point).

## Stats baseline at save time (account 49825877, demo)

Overall: 30 trades, 11 wins / 19 losses (36.7% win rate), net -478.40

| Symbol | Trades | W/L | Win% | Net profit |
|---|---|---|---|---|
| USA500 | 8 | 2/6 | 25.0% | -8.58 |
| USA100 | 5 | 3/2 | 60.0% | +18.47 |
| USA30  | 5 | 3/2 | 60.0% | +44.56 |
| XAUUSD | 5 | 3/2 | 60.0% | -415.00 |
| GBPUSD | 3 | 0/3 | 0.0%  | -1.06 |
| USDJPY | 4 | 0/4 | 0.0%  | -116.79 |

(XAUUSD's -415 on a 60% win rate is lot-size/point-value driven, not a
strategy-logic issue — its per-trade loss size is just much larger than
the other symbols at the current LOT setting.)

## Versioning pattern going forward

Each time we intentionally checkpoint the bot (a meaningful logic change,
or just "stop and record where we are"): copy `code/` + a `stats/` DB
snapshot into `c:\bot\versions\v<N>\`, same layout as this folder, with a
`NOTES.md` listing what changed since the previous version and the stats
baseline at that point. Next one is `v3`.
