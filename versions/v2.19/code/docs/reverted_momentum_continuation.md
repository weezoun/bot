# Reverted feature: scalp-TP momentum continuation

**Status:** Built, tested against live trades, then reverted on 2026-08-11.
**Where it lived:** `bot_runner.py` (removed) — see git history around this
file's introduction for the exact diff if needed.

## What it was

After a `COUNTER_SCALP` position hit **TP** (a win), this watched the
**opposite** (with-trend) side's DI for a genuine reversal and — if found —
fired an early, tight-SL "trial" entry in that direction, instead of waiting
for `evaluate_entry()`'s full DI-cross confirmation (which can lag the actual
price move by several candles).

### Mechanism

1. **Baseline capture** — every DI regime flip (in `bot_tick()`), snapshot
   both DI lines: `state.regime_opposite_di_baseline = {'plus': di_plus, 'minus': di_minus}`.
   This is the level the losing side needs to *reclaim* to prove it's
   genuinely back in contention (same "prior demonstrated strength" idea as
   `scalp_rearm_gate`).

2. **Watch trigger** (`_check_momentum_continuation`, called from
   `_classify_and_record_close` on a `COUNTER_SCALP` TP) — starts
   `state.momentum_watch = {'side': opposite, 'benchmark': baseline, 'rise_streak': 0, 'last_bar_time': None}`.

3. **Per-tick check** (`_check_momentum_watch`, called every `bot_tick()`) —
   dual-path confirmation, same shape as `_check_scalp_rearm`:
   - **Fast:** current DI crosses above the benchmark → fire immediately.
   - **Slow:** DI rises candle-over-candle for 2 candles in a row → fire.

4. **Fire** (`_fire_momentum_trial`) — opens a tight-SL/TP position
   (`_sl_tp_scalp` sizing, not full WITH_TREND size), mode-tagged
   `'MOMENTUM_TRIAL'`, capped at one attempt per DI regime
   (`state.momentum_trial_used`). Also records
   `state.momentum_trial_exit = {'ticket','side','watch_side','benchmark'}`
   — `watch_side`'s benchmark = the scalp side's own DI at the moment the
   trial opened.

5. **Proactive early exit** (`_check_momentum_trial_exit`, every tick) — if
   the scalp side's DI reclaims *its* benchmark (momentum swinging back),
   closes the trial early via `_close_ticket`, rather than waiting for its
   own SL.

All four state fields were reset on every DI regime flip.

### Reference code (as it was, for reuse)

```python
def _check_momentum_continuation(scalp_side: str, live_snap):
    if state.momentum_trial_used:
        return
    opposite = 'SELL' if scalp_side == 'BUY' else 'BUY'
    if state.momentum_watch and state.momentum_watch['side'] == opposite:
        return
    baseline = None
    if state.regime_opposite_di_baseline:
        baseline = state.regime_opposite_di_baseline.get('minus' if opposite == 'SELL' else 'plus')
    if baseline is None:
        baseline = _relevant_di(opposite, live_snap)
    state.momentum_watch = {'side': opposite, 'benchmark': baseline, 'rise_streak': 0, 'last_bar_time': None}


def _check_momentum_watch(live_snap):
    watch = state.momentum_watch
    if not watch:
        return
    side = watch['side']
    current = _relevant_di(side, live_snap)
    fast = current > watch['benchmark']
    slow = False
    if live_snap.bar_time != watch['last_bar_time']:
        prev = live_snap.prev_di_minus if side == 'SELL' else live_snap.prev_di_plus
        watch['rise_streak'] = watch['rise_streak'] + 1 if current > prev else 0
        watch['last_bar_time'] = live_snap.bar_time
        slow = watch['rise_streak'] >= 2
    if fast or slow:
        state.momentum_watch = None
        _fire_momentum_trial(side, live_snap, "benchmark cross" if fast else "2 rising candles")


def _fire_momentum_trial(side: str, live_snap, reason: str):
    if state.momentum_trial_used or not should_take_trade():
        return
    sl, tp = _sl_tp_scalp(side, live_snap.close, live_snap.atr)
    state.momentum_trial_used = True
    state.momentum_gate = None
    state.last_bar_time = live_snap.bar_time
    ticket = send_order(side, sl, tp, f'MOM_{side}', 'MOMENTUM_TRIAL',
                         f"Early opposite-direction trial after scalp TP ({reason})")
    if ticket:
        watch_side = 'SELL' if side == 'BUY' else 'BUY'
        state.momentum_trial_exit = {'ticket': ticket, 'side': side, 'watch_side': watch_side,
                                      'benchmark': _relevant_di(watch_side, live_snap)}


def _check_momentum_trial_exit(live_snap):
    watch = state.momentum_trial_exit
    if not watch:
        return
    current = _relevant_di(watch['watch_side'], live_snap)
    if current <= watch['benchmark']:
        return
    positions = mt5.positions_get(ticket=watch['ticket']) or []
    if not positions:
        state.momentum_trial_exit = None
        return
    _close_ticket(positions[0], "MomentumReverse")
    state.momentum_trial_exit = None
```

Wiring (removed): call `_check_momentum_continuation(side, live_snap)` from
`_classify_and_record_close`'s `COUNTER_SCALP` TP branch; call
`_check_momentum_watch(live_snap)` and `_check_momentum_trial_exit(live_snap)`
every tick in `bot_tick()`; capture/reset the 4 state fields in the DI
regime-flip block.

## Why it was reverted

1. **In a choppy DI range it barely differs from the existing gate.** The
   baseline is captured at the crossover instant, when both DI lines are
   ~equal — in a market where +DI/-DI stay in a tight band (observed:
   19.9 vs 19.7, 20.8 vs 20.1 on 2026-08-10), reclaiming that baseline ends
   up numerically close to a full DI cross anyway. The "2 rising candles"
   fast-path was the only genuinely earlier trigger, and even that fires
   into the same problem below.

2. **Tight SL + a late/weak signal is a near-guaranteed loss, regardless of
   whether the read is right.** Whenever this fires, it's firing right at a
   DI transition zone — the noisiest part of the move. A scalp-tight SL
   there gets taken out by ordinary noise almost independent of direction,
   which defeats the point of building confirmation logic at all: the
   *risk sizing* determines the outcome, not the *signal quality*.

3. **Timing** — it was proposed and built while the account was already in a
   drawdown session (balance $10.84 → $7.50). Adding a new speculative
   entry path (even risk-capped) compounds exposure at exactly the wrong
   moment; the account needed fewer new bets, not more.

## If revisiting this later

The core idea (early reversal detection via a genuine DI benchmark, not just
a noisy one-candle check) isn't necessarily wrong — the failure mode was
specifically the *tight* SL paired with a *late* trigger. A future attempt
should probably either:
- give the trial a wider SL (accepting it can't be scalp-tight if the entry
  itself isn't confirmed), funded by the DI-based proactive exit doing the
  real risk-cutting work instead of the price SL, or
- find a genuinely earlier trigger than "DI reclaiming its regime-start
  level" — e.g. price-action based (higher low / lower high structure)
  rather than DI-only, since DI lag was the root problem this was trying to
  route around in the first place.
