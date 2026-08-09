"""Pure indicator + signal logic for dual-mode ADX/DI/RSI strategy."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd

import config as cfg


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
    atr_strong = atr >= atr_mean  # momentum expansion (dumps/rallies)

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
        rsi=rsi,
        prev_rsi=prev_rsi,
        trend=trend,
        condition=condition,
        atr_weak=atr_weak,
        atr_strong=atr_strong,
    )


def _sl_tp_trend(side: str, entry: float, atr: float):
    atr = max(atr, 2.0)
    sl_d = atr * cfg.TREND_SL_ATR_MULT
    tp_d = atr * cfg.TREND_TP_ATR_MULT
    if side == 'BUY':
        return entry - sl_d, entry + tp_d
    return entry + sl_d, entry - tp_d


def _sl_tp_scalp(side: str, entry: float, atr: float):
    atr = max(atr, 2.0)
    sl_d = max(atr * cfg.SCALP_SL_ATR_MULT, 3.0)
    tp_d = cfg.SCALP_TP_POINTS
    if side == 'BUY':
        return entry - sl_d, entry + tp_d
    return entry + sl_d, entry - tp_d


def classify_side(side: str, snap: Snapshot):
    """Classify an immediate reversal re-entry (fired right after a COUNTER_SCALP
    gets stopped out) against the CURRENT big trend — not the mode of the scalp
    it followed. The opposite of a counter-scalp direction is, by definition,
    the WITH-trend direction, so this almost always comes back WITH_TREND
    (wider ATR-based SL/TP, trailing enabled) rather than another scalp.

    Returns (mode, sl, tp, trail_with_trend).
    """
    aligned = (
        (side == 'BUY' and snap.trend == 'TRENDING_UP')
        or (side == 'SELL' and snap.trend == 'TRENDING_DOWN')
    )
    if aligned:
        sl, tp = _sl_tp_trend(side, snap.close, snap.atr)
        return 'WITH_TREND', sl, tp, True
    sl, tp = _sl_tp_scalp(side, snap.close, snap.atr)
    return 'COUNTER_SCALP', sl, tp, False


def _bullish_candle(snap: Snapshot) -> bool:
    return snap.close > snap.open


def _bearish_candle(snap: Snapshot) -> bool:
    return snap.close < snap.open


def _rsi_buy_ceiling(snap: Snapshot) -> float:
    """Confirmed strong trend (high ADX) gets more RSI room — a persistent
    strong trend can keep RSI pinned near its extreme for a long stretch
    without that meaning exhaustion."""
    if snap.adx >= cfg.ADX_STRONG_TREND:
        return cfg.RSI_WITH_TREND_BUY_MAX_STRONG
    return cfg.RSI_WITH_TREND_BUY_MAX


def _rsi_sell_floor(snap: Snapshot) -> float:
    if snap.adx >= cfg.ADX_STRONG_TREND:
        return cfg.RSI_WITH_TREND_SELL_MIN_STRONG
    return cfg.RSI_WITH_TREND_SELL_MIN


def evaluate_flip(snap: Snapshot, has_buy: bool, has_sell: bool) -> Optional[Signal]:
    """Close opposite scalps and reverse into with-trend when momentum flips."""
    if snap.trend == 'TRENDING_UP' and has_sell:
        di_flip = snap.di_plus > snap.di_minus and snap.prev_di_plus <= snap.prev_di_minus
        di_strong = snap.di_plus > snap.di_minus and snap.di_plus > snap.prev_di_plus
        rsi_up = snap.rsi > snap.prev_rsi and snap.rsi >= 45
        adx_ok = snap.adx >= cfg.ADX_MIN
        if adx_ok and (di_flip or di_strong) and rsi_up:
            sl, tp = _sl_tp_trend('BUY', snap.close, snap.atr)
            return Signal(
                action='CLOSE_SELLS_THEN_BUY',
                mode='FLIP',
                reason=f"Flip UP: +DI {snap.di_plus:.1f}>-DI {snap.di_minus:.1f}, RSI {snap.rsi:.1f} rising",
                sl=sl,
                tp=tp,
                trail_with_trend=True,
            )

    if snap.trend == 'TRENDING_DOWN' and has_buy:
        di_flip = snap.di_minus > snap.di_plus and snap.prev_di_minus <= snap.prev_di_plus
        di_strong = snap.di_minus > snap.di_plus and snap.di_minus > snap.prev_di_minus
        rsi_down = snap.rsi < snap.prev_rsi and snap.rsi <= 55
        adx_ok = snap.adx >= cfg.ADX_MIN
        if adx_ok and (di_flip or di_strong) and rsi_down:
            sl, tp = _sl_tp_trend('SELL', snap.close, snap.atr)
            return Signal(
                action='CLOSE_BUYS_THEN_SELL',
                mode='FLIP',
                reason=f"Flip DOWN: -DI {snap.di_minus:.1f}>+DI {snap.di_plus:.1f}, RSI {snap.rsi:.1f} falling",
                sl=sl,
                tp=tp,
                trail_with_trend=True,
            )
    return None


def _skip_scalp_sell_reason(snap: Snapshot) -> str:
    """Explain why counter-trend SELL is not ready (trend UP)."""
    parts = []
    if not (snap.di_minus > snap.di_plus):
        parts.append(f"-DI({snap.di_minus:.1f}) not > +DI({snap.di_plus:.1f})")
    if not (snap.rsi < cfg.RSI_SCALP_SELL_MAX):
        parts.append(f"RSI({snap.rsi:.1f}) not < {cfg.RSI_SCALP_SELL_MAX}")
    if not snap.atr_strong:
        parts.append(f"ATR not strong ({snap.atr:.2f} < mean {snap.atr_mean:.2f})")
    return "; ".join(parts) if parts else "scalp conditions OK"


def _skip_scalp_buy_reason(snap: Snapshot) -> str:
    parts = []
    if not (snap.di_plus > snap.di_minus):
        parts.append(f"+DI({snap.di_plus:.1f}) not > -DI({snap.di_minus:.1f})")
    if not (snap.rsi > cfg.RSI_SCALP_BUY_MIN):
        parts.append(f"RSI({snap.rsi:.1f}) not > {cfg.RSI_SCALP_BUY_MIN}")
    if not snap.atr_strong:
        parts.append(f"ATR not strong ({snap.atr:.2f} < mean {snap.atr_mean:.2f})")
    return "; ".join(parts) if parts else "scalp conditions OK"


def _momentum_recovered(side: str, snap: Snapshot, momentum_gate: Optional[dict]) -> bool:
    """After a WITH_TREND SL, the "DI still > DI" check alone isn't enough —
    that comparison can stay nominally true while the DI value itself keeps
    fading (momentum genuinely dying), letting the bot re-enter the same
    losing direction next candle.

    Rolling check (not a frozen SL-time value): require this side's DI to be
    HIGHER than it was on the immediately PRECEDING candle — i.e. momentum is
    ticking up again right now, candle over candle. A fixed historical
    baseline (DI-at-stop-out) can take a whole session to reclaim if DI keeps
    grinding lower after the SL; a rolling comparison reacts the moment DI
    turns, so a genuine reversal isn't missed — at the cost of being looser
    (one up-tick is enough, even if DI is still objectively weak).
    """
    if not momentum_gate or momentum_gate.get('side') != side:
        return True
    # Must be a genuinely NEW candle since the SL — not just this gate's own
    # bar_time check, this replaces relying on the blanket last_bar_time/
    # already_entered_this_bar lock, which used to block EVERY entry type
    # (including an unrelated, freshly-qualifying COUNTER_SCALP on the other
    # side) for the rest of that candle. This gate only ever touches the
    # matching WITH_TREND side — scalp paths never check it at all.
    if snap.bar_time == momentum_gate.get('bar_time'):
        return False
    if side == 'BUY':
        return snap.di_plus > snap.prev_di_plus
    return snap.di_minus > snap.prev_di_minus


def _skip_trend_buy_reason(snap: Snapshot, momentum_gate: Optional[dict] = None) -> str:
    parts = []
    if not (snap.di_plus > snap.di_minus):
        parts.append(f"+DI({snap.di_plus:.1f}) <= -DI({snap.di_minus:.1f})")
    ceiling = _rsi_buy_ceiling(snap)
    if snap.rsi < 40 or snap.rsi > ceiling:
        parts.append(f"RSI({snap.rsi:.1f}) outside 40–{ceiling:.0f} (ADX {snap.adx:.1f})")
    if not _bullish_candle(snap):
        parts.append("closed candle not green")
    if not _momentum_recovered('BUY', snap, momentum_gate):
        if snap.bar_time == momentum_gate.get('bar_time'):
            parts.append("same candle as the SL — waiting for next candle")
        else:
            parts.append(f"+DI({snap.di_plus:.1f}) still not above prior candle ({snap.prev_di_plus:.1f})")
    return "; ".join(parts) if parts else "trend BUY conditions OK"


def _skip_trend_sell_reason(snap: Snapshot, momentum_gate: Optional[dict] = None) -> str:
    parts = []
    if not (snap.di_minus > snap.di_plus):
        parts.append(f"-DI({snap.di_minus:.1f}) <= +DI({snap.di_plus:.1f})")
    floor = _rsi_sell_floor(snap)
    if snap.rsi < floor or snap.rsi > 60:
        parts.append(f"RSI({snap.rsi:.1f}) outside {floor:.0f}–60 (ADX {snap.adx:.1f})")
    if not _bearish_candle(snap):
        parts.append("closed candle not red")
    if not _momentum_recovered('SELL', snap, momentum_gate):
        if snap.bar_time == momentum_gate.get('bar_time'):
            parts.append("same candle as the SL — waiting for next candle")
        else:
            parts.append(f"-DI({snap.di_minus:.1f}) still not above prior candle ({snap.prev_di_minus:.1f})")
    return "; ".join(parts) if parts else "trend SELL conditions OK"


def evaluate_entry(snap: Snapshot, scalp_allowed: bool = True, momentum_gate: Optional[dict] = None) -> Signal:
    """New entry when flat. Prefer counter-scalp when short-term opposes big trend.

    scalp_allowed: False once a counter-scalp has already been fired for the
    current DI regime (see bot_runner). Prevents repeatedly re-entering the
    same counter-trend scalp on every stop-out while -DI/+DI stays lopsided —
    DI is lagging, so the condition can stay true long after price has already
    turned back with the big trend. A fresh DI cross re-arms it.

    momentum_gate: {'side': 'BUY'|'SELL'} set right after a WITH_TREND SL,
    requiring that side's DI to be rising candle-over-candle (rolling, not a
    frozen SL-time value — see _momentum_recovered) before the SAME direction
    can be taken again. Prevents "DI still nominally ahead but fading"
    re-entries into the same losing move on the very next candle.
    """
    if snap.trend == 'NEUTRAL':
        return Signal('HOLD', 'NONE', 'SKIP: Trend NEUTRAL — wait for EMA cross')

    if snap.adx < cfg.ADX_MIN:
        return Signal('HOLD', 'NONE', f'SKIP: ADX {snap.adx:.1f} < {cfg.ADX_MIN}')

    # --- Counter-trend scalp (UP big trend, short-term sell pressure) ---
    # ATR STRONG = real dump/rally energy (not quiet chop). Weak-ATR filter was blocking good sells.
    if snap.trend == 'TRENDING_UP':
        scalp_ok = (
            snap.di_minus > snap.di_plus
            and snap.rsi < cfg.RSI_SCALP_SELL_MAX
            and snap.atr_strong
            and scalp_allowed
        )
        if scalp_ok:
            sl, tp = _sl_tp_scalp('SELL', snap.close, snap.atr)
            return Signal(
                action='SELL',
                mode='COUNTER_SCALP',
                reason=(
                    f"Scalp SELL: trend UP but -DI {snap.di_minus:.1f}>+DI {snap.di_plus:.1f}, "
                    f"RSI {snap.rsi:.1f}<{cfg.RSI_SCALP_SELL_MAX}, ATR strong "
                    f"({snap.atr:.2f}>={snap.atr_mean:.2f})"
                ),
                sl=sl,
                tp=tp,
                trail_with_trend=False,
            )

        # With-trend BUY
        trend_ok = (
            snap.di_plus > snap.di_minus
            and snap.rsi <= _rsi_buy_ceiling(snap)
            and snap.rsi >= 40
            and _bullish_candle(snap)
            and _momentum_recovered('BUY', snap, momentum_gate)
        )
        if trend_ok:
            sl, tp = _sl_tp_trend('BUY', snap.close, snap.atr)
            return Signal(
                action='BUY',
                mode='WITH_TREND',
                reason=f"With-trend BUY: +DI {snap.di_plus:.1f}>-DI {snap.di_minus:.1f}, RSI {snap.rsi:.1f}, green candle",
                sl=sl,
                tp=tp,
                trail_with_trend=True,
            )
        skip = _skip_scalp_sell_reason(snap)
        if not scalp_allowed:
            skip += "; already scalped this DI regime"
        return Signal(
            'HOLD', 'NONE',
            f"SKIP UP: scalp SELL blocked [{skip}] | "
            f"trend BUY blocked [{_skip_trend_buy_reason(snap, momentum_gate)}]"
        )

    # --- TRENDING_DOWN ---
    if snap.trend == 'TRENDING_DOWN':
        scalp_ok = (
            snap.di_plus > snap.di_minus
            and snap.rsi > cfg.RSI_SCALP_BUY_MIN
            and snap.atr_strong
            and scalp_allowed
        )
        if scalp_ok:
            sl, tp = _sl_tp_scalp('BUY', snap.close, snap.atr)
            return Signal(
                action='BUY',
                mode='COUNTER_SCALP',
                reason=(
                    f"Scalp BUY: trend DOWN but +DI {snap.di_plus:.1f}>-DI {snap.di_minus:.1f}, "
                    f"RSI {snap.rsi:.1f}>{cfg.RSI_SCALP_BUY_MIN}, ATR strong "
                    f"({snap.atr:.2f}>={snap.atr_mean:.2f})"
                ),
                sl=sl,
                tp=tp,
                trail_with_trend=False,
            )

        trend_ok = (
            snap.di_minus > snap.di_plus
            and snap.rsi >= _rsi_sell_floor(snap)
            and snap.rsi <= 60
            and _bearish_candle(snap)
            and _momentum_recovered('SELL', snap, momentum_gate)
        )
        if trend_ok:
            sl, tp = _sl_tp_trend('SELL', snap.close, snap.atr)
            return Signal(
                action='SELL',
                mode='WITH_TREND',
                reason=f"With-trend SELL: -DI {snap.di_minus:.1f}>+DI {snap.di_plus:.1f}, RSI {snap.rsi:.1f}, red candle",
                sl=sl,
                tp=tp,
                trail_with_trend=True,
            )
        skip = _skip_scalp_buy_reason(snap)
        if not scalp_allowed:
            skip += "; already scalped this DI regime"
        return Signal(
            'HOLD', 'NONE',
            f"SKIP DOWN: scalp BUY blocked [{skip}] | "
            f"trend SELL blocked [{_skip_trend_sell_reason(snap, momentum_gate)}]"
        )

    return Signal('HOLD', 'NONE', 'SKIP: No signal')


def decide(snap: Snapshot, has_buy: bool, has_sell: bool, already_entered_this_bar: bool,
           scalp_allowed: bool = True, momentum_gate: Optional[dict] = None) -> Signal:
    """Live-bar decisions. already_entered_this_bar only blocks a second entry, not reason updates."""
    flip = evaluate_flip(snap, has_buy, has_sell)
    if flip:
        if already_entered_this_bar and not (has_buy or has_sell):
            # rare: flipped and flat but already entered earlier this bar
            return Signal('MANAGE', 'FLIP', f"Already acted this M15 | {flip.reason}",
                          sl=flip.sl, tp=flip.tp, trail_with_trend=True)
        return flip

    if has_buy or has_sell:
        side = "BUY" if has_buy else "SELL"
        entry = evaluate_entry(snap, scalp_allowed, momentum_gate)
        return Signal(
            'MANAGE', entry.mode if entry.action in ('BUY', 'SELL') else 'NONE',
            f"Position open ({side}) — manage only | live setup: {entry.reason}"
        )

    entry = evaluate_entry(snap, scalp_allowed, momentum_gate)
    if already_entered_this_bar:
        return Signal(
            'MANAGE', entry.mode if entry.action in ('BUY', 'SELL') else 'NONE',
            f"Already entered this M15 — waiting next bar | live: {entry.reason}",
            sl=entry.sl, tp=entry.tp, trail_with_trend=entry.trail_with_trend,
        )
    return entry
