"""Pure indicator + signal logic for dual-mode ADX/DI/RSI strategy.

Indicator calculation (calculate_indicators/build_snapshot) uses only
shared, symbol-agnostic config (RSI_PERIOD). Everything past that — the
actual entry/exit decisions — takes an explicit `cfg: config.SymbolConfig`
argument instead of importing thresholds from a single global module. That's
what lets bot_runner.SymbolBot run this exact same logic for USA500 and
XAUUSD at the same time with independent thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd

import config as cfg  # only for the shared RSI_PERIOD constant, see calculate_indicators


@dataclass
class Snapshot:
    bar_time: int
    close: float
    open: float
    ema50: float
    ema200: float
    adx: float
    di_plus: float
    di_minus: float
    prev_di_plus: float
    prev_di_minus: float
    atr: float
    atr_mean: float
    prev_atr: float
    rsi: float
    prev_rsi: float
    trend: str
    condition: str
    atr_weak: bool
    atr_strong: bool

    def to_dict(self):
        return asdict(self)


@dataclass
class Signal:
    action: str  # BUY, SELL, CLOSE_SELLS_THEN_BUY, CLOSE_BUYS_THEN_SELL, HOLD, MANAGE
    mode: str    # WITH_TREND, COUNTER_SCALP, FLIP, NONE
    reason: str
    sl: Optional[float] = None
    tp: Optional[float] = None
    trail_with_trend: bool = False

    def to_dict(self):
        return asdict(self)


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False).mean()


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data['50EMA'] = data['close'].ewm(span=50, adjust=False).mean()
    data['200EMA'] = data['close'].ewm(span=200, adjust=False).mean()

    prev_close = data['close'].shift(1)
    tr = pd.concat([
        data['high'] - data['low'],
        (data['high'] - prev_close).abs(),
        (data['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    data['ATR'] = _wilder_smooth(tr, 14)

    # RSI (Wilder)
    delta = data['close'].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = _wilder_smooth(gain, cfg.RSI_PERIOD)
    avg_loss = _wilder_smooth(loss, cfg.RSI_PERIOD)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    data['RSI'] = 100 - (100 / (1 + rs))
    data['RSI'] = data['RSI'].fillna(50)

    # ADX / DI
    h_ph = data['high'] - data['high'].shift(1)
    pl_l = data['low'].shift(1) - data['low']
    plus_dm = np.where((h_ph > pl_l) & (h_ph > 0), h_ph, 0.0)
    minus_dm = np.where((pl_l > h_ph) & (pl_l > 0), pl_l, 0.0)

    tr14 = _wilder_smooth(tr, 14)
    plus_dm14 = _wilder_smooth(pd.Series(plus_dm, index=data.index), 14)
    minus_dm14 = _wilder_smooth(pd.Series(minus_dm, index=data.index), 14)

    data['+DI_14'] = (100 * (plus_dm14 / tr14.replace(0, np.nan))).fillna(0)
    data['-DI_14'] = (100 * (minus_dm14 / tr14.replace(0, np.nan))).fillna(0)
    di_sum = (data['+DI_14'] + data['-DI_14']).replace(0, np.nan)
    dx = (100 * (data['+DI_14'] - data['-DI_14']).abs() / di_sum).fillna(0)
    data['ADX'] = _wilder_smooth(dx, 14).replace([np.inf, -np.inf], 0).ffill().bfill()

    return data


def build_snapshot(data: pd.DataFrame, bar_offset: int = -2) -> Optional[Snapshot]:
    """bar_offset=-2 closed signal bar; -1 = forming bar (live preview)."""
    need = 50 if bar_offset == -2 else 51
    if len(data) < need:
        return None
    i = bar_offset
    ema50 = float(data['50EMA'].iloc[i])
    ema200 = float(data['200EMA'].iloc[i])
    close = float(data['close'].iloc[i])
    open_ = float(data['open'].iloc[i])
    prev_close = float(data['close'].iloc[i - 1])
    atr = float(data['ATR'].iloc[i])
    atr_mean = float(data['ATR'].iloc[-50:].mean())
    prev_atr = float(data['ATR'].iloc[i - 1])
    adx = float(data['ADX'].iloc[i])
    di_plus = float(data['+DI_14'].iloc[i])
    di_minus = float(data['-DI_14'].iloc[i])
    prev_di_plus = float(data['+DI_14'].iloc[i - 1])
    prev_di_minus = float(data['-DI_14'].iloc[i - 1])
    rsi = float(data['RSI'].iloc[i])
    prev_rsi = float(data['RSI'].iloc[i - 1])

    if ema50 > ema200:
        trend = 'TRENDING_UP'
    elif ema50 < ema200:
        trend = 'TRENDING_DOWN'
    else:
        trend = 'NEUTRAL'

    if atr > atr_mean * 1.2:
        condition = 'VOLATILE'
    elif abs(close - prev_close) < (atr * 0.25):
        condition = 'RANGING'
    else:
        condition = 'NORMAL'

    atr_weak = atr < atr_mean
    # Momentum expansion (dumps/rallies). Two ways in, whichever fires first:
    # (1) ATR already above its own 50-bar mean (absolute level), or
    # (2) ATR expanding candle-over-candle (rolling) — catches a move that's
    # genuinely picking up energy right now but hasn't caught up to its
    # slow-moving average yet, instead of waiting on a lagging static bar.
    atr_strong = (atr >= atr_mean) or (atr > prev_atr)

    bar_time = int(data['time'].iloc[i])
    return Snapshot(
        bar_time=bar_time,
        close=close,
        open=open_,
        ema50=ema50,
        ema200=ema200,
        adx=adx,
        di_plus=di_plus,
        di_minus=di_minus,
        prev_di_plus=prev_di_plus,
        prev_di_minus=prev_di_minus,
        atr=atr,
        atr_mean=atr_mean,
        prev_atr=prev_atr,
        rsi=rsi,
        prev_rsi=prev_rsi,
        trend=trend,
        condition=condition,
        atr_weak=atr_weak,
        atr_strong=atr_strong,
    )


def _sl_tp_trend(side: str, entry: float, atr: float, cfg):
    if cfg.FIXED_SL_POINTS is not None:
        sl_d = cfg.FIXED_SL_POINTS  # flat distance, bypasses ATR entirely — see config.py
    else:
        atr = max(atr, cfg.MIN_ATR)
        sl_d = atr * cfg.TREND_SL_ATR_MULT  # SL stays ATR-based — room to breathe
    tp_d = cfg.TREND_TP_POINTS  # TP is fixed, small — secure the win fast
    if side == 'BUY':
        return entry - sl_d, entry + tp_d
    return entry + sl_d, entry - tp_d


def _sl_tp_scalp(side: str, entry: float, atr: float, cfg):
    # SCALP_FIXED_SL_POINTS (scalp-only override, e.g. XAUUSD 2026-08-13)
    # takes priority over FIXED_SL_POINTS (which would also affect
    # _sl_tp_trend) — see config.py's SymbolConfig for the distinction.
    if cfg.SCALP_FIXED_SL_POINTS is not None:
        sl_d = cfg.SCALP_FIXED_SL_POINTS
    elif cfg.FIXED_SL_POINTS is not None:
        sl_d = cfg.FIXED_SL_POINTS
    else:
        atr = max(atr, cfg.MIN_ATR)
        sl_d = max(atr * cfg.SCALP_SL_ATR_MULT, cfg.SCALP_SL_FLOOR)
    tp_d = cfg.SCALP_TP_POINTS
    if side == 'BUY':
        return entry - sl_d, entry + tp_d
    return entry + sl_d, entry - tp_d


def classify_side(side: str, snap: Snapshot, cfg):
    """Classify an immediate reversal re-entry (fired right after a COUNTER_SCALP
    gets stopped out) against the CURRENT big trend — not the mode of the scalp
    it followed. The opposite of a counter-scalp direction is, by definition,
    the WITH-trend direction, so this almost always comes back WITH_TREND
    rather than another scalp — trail_with_trend is informational only, since
    bot_runner._reverse_scalp always sizes SL/TP scalp-tight regardless of
    which mode this returns (see its docstring).

    Returns (mode, sl, tp, trail_with_trend).
    """
    aligned = (
        (side == 'BUY' and snap.trend == 'TRENDING_UP')
        or (side == 'SELL' and snap.trend == 'TRENDING_DOWN')
    )
    if aligned:
        sl, tp = _sl_tp_trend(side, snap.close, snap.atr, cfg)
        return 'WITH_TREND', sl, tp, True
    sl, tp = _sl_tp_scalp(side, snap.close, snap.atr, cfg)
    return 'COUNTER_SCALP', sl, tp, False


def _bullish_candle(snap: Snapshot) -> bool:
    return snap.close > snap.open


def _bearish_candle(snap: Snapshot) -> bool:
    return snap.close < snap.open


def _rsi_buy_ceiling(snap: Snapshot, cfg) -> float:
    """Confirmed strong trend (high ADX) gets more RSI room — a persistent
    strong trend can keep RSI pinned near its extreme for a long stretch
    without that meaning exhaustion."""
    if snap.adx >= cfg.ADX_STRONG_TREND:
        return cfg.RSI_WITH_TREND_BUY_MAX_STRONG
    return cfg.RSI_WITH_TREND_BUY_MAX


def _rsi_sell_floor(snap: Snapshot, cfg) -> float:
    if snap.adx >= cfg.ADX_STRONG_TREND:
        return cfg.RSI_WITH_TREND_SELL_MIN_STRONG
    return cfg.RSI_WITH_TREND_SELL_MIN


def evaluate_flip(live_snap: Snapshot, closed_snap: Snapshot, has_buy: bool, has_sell: bool, cfg,
                   rule3_gate: Optional[dict] = None, rule4_gate: Optional[dict] = None) -> Optional[Signal]:
    """Close opposite scalps and reverse into with-trend when momentum flips.

    FLIP has its own separate confirmation criteria (DI flip/strong + RSI,
    not Rule 2's last-closed-candle-color checks). It DOES still need to
    respect rule3_gate/rule4_gate, though — a WITH_TREND close on a side
    should block FLIP into that same side too, same as it blocks a fresh
    Rule 2 entry (originally found and fixed 2026-08-11: FLIP used to
    skip this entirely, letting a WITH_TREND TP reopen same-candle via
    this path even though the normal entry route was correctly blocked).

    Regression found and fixed 2026-08-12: when Rule 3/Rule 4 were split
    out of the old shared momentum_gate, this function was left checking
    nothing at all — decide() hardcoded momentum_gate=None here, silently
    disabling the gate instead of rewiring it to the new fields. This
    reintroduced the exact same-candle-re-entry bug the 2026-08-11 fix
    was for. Uses the same trivial presence/side-check pattern as Rule 2
    (evaluate_entry) — never computes or duplicates either gate's
    clearing conditions."""
    if live_snap.trend == 'TRENDING_UP' and has_sell:
        di_flip = live_snap.di_plus > live_snap.di_minus and live_snap.prev_di_plus <= live_snap.prev_di_minus
        di_strong = live_snap.di_plus > live_snap.di_minus and live_snap.di_plus > live_snap.prev_di_plus
        rsi_up = live_snap.rsi > live_snap.prev_rsi and live_snap.rsi >= 45
        adx_ok = live_snap.adx >= cfg.ADX_MIN
        blocked = (rule3_gate and rule3_gate.get('side') == 'BUY') or (rule4_gate and rule4_gate.get('side') == 'BUY')
        if adx_ok and (di_flip or di_strong) and rsi_up and not blocked:
            sl, tp = _sl_tp_trend('BUY', live_snap.close, live_snap.atr, cfg)
            return Signal(
                action='CLOSE_SELLS_THEN_BUY',
                mode='FLIP',
                reason=f"Flip UP: +DI {live_snap.di_plus:.1f}>-DI {live_snap.di_minus:.1f}, RSI {live_snap.rsi:.1f} rising",
                sl=sl,
                tp=tp,
                trail_with_trend=True,
            )

    if live_snap.trend == 'TRENDING_DOWN' and has_buy:
        di_flip = live_snap.di_minus > live_snap.di_plus and live_snap.prev_di_minus <= live_snap.prev_di_plus
        di_strong = live_snap.di_minus > live_snap.di_plus and live_snap.di_minus > live_snap.prev_di_minus
        rsi_down = live_snap.rsi < live_snap.prev_rsi and live_snap.rsi <= 55
        adx_ok = live_snap.adx >= cfg.ADX_MIN
        blocked = (rule3_gate and rule3_gate.get('side') == 'SELL') or (rule4_gate and rule4_gate.get('side') == 'SELL')
        if adx_ok and (di_flip or di_strong) and rsi_down and not blocked:
            sl, tp = _sl_tp_trend('SELL', live_snap.close, live_snap.atr, cfg)
            return Signal(
                action='CLOSE_BUYS_THEN_SELL',
                mode='FLIP',
                reason=f"Flip DOWN: -DI {live_snap.di_minus:.1f}>+DI {live_snap.di_plus:.1f}, RSI {live_snap.rsi:.1f} falling",
                sl=sl,
                tp=tp,
                trail_with_trend=True,
            )
    return None


def _skip_scalp_sell_reason(snap: Snapshot, cfg) -> str:
    """Explain why counter-trend SELL is not ready (trend UP)."""
    parts = []
    if not (snap.di_minus > snap.prev_di_minus):
        parts.append(f"-DI({snap.di_minus:.1f}) not rising vs prior candle ({snap.prev_di_minus:.1f}) (Rule 5)")
    if not _bearish_candle(snap):
        parts.append("forming candle not red (Rule 5)")
    return "; ".join(parts) if parts else "scalp conditions OK"


def _skip_scalp_buy_reason(snap: Snapshot, cfg) -> str:
    parts = []
    if not (snap.di_plus > snap.prev_di_plus):
        parts.append(f"+DI({snap.di_plus:.1f}) not rising vs prior candle ({snap.prev_di_plus:.1f}) (Rule 5)")
    if not _bullish_candle(snap):
        parts.append("forming candle not green (Rule 5)")
    return "; ".join(parts) if parts else "scalp conditions OK"


def _momentum_recovered(side: str, live_snap: Snapshot, closed_snap: Snapshot,
                         momentum_gate: Optional[dict]) -> bool:
    """After a WITH_TREND close (SL or TP), the "DI still > DI" check alone
    isn't enough — that comparison can stay nominally true while the DI
    value itself keeps fading (momentum genuinely dying), letting the bot
    re-enter the same direction next candle.

    Rolling check (not a frozen close-time value): require this side's DI to
    be HIGHER than it was on the immediately PRECEDING candle — i.e.
    momentum is ticking up again right now, candle over candle. A fixed
    historical baseline can take a whole session to reclaim if DI keeps
    grinding lower after the close; a rolling comparison reacts the moment
    DI turns, so a genuine continuation isn't missed — at the cost of being
    looser (one up-tick is enough, even if DI is still objectively weak).

    Candle color must be checked on the LAST FULLY CLOSED candle
    (closed_snap), NOT the live/forming one (corrected 2026-08-11 — using
    live_snap here let the bot enter mid-candle off a transient in-progress
    color that could still reverse before that candle actually closed).
    closed_snap.bar_time must be STRICTLY AFTER the gate's bar_time — equal
    means the most recently closed candle IS the one the SL/TP happened on,
    so it isn't eligible; the bot has to wait for a candle *after* that one
    to finish, then check whether THAT candle closed in the confirming
    color. If it closes the wrong color, this keeps returning False and the
    wait continues into the next candle — a genuine extra-candle pause
    (during which a scalp on either side can still fire independently).
    """
    if not momentum_gate or momentum_gate.get('side') != side:
        return True
    if closed_snap.bar_time <= momentum_gate.get('bar_time'):
        return False
    if side == 'BUY':
        return live_snap.di_plus > live_snap.prev_di_plus and _bullish_candle(closed_snap)
    return live_snap.di_minus > live_snap.prev_di_minus and _bearish_candle(closed_snap)


def _skip_trend_buy_reason(snap: Snapshot, closed_snap: Snapshot, cfg,
                            rule3_gate: Optional[dict] = None,
                            rule4_gate: Optional[dict] = None) -> str:
    """rule3_gate/rule4_gate: only ever READ here (side-match presence
    check) — the actual clearing conditions for each are computed
    entirely inside their own dedicated bot_runner methods
    (_check_rule3_gate / _check_rule4_gate), never here. This function
    must never branch on gate internals beyond "is it currently set for
    this side" — that's the isolation boundary (2026-08-12)."""
    parts = []
    if snap.adx < cfg.ADX_MIN:
        parts.append(f"ADX({snap.adx:.1f}) < {cfg.ADX_MIN}")
    if not (snap.di_plus > snap.di_minus):
        parts.append(f"+DI({snap.di_plus:.1f}) <= -DI({snap.di_minus:.1f})")
    ceiling = _rsi_buy_ceiling(snap, cfg)
    if snap.rsi < 40 or snap.rsi > ceiling:
        parts.append(f"RSI({snap.rsi:.1f}) outside 40–{ceiling:.0f} (ADX {snap.adx:.1f})")
    if not _bullish_candle(closed_snap):
        parts.append("last CLOSED candle not green")
    if _bearish_candle(snap):
        parts.append("forming candle currently red (opposite direction)")
    if rule3_gate and rule3_gate.get('side') == 'BUY':
        parts.append("Rule 3 gate active (blocked after a WITH_TREND TP)")
    if rule4_gate and rule4_gate.get('side') == 'BUY':
        parts.append("Rule 4 gate active (blocked after a WITH_TREND SL)")
    return "; ".join(parts) if parts else "trend BUY conditions OK"


def _skip_trend_sell_reason(snap: Snapshot, closed_snap: Snapshot, cfg,
                             rule3_gate: Optional[dict] = None,
                             rule4_gate: Optional[dict] = None) -> str:
    """See _skip_trend_buy_reason's docstring — same isolation boundary."""
    parts = []
    if snap.adx < cfg.ADX_MIN:
        parts.append(f"ADX({snap.adx:.1f}) < {cfg.ADX_MIN}")
    if not (snap.di_minus > snap.di_plus):
        parts.append(f"-DI({snap.di_minus:.1f}) <= +DI({snap.di_plus:.1f})")
    floor = _rsi_sell_floor(snap, cfg)
    if snap.rsi < floor or snap.rsi > 60:
        parts.append(f"RSI({snap.rsi:.1f}) outside {floor:.0f}–60 (ADX {snap.adx:.1f})")
    if not _bearish_candle(closed_snap):
        parts.append("last CLOSED candle not red")
    if _bullish_candle(snap):
        parts.append("forming candle currently green (opposite direction)")
    if rule3_gate and rule3_gate.get('side') == 'SELL':
        parts.append("Rule 3 gate active (blocked after a WITH_TREND TP)")
    if rule4_gate and rule4_gate.get('side') == 'SELL':
        parts.append("Rule 4 gate active (blocked after a WITH_TREND SL)")
    return "; ".join(parts) if parts else "trend SELL conditions OK"


def evaluate_entry(snap: Snapshot, closed_snap: Snapshot, cfg, scalp_allowed: bool = True,
                    rule3_gate: Optional[dict] = None, rule4_gate: Optional[dict] = None) -> Signal:
    """New entry when flat. Prefer counter-scalp when short-term opposes big trend.

    cfg: config.SymbolConfig — this symbol's thresholds.

    closed_snap: the last FULLY CLOSED M15 bar — used for the
    last-closed-candle-color check on a WITH_TREND entry.

    scalp_allowed: False once a counter-scalp has already been fired for the
    current DI regime (see bot_runner). Prevents repeatedly re-entering the
    same counter-trend scalp on every stop-out while -DI/+DI stays lopsided —
    DI is lagging, so the condition can stay true long after price has already
    turned back with the big trend. A fresh DI cross re-arms it.

    rule3_gate / rule4_gate: {'side': 'BUY'|'SELL', 'bar_time': ...} or None
    — set by bot_runner right after a WITH_TREND TP / SL closes. Read here
    ONLY as a simple "is it currently set for this side" presence
    check — the actual clearing conditions (rolling DI, candle color, etc.)
    for each are computed entirely inside their own dedicated bot_runner
    methods (_check_rule3_gate / _check_rule4_gate) and never duplicated
    here. This is a deliberate isolation boundary (2026-08-12, explicit
    instruction): editing either gate's clearing logic must never require
    touching this function, and vice versa.
    """
    if snap.trend == 'NEUTRAL':
        return Signal('HOLD', 'NONE', 'SKIP: Trend NEUTRAL — wait for EMA cross')

    # ADX_MIN gate removed from here for Rule 5 (scalp) — DI alone is
    # sufficient for a counter-trend scalp; ADX was blocking scalp entries
    # outright with no benefit. Still required for Rule 2 (WITH_TREND),
    # checked as part of trend_ok below, unchanged for that rule.

    # --- Counter-trend scalp (UP big trend, short-term sell pressure) ---
    # RSI and ATR removed from Rule 5's own decision (2026-08-12) — ATR was
    # blocking good scalp entries outright with no benefit; the user's
    # instruction is that Rule 5's decision rests on DI + rolling DI +
    # forming candle direction only. RSI/ATR fields still exist on Snapshot
    # for other uses; just not read here anymore.
    if snap.trend == 'TRENDING_UP':
        # Rule 5, corrected 2026-08-12: the literal instantaneous cross
        # (-DI > +DI) was removed — the user's original reason for adding
        # rolling DI in the first place was that waiting for an actual
        # cross is too slow/late; requiring the cross ON TOP of rolling DI
        # defeated that purpose. Decision now rests purely on rolling DI
        # (this side's DI above the immediately preceding candle —
        # accelerating right now) + forming candle DEFINITELY the same
        # direction as the trade (absolute requirement, not "not
        # opposite"). Both read live_snap directly, catching a genuine move
        # as it's forming rather than waiting for it to close or to fully
        # overtake the other side.
        scalp_ok = (
            snap.di_minus > snap.prev_di_minus   # Rule 5: rolling DI
            and _bearish_candle(snap)              # Rule 5: forming candle same direction (red)
            and scalp_allowed
        )
        if scalp_ok:
            sl, tp = _sl_tp_scalp('SELL', snap.close, snap.atr, cfg)
            return Signal(
                action='SELL',
                mode='COUNTER_SCALP',
                reason=(
                    f"Rule 5: Scalp SELL: -DI {snap.di_minus:.1f} rising vs prior "
                    f"({snap.prev_di_minus:.1f}), red candle (trend UP)"
                ),
                sl=sl,
                tp=tp,
                trail_with_trend=False,
            )

        # With-trend BUY (Rule 2). Candle color checked on the LAST CLOSED
        # bar, not the live/forming one (corrected 2026-08-11) — a live-only
        # check let the bot enter off a transient in-progress green a few
        # seconds into a fresh candle, which then reversed and closed red
        # minutes later (found directly: XAUUSD, ticket 1284485196, entered
        # 3s into a new bar, that same bar closed red, SL hit). DI/RSI stay
        # on the live snap for responsiveness — only candle color needs a
        # genuinely finished bar behind it. Rule 2 additionally requires the
        # CURRENTLY FORMING candle to not itself be moving the opposite way
        # right now — the last closed candle being green isn't enough if
        # price has already turned red again since then.
        trend_ok = (
            snap.adx >= cfg.ADX_MIN                    # Rule 2's own ADX gate
            and snap.di_plus > snap.di_minus
            and snap.rsi <= _rsi_buy_ceiling(snap, cfg)
            and snap.rsi >= 40
            and _bullish_candle(closed_snap)          # last CLOSED candle: same direction (Rule 2)
            and not _bearish_candle(snap)              # forming candle: not opposite direction (Rule 2)
            and not (rule3_gate and rule3_gate.get('side') == 'BUY')  # presence check only
            and not (rule4_gate and rule4_gate.get('side') == 'BUY')  # presence check only
        )
        if trend_ok:
            sl, tp = _sl_tp_trend('BUY', snap.close, snap.atr, cfg)
            return Signal(
                action='BUY',
                mode='WITH_TREND',
                reason=f"Rule 2: With-trend BUY: +DI {snap.di_plus:.1f}>-DI {snap.di_minus:.1f}, RSI {snap.rsi:.1f}, green candle",
                sl=sl,
                tp=tp,
                trail_with_trend=True,
            )
        skip = _skip_scalp_sell_reason(snap, cfg)
        if not scalp_allowed:
            skip += "; already scalped this DI regime"
        return Signal(
            'HOLD', 'NONE',
            f"SKIP UP: scalp SELL blocked [{skip}] | "
            f"trend BUY blocked [{_skip_trend_buy_reason(snap, closed_snap, cfg, rule3_gate, rule4_gate)}]"
        )

    # --- TRENDING_DOWN ---
    if snap.trend == 'TRENDING_DOWN':
        # Rule 5 — see the matching SELL-scalp branch above for the full
        # rationale (instantaneous cross removed, rolling DI + candle only);
        # mirrored here for BUY.
        scalp_ok = (
            snap.di_plus > snap.prev_di_plus     # Rule 5: rolling DI
            and _bullish_candle(snap)              # Rule 5: forming candle same direction (green)
            and scalp_allowed
        )
        if scalp_ok:
            sl, tp = _sl_tp_scalp('BUY', snap.close, snap.atr, cfg)
            return Signal(
                action='BUY',
                mode='COUNTER_SCALP',
                reason=(
                    f"Rule 5: Scalp BUY: +DI {snap.di_plus:.1f} rising vs prior "
                    f"({snap.prev_di_plus:.1f}), green candle (trend DOWN)"
                ),
                sl=sl,
                tp=tp,
                trail_with_trend=False,
            )

        # With-trend SELL (Rule 2) — candle checks mirror the BUY branch above.
        trend_ok = (
            snap.adx >= cfg.ADX_MIN                    # Rule 2's own ADX gate
            and snap.di_minus > snap.di_plus
            and snap.rsi >= _rsi_sell_floor(snap, cfg)
            and snap.rsi <= 60
            and _bearish_candle(closed_snap)          # last CLOSED candle: same direction (Rule 2)
            and not _bullish_candle(snap)              # forming candle: not opposite direction (Rule 2)
            and not (rule3_gate and rule3_gate.get('side') == 'SELL')  # presence check only
            and not (rule4_gate and rule4_gate.get('side') == 'SELL')  # presence check only
        )
        if trend_ok:
            sl, tp = _sl_tp_trend('SELL', snap.close, snap.atr, cfg)
            return Signal(
                action='SELL',
                mode='WITH_TREND',
                reason=f"Rule 2: With-trend SELL: -DI {snap.di_minus:.1f}>+DI {snap.di_plus:.1f}, RSI {snap.rsi:.1f}, red candle",
                sl=sl,
                tp=tp,
                trail_with_trend=True,
            )
        skip = _skip_scalp_buy_reason(snap, cfg)
        if not scalp_allowed:
            skip += "; already scalped this DI regime"
        return Signal(
            'HOLD', 'NONE',
            f"SKIP DOWN: scalp BUY blocked [{skip}] | "
            f"trend SELL blocked [{_skip_trend_sell_reason(snap, closed_snap, cfg, rule3_gate, rule4_gate)}]"
        )

    return Signal('HOLD', 'NONE', 'SKIP: No signal')


def decide(snap: Snapshot, closed_snap: Snapshot, cfg, has_buy: bool, has_sell: bool,
           already_entered_this_bar: bool, scalp_allowed: bool = True,
           rule3_gate: Optional[dict] = None, rule4_gate: Optional[dict] = None) -> Signal:
    """Live-bar decisions. already_entered_this_bar only blocks a second entry, not reason updates.

    closed_snap: last FULLY CLOSED M15 bar — passed to evaluate_entry for
    its last-closed-candle-color check.

    rule3_gate / rule4_gate: see evaluate_entry()'s docstring — simple
    presence-check state read only, isolation boundary (2026-08-12).
    Passed through to evaluate_flip() too (regression fix, 2026-08-12 —
    see its docstring): FLIP has its own separate confirmation criteria,
    but still respects these same gates, same as a fresh Rule 2 entry."""
    flip = evaluate_flip(snap, closed_snap, has_buy, has_sell, cfg, rule3_gate, rule4_gate)
    if flip:
        if already_entered_this_bar and not (has_buy or has_sell):
            # rare: flipped and flat but already entered earlier this bar
            return Signal('MANAGE', 'FLIP', f"Already acted this M15 | {flip.reason}",
                          sl=flip.sl, tp=flip.tp, trail_with_trend=True)
        return flip

    if has_buy or has_sell:
        side = "BUY" if has_buy else "SELL"
        entry = evaluate_entry(snap, closed_snap, cfg, scalp_allowed, rule3_gate, rule4_gate)
        return Signal(
            'MANAGE', entry.mode if entry.action in ('BUY', 'SELL') else 'NONE',
            f"Position open ({side}) — manage only | live setup: {entry.reason}"
        )

    entry = evaluate_entry(snap, closed_snap, cfg, scalp_allowed, rule3_gate, rule4_gate)
    if already_entered_this_bar:
        return Signal(
            'MANAGE', entry.mode if entry.action in ('BUY', 'SELL') else 'NONE',
            f"Already entered this M15 — waiting next bar | live: {entry.reason}",
            sl=entry.sl, tp=entry.tp, trail_with_trend=entry.trail_with_trend,
        )
    return entry
