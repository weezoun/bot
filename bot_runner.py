"""MT5 polling loop + shared BotState for the Flask dashboard."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timedelta
from random import randrange
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd

import config as cfg
from strategy import calculate_indicators, build_snapshot, decide, classify_side, Signal


class BotState:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.connected = False
        self.last_error = ""
        self.attempt = 0
        self.symbol = cfg.SYMBOL
        self.lot = cfg.LOT
        self.snapshot = {}
        self.live = {}
        self.last_signal = {}
        self.last_reason = ""
        self.mode = "NONE"
        self.positions = []
        self.account = {}
        self.stats = {}
        self.logs = deque(maxlen=cfg.LOG_MAX)
        self.last_bar_time: Optional[int] = None  # forming bar time we already entered on
        self.last_logged_reason: str = ""
        self.updated_at: str = ""
        self.position_modes = {}  # ticket -> WITH_TREND | COUNTER_SCALP
        self.position_snapshot = {}  # ticket -> last known {sl, tp, type, price_open, profit, mode}
        self.position_open_info = {}  # ticket -> {reason, opened_at} captured at entry time
        self.trade_history = deque(maxlen=100)  # closed trades, most recent first
        self.di_regime: Optional[str] = None  # 'PLUS' | 'MINUS' — which DI is currently dominant
        self.scalp_armed: bool = True  # one counter-scalp attempt per DI regime (re-armed on fresh cross)
        self.scalp_reversal_used: bool = False  # one immediate reversal-on-SL attempt per DI regime
        self.momentum_gate: Optional[dict] = None  # {'side'} after a WITH_TREND SL — blocks
        # same-direction re-entry until that side's DI rises candle-over-candle again
        self.scalp_reversal_di = None  # {'side','di_at_sl'} — scalp's DI at the moment _reverse_scalp
        # fired; consumed once the reversal trade itself closes (see _classify_and_record_close)
        self.scalp_rearm_gate = None  # {'side','benchmark','rise_streak','last_bar_time'} — active after
        # a scalp AND its reversal have both been stopped out; re-arms scalp_armed early (see _check_scalp_rearm)

    def log(self, msg: str):
        line = f"{datetime.now().strftime('%H:%M:%S')} | {msg}"
        with self.lock:
            self.logs.appendleft(line)
        print(line)

    def snapshot_view(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "connected": self.connected,
                "last_error": self.last_error,
                "attempt": self.attempt,
                "symbol": self.symbol,
                "lot": self.lot,
                "snapshot": dict(self.snapshot),
                "live": dict(self.live),
                "last_signal": dict(self.last_signal),
                "last_reason": self.last_reason,
                "mode": self.mode,
                "positions": list(self.positions),
                "account": dict(self.account),
                "stats": dict(self.stats),
                "logs": list(self.logs)[:80],
                "trade_history": list(self.trade_history)[:50],
                "updated_at": self.updated_at,
            }


state = BotState()
_stop_event = threading.Event()
_thread: Optional[threading.Thread] = None


def connect_mt5() -> bool:
    if not mt5.initialize():
        state.last_error = f"initialize failed: {mt5.last_error()}"
        state.connected = False
        return False
    ok = mt5.login(cfg.MT5_LOGIN, password=cfg.MT5_PASSWORD, server=cfg.MT5_SERVER)
    if not ok:
        state.last_error = f"login failed: {mt5.last_error()}"
        state.connected = False
        return False
    state.connected = True
    state.last_error = ""
    state.log("Connected to MT5")
    return True


def _refresh_account():
    info = mt5.account_info()
    if info is None:
        return
    with state.lock:
        state.account = {
            "login": info.login,
            "balance": round(info.balance, 2),
            "equity": round(info.equity, 2),
            "margin": round(info.margin, 2),
            "profit": round(info.profit, 2),
        }


def _refresh_positions():
    positions = mt5.positions_get(symbol=cfg.SYMBOL) or []
    rows = []
    for p in positions:
        rows.append({
            "ticket": p.ticket,
            "type": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
            "volume": p.volume,
            "price_open": p.price_open,
            "sl": p.sl,
            "tp": p.tp,
            "profit": round(p.profit, 2),
            "mode": state.position_modes.get(p.ticket, "?"),
        })
        # Keep the latest known state for each open ticket — used to classify
        # the close (win/loss, SL-side vs TP-side) the instant it disappears,
        # without waiting on mt5.history_deals_get() (see _classify_and_record_close).
        state.position_snapshot[p.ticket] = {
            "sl": p.sl, "tp": p.tp, "type": p.type,
            "price_open": p.price_open, "profit": p.profit,
            "mode": state.position_modes.get(p.ticket, "?"),
        }
    # drop closed tickets from mode map
    open_tickets = {p.ticket for p in positions}
    state.position_modes = {t: m for t, m in state.position_modes.items() if t in open_tickets}
    with state.lock:
        state.positions = rows
    return positions


_EMPTY_STATS = {
    "total": 0, "wins": 0, "losses": 0, "profit": 0, "win_rate": 0,
    "buy_trades": 0, "sell_trades": 0,
}


def _refresh_stats():
    end = datetime.now()
    start = end - timedelta(days=30)
    deals = mt5.history_deals_get(start, end)
    if not deals:
        with state.lock:
            state.stats = dict(_EMPTY_STATS)
        return
    df = pd.DataFrame(list(deals), columns=deals[0]._asdict().keys())
    # Only real trade closes (exclude balance/credit/deposit noise)
    if 'entry' in df.columns:
        df = df[df['entry'].isin([1])]  # DEAL_ENTRY_OUT
    if 'symbol' in df.columns:
        df = df[(df['symbol'] == cfg.SYMBOL) | (df['symbol'] == '')]
    df = df[df['profit'] != 0]
    if df.empty:
        with state.lock:
            state.stats = dict(_EMPTY_STATS)
        return
    wins = int((df['profit'] > 0).sum())
    losses = int((df['profit'] < 0).sum())
    total = wins + losses
    profit = float(df['profit'].sum())
    # The closing deal's type is the OPPOSITE of the position it closed
    # (you SELL to close a BUY, and BUY to close a SELL).
    buy_trades = int((df['type'] == mt5.DEAL_TYPE_SELL).sum()) if 'type' in df.columns else 0
    sell_trades = int((df['type'] == mt5.DEAL_TYPE_BUY).sum()) if 'type' in df.columns else 0
    with state.lock:
        state.stats = {
            "total": total,
            "wins": wins,
            "losses": losses,
            "profit": round(profit, 2),
            "win_rate": round(wins / total * 100, 2) if total else 0,
            "buy_trades": buy_trades,
            "sell_trades": sell_trades,
        }


def _record_close_stats(side: str, profit: float):
    with state.lock:
        st = dict(state.stats) if state.stats else dict(_EMPTY_STATS)
        if profit != 0:
            st["total"] = st.get("total", 0) + 1
            if profit > 0:
                st["wins"] = st.get("wins", 0) + 1
            else:
                st["losses"] = st.get("losses", 0) + 1
        st["profit"] = round(st.get("profit", 0) + profit, 2)
        st["buy_trades"] = st.get("buy_trades", 0) + (1 if side == "BUY" else 0)
        st["sell_trades"] = st.get("sell_trades", 0) + (1 if side == "SELL" else 0)
        total = st.get("total", 0)
        st["win_rate"] = round(st.get("wins", 0) / total * 100, 2) if total else 0
        state.stats = st


def _classify_and_record_close(ticket: int, live_snap, bid: Optional[float], ask: Optional[float]):
    """Runs the instant a tracked ticket disappears from positions_get().

    mt5.history_deals_get() can lag the terminal's own live state by a long
    time on this setup (observed: hours) — a trade that already shows closed
    with profit in the MT5 terminal's own History tab was still invisible to
    history_deals_get() 3+ hours later. So we don't use it for win/loss stats
    or SL-handling at all: everything here is derived from the position's own
    last known SL/TP/profit (from positions_get(), which stays accurate to
    the tick) plus the current bid/ask.

    What happens on an SL-side close depends on how the trade was opened:
      COUNTER_SCALP -> try the opposite side immediately (capped at one
        attempt per DI regime by scalp_reversal_used).
      WITH_TREND (or unknown) -> hold entries until the next candle, then
        let decide()/evaluate_entry() re-evaluate fresh (existing behavior).
    """
    snap = state.position_snapshot.pop(ticket, None)
    if snap is None:
        return
    profit = snap["profit"]
    side = "BUY" if snap["type"] == mt5.ORDER_TYPE_BUY else "SELL"
    mode = snap.get("mode", "?")
    price = bid if side == "BUY" else ask
    sl, tp = snap["sl"], snap["tp"]
    # Which level was price nearer to when the position vanished? That's the
    # one that most likely triggered the close (works for original AND
    # trailing-adjusted SL, since trailing only moves the sl field).
    if price is not None and sl and tp:
        hit_sl = abs(price - sl) <= abs(price - tp)
    elif sl:
        hit_sl = True
    else:
        hit_sl = False

    _record_close_stats(side, profit)
    _push_trade_history(ticket, side, snap, profit, "SL" if hit_sl else "TP")
    state.log(f"{side} closed, profit {profit:+.2f} ({'SL-side' if hit_sl else 'TP-side'}, {mode})")

    if not hit_sl:
        if mode == 'COUNTER_SCALP':
            _rearm_scalp_if_continuing(side, live_snap)
        elif mode == 'WITH_TREND' and state.scalp_reversal_di and state.scalp_reversal_di['side'] != side:
            # This WITH_TREND position was the immediate reversal of an earlier
            # scalp SL, and it won (TP) — no need for the re-arm benchmark below.
            state.scalp_reversal_di = None
        return

    if mode == 'COUNTER_SCALP':
        _reverse_scalp(side, live_snap)
    elif cfg.SL_COOLDOWN_UNTIL_NEXT_CANDLE:
        # Deliberately NOT using state.last_bar_time here — that's a blanket
        # lock that blocks EVERY entry type in decide() for the rest of this
        # candle, which was wrongly also blocking a fresh, independently-
        # qualifying COUNTER_SCALP on the other side. momentum_gate is scoped
        # to just this side's WITH_TREND path: needs a genuinely new candle
        # AND that side's DI rising candle-over-candle (see
        # strategy._momentum_recovered) before re-entering the SAME side.
        # Scalp opportunities stay completely unaffected.
        state.momentum_gate = {'side': side, 'bar_time': live_snap.bar_time}
        state.log(
            f"WITH_TREND SL — holding {side} entries until next candle + "
            f"{'+DI' if side == 'BUY' else '-DI'} rising candle-over-candle "
            f"(scalps on the other side still allowed)"
        )

        # If this WITH_TREND position was the immediate reversal of an earlier
        # scalp SL, and it ALSO just got stopped out (both attempts failed),
        # set up the faster scalp re-arm: benchmark = the stronger of the two
        # failure-point DI readings. Crossing it re-arms immediately; short of
        # that, 2 rising candles in a row also re-arms (see _check_scalp_rearm).
        # This is IN ADDITION to the existing regime-flip re-arm — neither one
        # replaces the other.
        pending = state.scalp_reversal_di
        if pending and pending['side'] != side:
            scalp_side = pending['side']
            di_at_reversal_sl = _relevant_di(scalp_side, live_snap)
            benchmark = max(pending['di_at_sl'], di_at_reversal_sl)
            state.scalp_rearm_gate = {
                'side': scalp_side, 'benchmark': benchmark,
                'rise_streak': 0, 'last_bar_time': None,
            }
            state.scalp_reversal_di = None
            state.log(
                f"Scalp + reversal both SL'd — {scalp_side} scalp re-arms early if DI "
                f"crosses {benchmark:.1f}, or 2 rising candles in a row"
            )


def _relevant_di(side: str, live_snap) -> float:
    """The DI value that matters for a given scalp direction: -DI for SELL, +DI for BUY."""
    return live_snap.di_minus if side == 'SELL' else live_snap.di_plus


def _check_scalp_rearm(live_snap):
    """Runs every tick while state.scalp_rearm_gate is active (set in
    _classify_and_record_close after a scalp AND its reversal have both been
    stopped out). Two independent ways to re-arm — whichever comes first:

      1. Fast: DI crosses above the benchmark (the stronger of the two
         failure-point DI readings) — high-confidence, checked live, no wait.
      2. Slower: DI rises candle-over-candle for 2 candles in a row — checked
         once per new candle (not intra-candle noise).

    This is purely additive — the existing regime-flip re-arm still works
    exactly as before and can also fire independently at any time.
    """
    gate = state.scalp_rearm_gate
    if not gate:
        return
    side = gate['side']
    current = _relevant_di(side, live_snap)

    if current > gate['benchmark']:
        state.scalp_armed = True
        state.scalp_rearm_gate = None
        state.log(f"Scalp re-armed ({side}) — DI {current:.1f} crossed benchmark {gate['benchmark']:.1f}")
        return

    if live_snap.bar_time != gate['last_bar_time']:
        prev = live_snap.prev_di_minus if side == 'SELL' else live_snap.prev_di_plus
        gate['rise_streak'] = gate['rise_streak'] + 1 if current > prev else 0
        gate['last_bar_time'] = live_snap.bar_time
        if gate['rise_streak'] >= 2:
            state.scalp_armed = True
            state.scalp_rearm_gate = None
            state.log(f"Scalp re-armed ({side}) — DI rising 2 candles in a row")


def _rearm_scalp_if_continuing(side: str, live_snap):
    """A COUNTER_SCALP hit TP (a win) — this is NOT the SL case, so the
    "one scalp per DI regime" lock (scalp_armed disarmed at open, only
    re-armed on a fresh DI cross) doesn't belong here at all. Instead: allow
    another same-direction scalp right away as long as that side's DI is
    still confirming — not fading vs the prior candle. If DI has started
    fading, leave it disarmed (falls through to normal evaluate_entry()) so
    the bot doesn't chase a move that's already turning.
    """
    current = live_snap.di_minus if side == 'SELL' else live_snap.di_plus
    prev = live_snap.prev_di_minus if side == 'SELL' else live_snap.prev_di_plus
    label = '-DI' if side == 'SELL' else '+DI'
    if current >= prev:
        state.scalp_armed = True
        state.log(f"Scalp TP ({side}) — {label} still confirming ({current:.1f} >= {prev:.1f}) — re-armed for another {side} scalp")
    else:
        state.log(f"Scalp TP ({side}) — {label} fading ({current:.1f} < {prev:.1f}) — not re-arming, waiting for a fresh signal")


def _reverse_scalp(closed_side: str, live_snap):
    """A COUNTER_SCALP just got stopped out — immediately try the opposite
    side once. Capped at one attempt per DI regime (scalp_reversal_used) so
    it can't chain into repeated whipsaw losses; a fresh DI cross resets it,
    same as scalp_armed. The opposite of a counter-scalp direction is by
    definition the WITH-trend direction, so classify_side() will almost
    always come back WITH_TREND here (wider SL/TP, trailing) — not another
    scalp — which then follows the normal candle-wait rule if it too is
    stopped out.
    """
    if state.scalp_reversal_used:
        state.log("Scalp SL — reversal already used this DI regime, waiting for a fresh cross/signal")
        return
    if not should_take_trade():
        return
    opposite = 'SELL' if closed_side == 'BUY' else 'BUY'
    mode, sl, tp, _trail = classify_side(opposite, live_snap)
    state.scalp_reversal_used = True
    state.momentum_gate = None  # a fresh entry just opened — old gate is moot
    # Remember the scalp's own DI right now, at its SL — needed later if the
    # reversal ALSO gets stopped out, to compute the re-arm benchmark (see
    # _classify_and_record_close / _check_scalp_rearm).
    state.scalp_reversal_di = {'side': closed_side, 'di_at_sl': _relevant_di(closed_side, live_snap)}
    if mode == 'COUNTER_SCALP':
        state.scalp_armed = False
    state.last_bar_time = live_snap.bar_time  # this bar already acted on — decide() should just MANAGE
    state.log(f"Scalp SL -> immediately opening opposite {opposite} [{mode}]")
    send_order(
        opposite, sl, tp, f'SCALP_REV_{mode}', mode,
        f"Immediate reversal after COUNTER_SCALP {closed_side} stopped out",
    )


def _push_trade_history(ticket: int, side: str, snap: dict, profit: float, close_reason: str):
    open_info = state.position_open_info.pop(ticket, {})
    entry = {
        "ticket": ticket,
        "side": side,
        "mode": snap.get("mode", "?"),
        "opened_at": open_info.get("opened_at", "—"),
        "closed_at": datetime.now().strftime("%H:%M:%S"),
        "price_open": snap.get("price_open"),
        "sl": snap.get("sl"),
        "tp": snap.get("tp"),
        "profit": round(profit, 2),
        "close_reason": close_reason,
        "open_reason": open_info.get("reason", ""),
    }
    with state.lock:
        state.trade_history.appendleft(entry)


def should_take_trade() -> bool:
    info = mt5.account_info()
    if info is None or info.equity <= 0:
        return False
    if info.margin / info.equity <= 0.1:
        return True
    state.log("Insufficient margin room")
    return False


def send_order(side: str, sl: float, tp: float, comment: str, mode: str, reason: str = "") -> Optional[int]:
    tick = mt5.symbol_info_tick(cfg.SYMBOL)
    if tick is None:
        state.log("No tick data")
        return None
    order_type = mt5.ORDER_TYPE_BUY if side == 'BUY' else mt5.ORDER_TYPE_SELL
    price = tick.ask if side == 'BUY' else tick.bid
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": cfg.SYMBOL,
        "volume": cfg.LOT,
        "type": order_type,
        "price": price,
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "magic": randrange(1000000),
        "comment": comment[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    result = mt5.order_send(request)
    if result is None:
        state.log(f"Order failed: {mt5.last_error()}")
        return None
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        state.log(f"Order error {result.retcode}: {result.comment}")
        return None
    state.log(f"{side} placed order={result.order} SL={sl:.2f} TP={tp:.2f} ({comment})")
    # Map mode onto the newest open position ticket
    time.sleep(0.15)
    positions = mt5.positions_get(symbol=cfg.SYMBOL) or []
    side_type = mt5.ORDER_TYPE_BUY if side == 'BUY' else mt5.ORDER_TYPE_SELL
    candidates = [p for p in positions if p.type == side_type and p.ticket not in state.position_modes]
    if candidates:
        newest = max(candidates, key=lambda p: p.time)
        state.position_modes[newest.ticket] = mode
        state.position_open_info[newest.ticket] = {
            "reason": reason,
            "opened_at": datetime.fromtimestamp(newest.time).strftime("%H:%M:%S"),
        }
        return newest.ticket
    return result.order


def close_positions_of_type(order_type: int) -> int:
    positions = mt5.positions_get(symbol=cfg.SYMBOL) or []
    closed = 0
    tick = mt5.symbol_info_tick(cfg.SYMBOL)
    if tick is None:
        return 0
    for p in positions:
        if p.type != order_type:
            continue
        close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": cfg.SYMBOL,
            "volume": p.volume,
            "type": close_type,
            "position": p.ticket,
            "price": price,
            "magic": randrange(1000000),
            "comment": "FlipClose",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            closed += 1
            side = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
            snap = {
                "sl": p.sl, "tp": p.tp, "price_open": p.price_open,
                "mode": state.position_modes.get(p.ticket, "?"),
            }
            _record_close_stats(side, p.profit)
            _push_trade_history(p.ticket, side, snap, p.profit, "FLIP")
            state.log(f"Closed ticket {p.ticket} (flip), profit {p.profit:+.2f}")
            state.position_modes.pop(p.ticket, None)
            state.position_snapshot.pop(p.ticket, None)
        else:
            state.log(f"Close failed {p.ticket}: {getattr(result, 'comment', mt5.last_error())}")
    return closed


def trail_with_trend_positions(atr: float):
    atr = max(atr, 2.0)
    positions = mt5.positions_get(symbol=cfg.SYMBOL) or []
    tick = mt5.symbol_info_tick(cfg.SYMBOL)
    if tick is None:
        return
    for p in positions:
        mode = state.position_modes.get(p.ticket, 'WITH_TREND')
        if mode != 'WITH_TREND':
            continue  # scalps: no aggressive trail
        if p.type == mt5.ORDER_TYPE_BUY:
            profit_pts = tick.bid - p.price_open
            if profit_pts >= atr:
                nsl = max(tick.bid - atr * 0.8, p.price_open + atr * 0.2)
                if p.sl == 0 or nsl > p.sl:
                    _modify_sltp(p.ticket, nsl, p.tp)
        else:
            profit_pts = p.price_open - tick.ask
            if profit_pts >= atr:
                nsl = min(tick.ask + atr * 0.8, p.price_open - atr * 0.2)
                if p.sl == 0 or nsl < p.sl:
                    _modify_sltp(p.ticket, nsl, p.tp)


def _modify_sltp(ticket: int, sl: float, tp: float):
    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": cfg.SYMBOL,
        "position": ticket,
        "sl": round(sl, 2),
        "tp": tp,
        "comment": "Trail",
    }
    result = mt5.order_send(req)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        state.log(f"Trail SL ticket={ticket} -> {sl:.2f}")


def execute_signal(sig: Signal):
    if sig.action == 'HOLD' or sig.action == 'MANAGE':
        return

    if sig.action == 'CLOSE_SELLS_THEN_BUY':
        close_positions_of_type(mt5.ORDER_TYPE_SELL)
        time.sleep(0.3)
        if should_take_trade():
            send_order('BUY', sig.sl, sig.tp, 'FLIP_BUY', 'WITH_TREND', sig.reason)
        return

    if sig.action == 'CLOSE_BUYS_THEN_SELL':
        close_positions_of_type(mt5.ORDER_TYPE_BUY)
        time.sleep(0.3)
        if should_take_trade():
            send_order('SELL', sig.sl, sig.tp, 'FLIP_SELL', 'WITH_TREND', sig.reason)
        return

    if sig.action in ('BUY', 'SELL') and sig.sl is not None and sig.tp is not None:
        if not should_take_trade():
            return
        comment = sig.mode[:20]
        send_order(sig.action, sig.sl, sig.tp, comment, sig.mode, sig.reason)


def _fetch_rates() -> Optional[pd.DataFrame]:
    rates = mt5.copy_rates_from_pos(cfg.SYMBOL, mt5.TIMEFRAME_M15, 0, cfg.TIMEFRAME_BARS)
    if rates is None or len(rates) < 50:
        return None
    df = pd.DataFrame(rates)
    df.columns = ['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume']
    return df


def bot_tick():
    state.attempt += 1
    if not state.connected and not connect_mt5():
        return

    tick = mt5.symbol_info_tick(cfg.SYMBOL)
    live = {}
    if tick is not None:
        live = {
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "mid": round((tick.bid + tick.ask) / 2, 2),
            "spread": round(tick.ask - tick.bid, 2),
            "time": datetime.fromtimestamp(tick.time).strftime("%H:%M:%S") if tick.time else "",
        }

    df = _fetch_rates()
    if df is None:
        state.log("Not enough rate data")
        with state.lock:
            state.live = live
            state.updated_at = datetime.now().strftime("%H:%M:%S")
        return

    # Live forming-bar preview: patch current bar with live mid so RSI/EMA move on dashboard
    data_live = df.copy()
    if tick is not None and len(data_live):
        mid = (tick.bid + tick.ask) / 2.0
        idx = data_live.index[-1]
        data_live.at[idx, 'close'] = mid
        data_live.at[idx, 'high'] = max(float(data_live.at[idx, 'high']), mid)
        data_live.at[idx, 'low'] = min(float(data_live.at[idx, 'low']), mid)

    data_closed = calculate_indicators(df)
    data_preview = calculate_indicators(data_live)
    closed_snap = build_snapshot(data_closed, bar_offset=-2)
    # Decisions + dashboard use the SAME live forming bar
    live_snap = build_snapshot(data_preview, bar_offset=-1)
    if live_snap is None:
        return
    if closed_snap is None:
        closed_snap = live_snap

    # position_snapshot (not position_modes) is the "previously open" set —
    # it's populated for ANY open ticket unconditionally (see _refresh_positions),
    # including ones that were already open before this process started (e.g.
    # after a restart). position_modes only has tickets THIS process opened via
    # send_order(), so using it here silently missed closes for pre-existing
    # positions (their close never got detected at all).
    prev_tracked_tickets = set(state.position_snapshot.keys())
    positions = _refresh_positions()
    current_tickets = {p.ticket for p in positions}
    closed_tickets = prev_tracked_tickets - current_tickets
    for ticket in closed_tickets:
        _classify_and_record_close(ticket, live_snap, live.get('bid'), live.get('ask'))

    has_buy = any(p.type == mt5.ORDER_TYPE_BUY for p in positions)
    has_sell = any(p.type == mt5.ORDER_TYPE_SELL for p in positions)

    # Track which DI is dominant. A regime change (i.e. a fresh cross) re-arms
    # the counter-scalp so it can only fire once per regime instead of on
    # every stop-out while -DI/+DI stays lopsided (DI is a lagging indicator).
    if live_snap.di_plus > live_snap.di_minus:
        regime = 'PLUS'
    elif live_snap.di_minus > live_snap.di_plus:
        regime = 'MINUS'
    else:
        regime = state.di_regime
    if regime != state.di_regime:
        state.di_regime = regime
        state.scalp_armed = True
        state.scalp_reversal_used = False
        state.scalp_rearm_gate = None  # regime flip already re-armed it — this gate is moot
        state.scalp_reversal_di = None

    _check_scalp_rearm(live_snap)

    # Only block a second ENTRY on the same forming M15 — reasons always from live
    already_entered = (
        state.last_bar_time is not None
        and live_snap.bar_time == state.last_bar_time
    )
    sig = decide(live_snap, has_buy, has_sell, already_entered, state.scalp_armed, state.momentum_gate)

    display = live_snap.to_dict()
    display['signal_close'] = closed_snap.close
    display['signal_bar_time'] = closed_snap.bar_time
    display['decision_source'] = 'LIVE_FORMING_M15'

    with state.lock:
        state.snapshot = display
        state.live = live
        state.last_signal = sig.to_dict()
        state.last_reason = sig.reason
        state.mode = sig.mode
        state.updated_at = datetime.now().strftime("%H:%M:%S")

    if sig.reason != state.last_logged_reason:
        state.log(sig.reason)
        state.last_logged_reason = sig.reason

    if sig.action in ('BUY', 'SELL', 'CLOSE_SELLS_THEN_BUY', 'CLOSE_BUYS_THEN_SELL'):
        before = len(mt5.positions_get(symbol=cfg.SYMBOL) or [])
        execute_signal(sig)
        after = len(mt5.positions_get(symbol=cfg.SYMBOL) or [])
        # Mark forming bar only if we opened/flipped something
        if after != before or sig.action.startswith('CLOSE'):
            state.last_bar_time = live_snap.bar_time
        if after > before:
            state.momentum_gate = None  # a fresh entry just opened — old gate is moot
            if sig.mode == 'COUNTER_SCALP':
                state.scalp_armed = False

    trail_with_trend_positions(live_snap.atr)
    _refresh_account()


def _loop():
    state.log("Bot loop started")
    connect_mt5()
    if state.connected:
        # One-time baseline from broker history at startup (best-effort — may
        # itself lag, see _classify_and_record_close). Every trade closed
        # DURING this run updates state.stats locally and immediately from then on.
        _refresh_stats()
    while not _stop_event.is_set():
        if not state.running:
            time.sleep(0.5)
            continue
        try:
            bot_tick()
        except Exception as e:
            state.last_error = str(e)
            state.log(f"Error: {e}")
            time.sleep(cfg.POLL_SECONDS)
            continue
        time.sleep(cfg.POLL_SECONDS)
    state.log("Bot loop stopped")


def start_bot():
    global _thread
    with state.lock:
        state.running = True
    _stop_event.clear()
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, daemon=True)
        _thread.start()
    state.log("Bot marked RUNNING")


def stop_bot():
    with state.lock:
        state.running = False
    state.log("Bot marked STOPPED (thread idle)")
