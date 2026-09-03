"""MT5 polling loop + shared BotState — now class-based (SymbolBot) so the
same trading logic can run for multiple symbols at once, each with its own
state and thresholds. app.py instantiates one SymbolBot per entry in
config.SYMBOLS and starts them all.

MT5's own connection (mt5.initialize()/mt5.login()) is a single session to
the terminal, shared by every symbol — connect_mt5() is a free function, not
a per-bot method, and only needs to be called once.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from random import randrange
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd

import config as cfg
import trade_store
from strategy import (
    calculate_indicators, build_snapshot, decide, classify_side, Signal,
    _sl_tp_scalp, _sl_tp_reversal, _sl_tp_trend, _bullish_candle, _bearish_candle, _momentum_recovered,
    _rsi_buy_ceiling, _rsi_sell_floor,
)

_mt5_lock = threading.Lock()  # order_send/history calls aren't documented thread-safe; serialize them
_connected = False
_last_connect_error = ""

# Auto-reconnect, 2026-08-24, requested directly after a real incident:
# the bot's own long-running process (alive since 2026-08-21) kept
# logging "Not enough rate data" for ALL 6 symbols, in a tight loop,
# apparently for days — even though a completely fresh, separate python
# process connected to MT5 and fetched rates instantly. Root cause:
# is_connected() just returns the cached `_connected` module flag, set
# ONCE by connect_mt5() at startup (and again only in _loop()'s own
# startup path) — NOTHING ever re-checks or refreshes it once the bot is
# running, so if the underlying MT5 IPC session goes stale for ANY
# reason (terminal restart, a dropped connection over a weekend market
# closure and reopen, etc.), bot_tick() keeps sailing past
# `if not self.state.connected: return` believing everything is fine,
# then fails at the actual data fetch, forever, with no retry anywhere.
# User's question that prompted this: "saturday sunday market band rahe
# gi to kya yeh her weekend per aesa hi karega? iska solution hona
# chahiye" — yes, it would have, on every future weekend or any other
# MT5 disconnect, without this.
#
# Fix: whenever a symbol's tick hits either failure mode (is_connected()
# false, OR true but the actual rates fetch still fails), it calls
# _maybe_reconnect() below, which re-runs the exact same connect_mt5()
# used at startup — refreshing `_connected` for real instead of trusting
# a stale cached value. Rate-limited (cooldown, not per-tick) since up to
# 6 symbols' threads can all hit this in the same failure window and
# connect_mt5() itself can be slow (a full terminal64.exe relaunch has
# been observed taking up to ~60s) — retrying every 2s from 6 threads at
# once would pile up reconnect attempts instead of cleanly recovering.
_last_reconnect_attempt = 0.0
_RECONNECT_COOLDOWN_SECONDS = 30


def _maybe_reconnect():
    """Best-effort, rate-limited reconnect attempt — called whenever a
    symbol's tick discovers the MT5 connection isn't actually working,
    regardless of what the cached is_connected() flag says. Silent on
    failure (connect_mt5() already logs its own error into
    _last_connect_error); the caller's own "Not enough rate data" log
    line is enough visibility for a single tick — this just gives the
    bot a real chance to self-heal on the next one instead of never
    trying again."""
    global _last_reconnect_attempt
    now = time.time()
    if now - _last_reconnect_attempt < _RECONNECT_COOLDOWN_SECONDS:
        return
    _last_reconnect_attempt = now
    connect_mt5()


def connect_mt5() -> bool:
    """Shared across all symbols — one terminal session, one login.

    `path=cfg.MT5_TERMINAL_PATH` (2026-08-31, requested directly — see
    that config value's own comment for the full REASON): pins this
    process to its OWN dedicated terminal install, rather than letting
    mt5.initialize() attach to whichever terminal it happens to find —
    undefined/ambiguous now that two separate MT5 terminals exist on
    this machine (demo + live)."""
    global _connected, _last_connect_error
    with _mt5_lock:
        if not mt5.initialize(path=cfg.MT5_TERMINAL_PATH):
            _last_connect_error = f"initialize failed: {mt5.last_error()}"
            _connected = False
            return False
        ok = mt5.login(cfg.MT5_LOGIN, password=cfg.MT5_PASSWORD, server=cfg.MT5_SERVER)
        if not ok:
            _last_connect_error = f"login failed: {mt5.last_error()}"
            _connected = False
            return False
        _connected = True
        _last_connect_error = ""
        # Proof, not assumption — logs the ACTUAL terminal path MT5
        # itself reports being attached to, so this is verifiable in the
        # bot's own log rather than just trusted from the config value
        # passed in above.
        term = mt5.terminal_info()
        print(f"[connect_mt5] attached to terminal: {term.path if term else '?'} (expected {cfg.MT5_TERMINAL_PATH})")
        # Not every configured symbol is in Market Watch by default (e.g.
        # USA100 on this broker) — symbol_info_tick()/order_send() silently
        # fail on a non-selected symbol, so make sure every one we trade is
        # explicitly added.
        for symbol_cfg in cfg.SYMBOLS.values():
            if not mt5.symbol_select(symbol_cfg.SYMBOL, True):
                print(f"[connect_mt5] symbol_select failed for {symbol_cfg.SYMBOL}: {mt5.last_error()}")
        return True


def is_connected() -> bool:
    return _connected


def current_account_login() -> Optional[int]:
    """Which MT5 account is this process actually trading on right now —
    threaded through every trade_store call so switching accounts (e.g.
    live -> demo) never merges two accounts' history under the same symbol
    (see trade_store.py's account_login column)."""
    info = mt5.account_info()
    return info.login if info is not None else None


def _relevant_di(side: str, live_snap) -> float:
    """The DI value that matters for a given scalp direction: -DI for SELL, +DI for BUY."""
    return live_snap.di_minus if side == 'SELL' else live_snap.di_plus


class BotState:
    def __init__(self, symbol_cfg: cfg.SymbolConfig):
        self.lock = threading.Lock()
        self.running = False
        self.connected = False
        self.last_error = ""
        self.attempt = 0
        self.symbol = symbol_cfg.SYMBOL
        self.lot = symbol_cfg.LOT
        self.digits = 2  # this symbol's real price precision — set from SymbolBot._digits() once known,
        # so the dashboard can format GBPUSD/USDJPY prices correctly instead of a flat 2 decimals
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
        # Closed trades + win/loss/profit stats are NOT kept here — an
        # in-memory-only deque used to lose all history on every restart (bot
        # update, crash, system reboot). Both now live in trade_store's SQLite
        # DB (trade_history.db, one shared table with a symbol column).
        # Rule 1 (user-dictated, locked — do not modify without explicit permission):
        # no trade may open on the same candle that was forming when the bot
        # last started/restarted (fresh process launch OR a resume via the
        # dashboard's Start button) — must wait for that candle to close and
        # a new one to begin before any entry is even considered.
        self.startup_bar_time: Optional[int] = None  # bar_time captured on the first tick after start()
        self.startup_gate_cleared: bool = False  # True once a bar_time != startup_bar_time has been seen
        self.di_regime: Optional[str] = None  # 'PLUS' | 'MINUS' — which DI is currently dominant
        self.scalp_armed: bool = True  # one counter-scalp attempt per DI regime (re-armed on fresh cross)
        self.scalp_reversal_used: bool = False  # one immediate reversal-on-SL attempt per DI regime
        # NEW mechanism, 2026-08-14, requested directly, GBPUSD/USDJPY
        # only (cfg.TREND_SL_REVERSAL_ENABLED) — NOT a numbered rule, NOT
        # a modification to Rule 4: an ADDITIONAL, symbol-scoped reaction
        # fired alongside Rule 4's own (unchanged) gate-setting whenever a
        # WITH_TREND SL hits. Own dedicated field, own dedicated function
        # (_reverse_trend), same isolation shape as Rule 7's
        # scalp_reversal_used above — fully independent of it.
        self.trend_reversal_used: bool = False  # one immediate reversal-on-WITH_TREND-SL attempt per DI regime
        # Rule 3 (user-dictated, locked — do not modify without explicit
        # permission): WITH_TREND TP hit — its own isolated gate + dedicated
        # clearing method (_check_rule3_gate). Deliberately NOT shared with
        # any other gate/function, per the explicit isolation instruction
        # (2026-08-12): editing this rule's clearing conditions must never
        # be able to affect any other rule's.
        self.rule3_gate: Optional[dict] = None  # {'side','bar_time'} — WITH_TREND TP hit
        # WITH_TREND SL hit (locked, same isolation instruction) — its own
        # isolated gate + dedicated clearing method (_check_rule4_gate).
        self.rule4_gate: Optional[dict] = None  # {'side','bar_time'} — WITH_TREND SL hit
        # NEW mechanism, 2026-09-02, XAUUSD only (cfg.SCALP_SL_REVERSAL_
        # COOLDOWN) — set by _gate_scalp_reversal (ANY scalp SL close,
        # profit or loss alike) in place of the old immediate
        # _reverse_scalp() call, cleared entirely by its own dedicated
        # _check_rule7_reversal_gate. Same shape as rule4_gate (cooldown
        # floor + benchmark-cross-OR-rolling-DI+candle) but its own
        # separate field/function, zero shared state with rule4_gate —
        # blocks a fresh WITH_TREND entry on the REVERSAL (opposite) side
        # only. The scalp's own original side is not this gate's concern
        # at all — nothing in this mechanism touches it (corrected
        # 2026-09-02: no longer linked to Rule 6/scalp_continuation_gate,
        # per direct instruction — "rule 6 us se link nahi hai").
        self.rule7_reversal_gate: Optional[dict] = None  # {'side','benchmark','sl_time'} — reversal side blocked after any scalp SL (XAUUSD only)
        self.scalp_reversal_di = None  # {'side','di_at_sl'} — scalp's DI at the moment _reverse_scalp
        # fired; consumed once the reversal trade itself closes (see _classify_and_record_close)
        self.scalp_rearm_gate = None  # {'side','benchmark','rise_streak','last_bar_time'} — active after
        # a scalp AND its reversal have both been stopped out; re-arms scalp_armed early (see _check_scalp_rearm)
        # Scalp TP hit (user-dictated, locked — do not modify without
        # explicit permission): its own isolated gate/function
        # (_check_rule6_gate), separate from scalp_no_reversal_gate below.
        self.scalp_continuation_gate: Optional[dict] = None  # {'side','bar_time'} — active after a scalp
        # TP win; blocks re-arming another same-direction scalp until a genuinely new candle AND that
        # side's DI rising AND the forming candle is definitely the required color — previously this
        # re-armed immediately, same candle as the TP, which chased the tail of a move that had
        # already paid out and often gave the win straight back (found directly: USA100, 2026-08-11)
        self.scalp_no_reversal_gate: Optional[dict] = None  # {'side','bar_time'} — active after a scalp
        # SL whose immediate reversal attempt didn't end up opening a position (cap already used /
        # insufficient margin / order failed — see _reverse_scalp). Its own separate field/function,
        # kept isolated from every other gate.

    def log(self, msg: str):
        line = f"{datetime.now().strftime('%H:%M:%S')} | {msg}"
        with self.lock:
            self.logs.appendleft(line)
        print(f"[{self.symbol}] {line}")

    def snapshot_view(self) -> dict:
        # Read outside the lock — sqlite I/O shouldn't hold up the bot loop,
        # which also takes self.lock on every tick. account_login scopes
        # this to the currently-connected account only, so switching
        # accounts (e.g. live -> demo) never mixes their history together.
        login = (self.account or {}).get("login")
        # Table is per-account — before the first tick populates self.account
        # (login unknown yet), there's nothing to show; don't error.
        trade_history = trade_store.get_page(1, 50, login, symbol=self.symbol)["trades"] if login else []
        with self.lock:
            return {
                "running": self.running,
                "connected": self.connected,
                "last_error": self.last_error,
                "attempt": self.attempt,
                "symbol": self.symbol,
                "lot": self.lot,
                "digits": self.digits,
                "snapshot": dict(self.snapshot),
                "live": dict(self.live),
                "last_signal": dict(self.last_signal),
                "last_reason": self.last_reason,
                "mode": self.mode,
                "positions": list(self.positions),
                "account": dict(self.account),
                "stats": dict(self.stats),
                "logs": list(self.logs)[:80],
                "trade_history": trade_history,  # most recent 50 — full pagination via /api/trades
                "updated_at": self.updated_at,
            }


class SymbolBot:
    """Owns one symbol's polling loop, state, and all trading logic. Two
    systems, both re-evaluated fresh on every close:
      COUNTER_SCALP SL  -> try the opposite side immediately, tight SL,
        capped at one attempt per DI regime (scalp_reversal_used); if that
        doesn't end up opening, its own gate (scalp_no_reversal_gate).
      COUNTER_SCALP TP  -> its own isolated gate (scalp_continuation_gate / _check_rule6_gate).
      WITH_TREND TP -> its own isolated gate (rule3_gate / _check_rule3_gate).
      WITH_TREND SL -> its own isolated gate (rule4_gate / _check_rule4_gate).
    """

    def __init__(self, symbol_cfg: cfg.SymbolConfig):
        self.cfg = symbol_cfg
        self.state = BotState(symbol_cfg)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._digits_cache: Optional[int] = None  # see _digits()
        self._min_stop_cache: Optional[float] = None  # see _min_stop_distance()
        self._tick_size_cache: Optional[float] = None  # see _round_price()
        # trade_store tables are per-account (trade_history_<login>) and
        # created lazily on first use — the account isn't known yet at
        # construction time (MT5 may not be connected), so there's nothing
        # to pre-create here anymore.

    def _broker_time_offset(self) -> float:
        """Seconds to ADD to a raw MT5 `.time` epoch value (deal time,
        position time) to get the equivalent LOCAL machine wall-clock
        epoch. The broker's own server clock isn't necessarily UTC-synced
        — confirmed directly (2026-08-13): a live position's `opened_at`
        (from `position.time`) displayed ~3h AHEAD of `closed_at` (from
        `datetime.now()`), making trade history rows show "closed" before
        "opened" when both should read local time. Computed fresh each
        call from a live tick vs. `time.time()` rather than hardcoding
        that ~3h, since broker/DST changes could shift it."""
        tick = mt5.symbol_info_tick(self.cfg.SYMBOL)
        if tick is None or not tick.time:
            return 0.0
        return time.time() - tick.time

    def _broker_ts_to_local_str(self, epoch_seconds) -> str:
        """Renders an MT5 `.time` epoch value (deal/position time) as a
        LOCAL-machine-time string, using _broker_time_offset() — see its
        docstring. Added 2026-08-13, requested directly: user wants every
        trade-history timestamp on local machine time, open before close,
        for easy observation."""
        if not epoch_seconds:
            return "—"
        return datetime.fromtimestamp(epoch_seconds + self._broker_time_offset()).strftime("%Y-%m-%d %H:%M:%S")

    def _digits(self) -> int:
        """This symbol's actual price precision (2 for USA500/indices/gold,
        5 for GBPUSD, 3 for USDJPY, ...). SL/TP used to be hard-rounded to 2
        decimals for every symbol — harmless for USA500-scale instruments,
        but on GBPUSD (5 decimals) that collapsed a real SL/TP distance like
        1.35025 down to 1.35, landing on an invalid price and getting
        rejected by the broker ("Invalid stops", retcode 10016)."""
        if self._digits_cache is None:
            info = mt5.symbol_info(self.cfg.SYMBOL)
            self._digits_cache = info.digits if info else 2
        return self._digits_cache

    def _min_stop_distance(self) -> float:
        """Broker's minimum SL/TP distance from the current price, in price
        units. Two components, take whichever is bigger:

        1. trade_stops_level * point — the documented minimum.
        2. Current spread — on USA30, verified directly via mt5.order_check()
           (2026-08-11): trade_stops_level reports 0.60, but the broker
           actually rejected ("Invalid stops") anything under ~4.2, right
           at that moment's spread of ~3.8 — trade_stops_level alone was
           simply wrong for this symbol. This isn't documented anywhere;
           found by bisecting real order_check() calls. Spread moves tick
           to tick so this half is never cached, only the stops_level part.
        """
        # Not caching a bare 0 permanently — a transient symbol_info() miss
        # (e.g. right at startup before symbol_select() has taken effect)
        # would otherwise disable this safety clamp for the rest of the
        # process's life. Retry the fetch until a real value comes back.
        if not self._min_stop_cache:
            info = mt5.symbol_info(self.cfg.SYMBOL)
            self._min_stop_cache = (info.trade_stops_level * info.point) if info else 0.0
        tick = mt5.symbol_info_tick(self.cfg.SYMBOL)
        spread = (tick.ask - tick.bid) if tick else 0.0
        return max(self._min_stop_cache, spread)

    def _round_price(self, price: float, reference: Optional[float] = None, coarse: bool = True) -> float:
        """Round a computed SL/TP to the broker's real tradable price grid.

        Rounding to `digits` decimal places alone isn't enough — USA30
        confirmed directly via mt5.symbol_info() (2026-08-11): its
        trade_tick_size is 0.1, but digits=2 (0.01) implies 0.01 granularity
        is fine, which it isn't. SL/TP get computed from live_snap.close,
        which is a live bid/ask MID (for the dashboard's live-moving
        indicators) — averaging two 0.1-grid prices with an odd tick-count
        spread lands the mid exactly half a tick off-grid (e.g. ...95
        instead of ...90/...00), and every SL/TP derived from it inherits
        that same half-tick offset. `round(x, 2)` doesn't fix that (54195.95
        rounds to itself) — the broker then rejects it as invalid regardless
        of how far it is from price, no matter the safety margin. Every
        other configured symbol currently has trade_tick_size == point, so
        this was silent everywhere except USA30 — fixed generally here so
        any future symbol with the same mismatch doesn't hit it again.

        If `cfg.ROUND_STEP` is set AND `coarse=True` (USDJPY/GBPUSD,
        2026-08-12, requested directly — pip-level SL/TP rounding, not a
        broker-grid fix), rounds to THAT coarser step instead of the
        broker tick — and always AWAY from `reference` (entry price for a
        fresh order, current price for a trail), never to the nearest grid
        point. Rounding to nearest could otherwise shrink a tight computed
        distance (e.g. USDJPY's 0.046 scalp SL floor is smaller than the
        0.100 step) down to nearly nothing; rounding away only ever widens
        it.

        `coarse=False` (GBPUSD WITH_TREND SL only, 2026-08-13, requested
        directly) skips the ROUND_STEP grid entirely and falls straight
        through to the fine broker-tick rounding below — used when
        ROUND_STEP's away-rounding was inflating a target that's the SAME
        SIZE as the step itself (GBPUSD's flat 0.00100 SL, rounded away on
        a 0.00100 grid, could land anywhere up to ~0.00200 — nearly double
        the intended distance; user reported this as "SL bohot door ja
        raha hai" and asked for it back down near 0.00100). Scoped to SL
        only, WITH_TREND only, via the caller — TP and every other
        mode/symbol still get the normal coarse rounding."""
        step = self.cfg.ROUND_STEP if coarse else None
        if step:
            if reference is not None and price != reference:
                if price < reference:
                    price = math.floor(price / step) * step
                else:
                    price = math.ceil(price / step) * step
            else:
                price = round(price / step) * step
            return round(price, self._digits())
        if self._tick_size_cache is None:
            info = mt5.symbol_info(self.cfg.SYMBOL)
            self._tick_size_cache = (info.trade_tick_size if info and info.trade_tick_size else None)
        step = self._tick_size_cache
        if step:
            price = round(price / step) * step
        return round(price, self._digits())

    # ---------- account / position refresh ----------

    def _refresh_account(self):
        info = mt5.account_info()
        if info is None:
            return
        with self.state.lock:
            self.state.account = {
                "login": info.login,
                "balance": round(info.balance, 2),
                "equity": round(info.equity, 2),
                "margin": round(info.margin, 2),
                "profit": round(info.profit, 2),
            }

    def _refresh_positions(self):
        positions = mt5.positions_get(symbol=self.cfg.SYMBOL) or []
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
                "mode": self.state.position_modes.get(p.ticket, "?"),
            })
            # Keep the latest known state for each open ticket — used to classify
            # the close (win/loss, SL-side vs TP-side) the instant it disappears,
            # without waiting on mt5.history_deals_get() (see _classify_and_record_close).
            self.state.position_snapshot[p.ticket] = {
                "sl": p.sl, "tp": p.tp, "type": p.type,
                "price_open": p.price_open, "profit": p.profit,
                "mode": self.state.position_modes.get(p.ticket, "?"),
            }
        # drop closed tickets from mode map
        open_tickets = {p.ticket for p in positions}
        self.state.position_modes = {t: m for t, m in self.state.position_modes.items() if t in open_tickets}
        with self.state.lock:
            self.state.positions = rows
        return positions

    # ---------- persistent history / stats ----------

    def _sync_stats_from_db(self):
        """Recompute stats straight from trade_store — same rows the history
        table shows, so wins/losses/profit can never drift from what's
        actually listed (this is also where commission/swap reconciliation
        shows up)."""
        login = current_account_login()
        if login is None:
            return
        stats = trade_store.get_stats(login, symbol=self.cfg.SYMBOL)
        with self.state.lock:
            self.state.stats = stats

    def _sync_trades_from_broker(self, days: int = 90):
        """Reconcile local trade_history against MT5's OWN closed-deal
        history for this symbol — inserts any closed position that isn't
        recorded locally yet. Runs on startup, every resume-from-Stop, and
        periodically while running, so the local count stays aligned with
        MetaTrader's own on an ongoing basis, not just at first launch.
        Deals are grouped by position_id and already carry real
        commission/swap, so anything inserted here comes in fully reconciled.
        """
        login = current_account_login()
        if login is None:
            self.state.log("History sync: no account connected yet")
            return
        end = datetime.now()
        start = end - timedelta(days=days)
        # An intentional cleanup (deleting old/contaminated rows) sets a
        # cutoff so this sync doesn't just re-import them right back in on
        # the next run — without this, DELETE-ing a row from trade_store
        # wasn't actually permanent, since the broker's own history still
        # has that deal and this sync would see it as "missing" again.
        cutoff = trade_store.get_sync_cutoff(self.cfg.SYMBOL, login)
        if cutoff is not None:
            cutoff_dt = datetime.fromtimestamp(cutoff)
            if cutoff_dt > start:
                start = cutoff_dt
        with _mt5_lock:
            deals = mt5.history_deals_get(start, end)
        if deals is None:
            self.state.log(f"History sync: history_deals_get() failed — {mt5.last_error()}")
            return
        if not deals:
            self.state.log(f"History sync: MT5 returned 0 deals for the last {days}d — nothing to reconcile")
            return
        by_position = {}
        other_symbol_positions = {}  # position_id -> symbol, for diagnostics only
        for d in deals:
            if d.position_id == 0:
                continue  # balance/credit/deposit ops, not a real trade
            sym = getattr(d, 'symbol', '')
            if sym and sym != self.cfg.SYMBOL:
                other_symbol_positions[d.position_id] = sym
                continue
            by_position.setdefault(d.position_id, []).append(d)
        # Ticket numbers are only unique per-account, not globally — scoping
        # by account_login too avoids a demo-account ticket coincidentally
        # matching a live-account one and being skipped as "already known".
        known = trade_store.known_tickets(self.cfg.SYMBOL, login)
        added = 0
        still_open_tickets = []  # MT5 has deals for this ticket but no closing leg yet
        for pos_id, ds in by_position.items():
            if pos_id in known:
                continue
            ds.sort(key=lambda d: d.time)
            # DEAL_ENTRY_OUT (1) = normal close. DEAL_ENTRY_OUT_BY (3) = closed
            # by an opposite position (netting/hedge accounts).
            out_deals = [d for d in ds if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY)]
            in_deals = [d for d in ds if d.entry in (mt5.DEAL_ENTRY_IN, mt5.DEAL_ENTRY_INOUT)]
            if not out_deals:
                still_open_tickets.append(pos_id)
                continue  # still open, or no closing leg in this window
            gross = sum(d.profit for d in ds)
            commission = round(sum(d.commission for d in ds), 2)
            swap = round(sum(d.swap for d in ds), 2)
            net = round(gross + commission + swap, 2)
            open_deal = in_deals[0] if in_deals else ds[0]
            close_deal = out_deals[-1]
            side = "BUY" if open_deal.type == mt5.DEAL_TYPE_BUY else "SELL"
            entry = {
                "ticket": pos_id, "side": side, "mode": "IMPORTED",
                "opened_at": self._broker_ts_to_local_str(open_deal.time),
                "closed_at": self._broker_ts_to_local_str(close_deal.time),
                "price_open": open_deal.price, "sl": None, "tp": None,
                "profit": round(gross, 2), "close_reason": "—",
                "open_reason": "Imported from broker history",
            }
            trade_store.insert_trade(
                entry, ts=close_deal.time, symbol=self.cfg.SYMBOL, account_login=login,
                commission=commission, swap=swap, net_profit=net, reconciled=True,
            )
            added += 1

        known_matched = len(known & by_position.keys())
        unresolved = len(by_position) - known_matched - added
        if added or still_open_tickets or other_symbol_positions:
            self.state.log(
                f"History sync ({self.cfg.SYMBOL}, last {days}d): {len(by_position)} closed positions "
                f"seen in MT5 deals, {known_matched} already known, {added} added, {unresolved} unresolved"
            )
        if still_open_tickets:
            self.state.log(
                f"History sync: {len(still_open_tickets)} ticket(s) have deals but no OUT leg yet "
                f"per MT5 — tickets: {still_open_tickets[:10]}"
            )
        if added:
            self._sync_stats_from_db()
        if other_symbol_positions:
            syms = sorted(set(other_symbol_positions.values()))
            self.state.log(
                f"Note: {len(other_symbol_positions)} closed position(s) in broker "
                f"history are on other symbol(s) {syms} — not counted here "
                f"(this bot instance tracks {self.cfg.SYMBOL} only)"
            )

    def _reconcile_commissions(self):
        """MT5's position.profit (what closed trades are first recorded
        with) excludes commission/swap. This patches it in from the real
        deal history once it's available — history_deals_get() can lag the
        terminal by hours, so rows just wait in 'unreconciled' state until
        their deals show up. Cheap to call every tick: short-circuits
        immediately when nothing is pending."""
        login = current_account_login()
        if login is None:
            return
        pending = trade_store.find_unreconciled(self.cfg.SYMBOL, login, limit=25)
        if not pending:
            return
        end = datetime.now()
        start = end - timedelta(days=3)
        with _mt5_lock:
            deals = mt5.history_deals_get(start, end)
        if not deals:
            return
        by_position = {}
        for d in deals:
            by_position.setdefault(d.position_id, []).append(d)
        changed = False
        for row in pending:
            matches = by_position.get(row["ticket"])
            if not matches:
                continue
            commission = round(sum(d.commission for d in matches), 2)
            swap = round(sum(d.swap for d in matches), 2)
            net = round((row["gross_profit"] or 0) + commission + swap, 2)
            trade_store.update_commission(row["id"], login, commission, swap, net)
            changed = True
        if changed:
            self._sync_stats_from_db()
            self.state.log("Reconciled commission/swap for closed trade(s) — amounts now match broker history")

    def _push_trade_history(self, ticket: int, side: str, snap: dict, profit: float, close_reason: str):
        open_info = self.state.position_open_info.pop(ticket, {})
        now = datetime.now()
        entry = {
            "ticket": ticket,
            "side": side,
            "mode": snap.get("mode", "?"),
            "opened_at": open_info.get("opened_at", "—"),
            "closed_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "price_open": snap.get("price_open"),
            "sl": snap.get("sl"),
            "tp": snap.get("tp"),
            "profit": round(profit, 2),  # gross — reconciled to net (incl. commission/swap) once broker deal data lands
            "close_reason": close_reason,
            "open_reason": open_info.get("reason", ""),
        }
        login = current_account_login()
        if login is None:
            self.state.log(f"WARNING: couldn't record trade history for ticket {ticket} — no account login available")
            return
        trade_store.insert_trade(entry, ts=now.timestamp(), symbol=self.cfg.SYMBOL, account_login=login)
        self._sync_stats_from_db()

    # ---------- close classification / scalp+trend state machine ----------

    def _classify_and_record_close(self, ticket: int, live_snap, bid: Optional[float], ask: Optional[float]):
        """Runs the instant a tracked ticket disappears from positions_get().

        mt5.history_deals_get() can lag the terminal's own live state by a
        long time on this setup (observed: hours), so we don't use it for
        win/loss stats or SL-handling at all: everything here is derived
        from the position's own last known SL/TP/profit (from
        positions_get(), which stays accurate to the tick) plus the current
        bid/ask.
        """
        snap = self.state.position_snapshot.pop(ticket, None)
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

        self._push_trade_history(ticket, side, snap, profit, "SL" if hit_sl else "TP")
        self.state.log(f"{side} closed, profit {profit:+.2f} ({'SL-side' if hit_sl else 'TP-side'}, {mode})")

        if not hit_sl:
            if mode == 'COUNTER_SCALP':
                self._rearm_scalp_after_tp(side, live_snap)
            elif mode == 'WITH_TREND':
                # Rule 3 (WITH_TREND TP) — its own isolated gate, cleared
                # entirely by _check_rule3_gate, never by this function.
                # Always set for any WITH_TREND TP.
                self.state.rule3_gate = {'side': side, 'bar_time': live_snap.bar_time}
                self.state.log(
                    f"Rule 3: WITH_TREND TP ({side}) — profit secured, holding {side} entries until "
                    f"ADX/DI/rolling-DI/RSI/ATR/candle all confirm (same candle allowed once they do)"
                )
                # Rule 7's own concern (Scalp SL hit -> reversal outcome):
                # was this WITH_TREND position actually the immediate
                # reversal of an earlier scalp SL? Handled in its own
                # isolated function, not inline here.
                pending = self.state.scalp_reversal_di
                if pending and pending['side'] != side:
                    self._on_reversal_tp(live_snap)
            return

        if mode == 'COUNTER_SCALP':
            # "Indices" group only (see cfg.SCALP_SL_PROFIT_SKIP_REVERSAL's
            # own comment, config.py, for the full REASON/IMPACT) — a
            # profit-closed scalp SL (trailing) skips the immediate
            # reversal below entirely; a loss-closed one is unaffected.
            if self.cfg.SCALP_SL_PROFIT_SKIP_REVERSAL and profit >= 0:
                self._rearm_scalp_after_profit_sl(side, live_snap)
            # XAUUSD only (see cfg.SCALP_SL_REVERSAL_COOLDOWN's own
            # comment, config.py, for the full REASON/IMPACT) — CORRECTED
            # 2026-09-02, same day: originally scoped to a LOSS-closed
            # scalp SL only, and originally also re-armed the ORIGINAL
            # scalp side via Rule 6's own mechanism in parallel. User
            # caught BOTH as wrong the same day: "rule 6 us se link nahi
            # hai" (Rule 6 is Scalp TP — unrelated to this SL discussion,
            # remove it) and "sl with loss hit... sl with profit hit
            # hone per woh rule copy ho jayenge jo rule 4 mein hain" (both
            # outcomes copy ONLY Rule 4's mechanism into Rule 7 — nothing
            # else). Now applies to ANY scalp SL close on XAUUSD,
            # regardless of profit/loss — gates ONLY the reversal side,
            # same shape as Rule 4, no other mechanism involved.
            elif self.cfg.SCALP_SL_REVERSAL_COOLDOWN:
                self._gate_scalp_reversal(side, live_snap)
            else:
                self._reverse_scalp(side, live_snap)
        elif cfg.SL_COOLDOWN_UNTIL_NEXT_CANDLE:
            # Rule 4 (WITH_TREND SL) — its own isolated gate, cleared
            # entirely by _check_rule4_gate, never by this function.
            #
            # CHANGED 2026-08-13 (requested directly): no longer ALSO sets
            # last_bar_time. User caught this as a real isolation
            # violation, not just a wording issue — Rule 4 was being
            # restricted by TWO separate checks (this generic
            # already-entered-this-bar block, on top of rule4_gate's own
            # presence check in trend_ok), the exact "same rule checked in
            # multiple places" duplication the whole rules process exists
            # to prevent. rule4_gate is now the ONE mechanism governing
            # Rule 4's re-entry restriction — same scope Rule 3 already
            # has (blocks only a fresh WITH_TREND entry on THIS SAME
            # side; never touches the opposite side or scalp, on either
            # side, at all).
            #
            # Benchmark = the DI value AT THE MOMENT OF THIS SL, for the
            # SL'd side (same concept as Rule 7's own reversal-SL
            # benchmark, added same day): re-entry clears EITHER by DI
            # crossing back above this benchmark (fast path — a genuine
            # recovery past the failure point) OR by the existing
            # rolling-DI-vs-preceding-candle + forming candle color check
            # (slower path, unchanged) — whichever comes first, checked
            # fresh every tick, same candle as the SL or not.
            #
            # CORRECTED 2026-08-28 (real misimplementation caught by the
            # user): the 2026-08-27 cooldown floor below was applied to
            # EVERY SL close — but the user's original ask was explicitly
            # scoped to a LOSING SL only ("ager sl loss may hit ho to phir
            # wait kare... lekin ager with_trend sl k sath [profit mein,
            # i.e. trailing] close ho to jo kaam ker raha hai woh kerta
            # hai"). A trailing-SL exit that closed in PROFIT is a
            # successful trade, not a failed entry the rapid-reentry
            # protection was meant to guard against — caught live on
            # XAUUSD: a +160 profit trailing-SL close still triggered the
            # full 180s+DI-confirmation wait, blocking a legitimate
            # continuation entry in an obvious, ongoing trend. Fix:
            # `sl_time` (the cooldown floor) is now only set when this
            # close was an actual loss (profit < 0) — a profitable
            # trailing-SL close sets the gate with `sl_time=None`, which
            # `_check_rule4_gate` treats as "no minimum-wait floor, go
            # straight to the two original clearing paths" (the exact
            # pre-2026-08-27 behavior for this case).
            sl_time = time.time() if profit < 0 else None
            self.state.rule4_gate = {
                'side': side, 'bar_time': live_snap.bar_time,
                'benchmark': _relevant_di(side, live_snap),
                'sl_time': sl_time,
            }
            if sl_time is not None:
                self.state.log(
                    f"Rule 4: WITH_TREND SL ({side}, loss {profit:+.2f}) — {side}-side re-entry needs "
                    f"{cfg.RULE4_MIN_COOLDOWN_SECONDS:.0f}s minimum wait, THEN EITHER DI crossing "
                    f"{_relevant_di(side, live_snap):.1f} (benchmark) OR rolling DI rising + forming "
                    f"candle definitely {'green' if side == 'BUY' else 'red'}"
                )
            else:
                self.state.log(
                    f"Rule 4: WITH_TREND SL ({side}, trailing profit {profit:+.2f}) — no minimum-wait "
                    f"cooldown (closed in profit, not a loss) — {side}-side re-entry needs EITHER DI "
                    f"crossing {_relevant_di(side, live_snap):.1f} (benchmark) OR rolling DI rising + "
                    f"forming candle definitely {'green' if side == 'BUY' else 'red'}"
                )
            # Rule 7's own concern (Scalp SL hit -> reversal outcome): was
            # this WITH_TREND position actually the immediate reversal of
            # an earlier scalp SL, and did it ALSO get stopped out?
            # Handled in its own isolated function, not inline here.
            pending = self.state.scalp_reversal_di
            if pending and pending['side'] != side:
                self._on_reversal_sl(pending, live_snap)
            # NEW mechanism's own concern (not Rule 4's, not Rule 7's):
            # GBPUSD/USDJPY only, added ALONGSIDE everything above,
            # nothing above touched. Handled in its own isolated function.
            if self.cfg.TREND_SL_REVERSAL_ENABLED and not self.state.trend_reversal_used:
                self._reverse_trend(side, live_snap)

    def _check_scalp_rearm(self, live_snap):
        """Rule 7 (Scalp SL hit) — clearing check for the scalp-side
        benchmark set by _on_reversal_sl (scalp AND its reversal both
        SL'd). Runs every tick while state.scalp_rearm_gate is active. Two
        independent ways to re-arm — whichever comes first:
          1. Fast: DI crosses above the benchmark.
          2. Slower: DI rises candle-over-candle for 2 candles in a row.
        """
        gate = self.state.scalp_rearm_gate
        if not gate:
            return
        side = gate['side']
        current = _relevant_di(side, live_snap)

        if current > gate['benchmark']:
            self.state.scalp_armed = True
            self.state.scalp_rearm_gate = None
            self.state.log(f"Rule 7: scalp re-armed ({side}) — DI {current:.1f} crossed benchmark {gate['benchmark']:.1f}")
            return

        if live_snap.bar_time != gate['last_bar_time']:
            prev = live_snap.prev_di_minus if side == 'SELL' else live_snap.prev_di_plus
            gate['rise_streak'] = gate['rise_streak'] + 1 if current > prev else 0
            gate['last_bar_time'] = live_snap.bar_time
            if gate['rise_streak'] >= 2:
                self.state.scalp_armed = True
                self.state.scalp_rearm_gate = None
                self.state.log(f"Rule 7: scalp re-armed ({side}) — DI rising 2 candles in a row")

    def _on_reversal_tp(self, live_snap):
        """Rule 7 (Scalp SL hit) — reversal TP outcome, its own isolated
        function (does not touch rule3_gate or any other rule's state;
        called alongside Rule 3's own handling, not from inside it).

        When the immediate reversal-of-a-scalp-SL trade itself wins (TP),
        scalp must be explicitly re-armed here — unlike an ordinary
        WITH_TREND TP (where scalp_armed was likely already True), this
        one follows directly from a scalp SL that set scalp_armed False,
        and nothing else on this path re-arms it. Without this, scalp
        would stay stuck disarmed until a full DI regime flip even though
        the reversal won."""
        self.state.scalp_reversal_di = None
        self.state.scalp_armed = True
        self.state.log("Rule 7: reversal TP — scalp re-armed")

    def _on_reversal_sl(self, pending: dict, live_snap):
        """Rule 7 (Scalp SL hit) — reversal SL outcome (scalp AND its
        reversal have now both been stopped out), its own isolated
        function (does not touch rule4_gate or any other rule's state;
        called alongside Rule 4's own handling, not from inside it).

        Sets a rolling-DI benchmark re-arm for the scalp side — benchmark
        = the stronger of the two failure-point DI readings (scalp's own
        SL, and the reversal's SL). Cleared by _check_scalp_rearm."""
        scalp_side = pending['side']
        di_at_reversal_sl = _relevant_di(scalp_side, live_snap)
        benchmark = max(pending['di_at_sl'], di_at_reversal_sl)
        self.state.scalp_rearm_gate = {
            'side': scalp_side, 'benchmark': benchmark,
            'rise_streak': 0, 'last_bar_time': None,
        }
        self.state.scalp_reversal_di = None
        self.state.log(
            f"Rule 7: scalp + reversal both SL'd — {scalp_side} scalp re-arms early if DI "
            f"crosses {benchmark:.1f}, or 2 rising candles in a row"
        )

    def _rearm_scalp_after_tp(self, side: str, live_snap):
        """Rule 6 (Scalp TP hit). Sets scalp_continuation_gate — this
        rule's own dedicated field, cleared entirely by _check_rule6_gate.

        CHANGED 2026-08-13 (requested directly, same change as Rule 3):
        no longer blocks ALL new entries this candle via last_bar_time —
        that was preventing WITH_TREND (and scalp) from continuing right
        after a clean scalp TP. The original reason for the blanket block
        (found directly: USA100, 2026-08-11 — a scalp win got chased and
        given back) is now handled by _check_rule6_gate's full
        confirmation requirement instead of an outright block: a genuine
        exhaustion/reversal should fail ADX/RSI/ATR/DI confirmation, while
        genuine continuation should pass it, same candle or not."""
        self.state.scalp_continuation_gate = {'side': side, 'bar_time': live_snap.bar_time}
        label = '-DI' if side == 'SELL' else '+DI'
        candle_word = 'green' if side == 'BUY' else 'red'
        self.state.log(
            f"Rule 6: Scalp TP ({side}) — waiting for ADX/RSI/ATR/{label} rising/forming candle "
            f"definitely {candle_word} to all confirm before re-arming another {side} scalp "
            f"(same candle allowed once confirmed)"
        )

    def _rearm_scalp_after_profit_sl(self, side: str, live_snap):
        """"Indices" group only (USA500/USA100/USA30, cfg.SCALP_SL_PROFIT_
        SKIP_REVERSAL), added 2026-09-01 — real data showed PROFIT-
        triggered immediate reversals net-negative on all three
        (-8.36/-16.70/-147.70), while LOSS-triggered ones were net-
        POSITIVE (+3.00/+34.53/+81.10) — the opposite pairing from
        XAUUSD, where BOTH cases are negative (XAUUSD is frozen per
        v2.18 anyway — untouched; GBPUSD/USDJPY explicitly get no change
        this round either — this flag defaults False everywhere else).

        A scalp position whose TRAILING SL closes it while still in
        PROFIT now skips Rule 7's immediate/zero-confirmation reversal
        entirely and re-arms scalp EXACTLY the way an ordinary Rule 6 TP
        outcome does — same state (scalp_continuation_gate), same
        clearing function (_check_rule6_gate), completely UNCHANGED and
        NOT duplicated, per direct instruction ("scalp re-arm ka system
        wohi rahega jo existing hai, mein us ko change karne ka nahi keh
        raha"). This function exists only so the log text is accurate
        (this was an SL close, not an actual TP) — a LOSS-triggered scalp
        SL is completely unaffected, still the existing, unchanged
        _reverse_scalp() immediate reversal (see the call site in
        _classify_and_record_close)."""
        self.state.scalp_continuation_gate = {'side': side, 'bar_time': live_snap.bar_time}
        label = '-DI' if side == 'SELL' else '+DI'
        candle_word = 'green' if side == 'BUY' else 'red'
        self.state.log(
            f"Scalp SL ({side}, closed in profit via trailing) — indices-only: no immediate "
            f"reversal, waiting for ADX/RSI/ATR/{label} rising/forming candle definitely "
            f"{candle_word} to all confirm before re-arming another {side} scalp "
            f"(same re-arm as Rule 6's own TP outcome, same candle allowed once confirmed)"
        )

    def _gate_scalp_reversal(self, closed_side: str, live_snap):
        """XAUUSD only (cfg.SCALP_SL_REVERSAL_COOLDOWN), added 2026-09-02
        — see that flag's own comment in config.py for the full REASON/
        IMPACT.

        CORRECTED same day: originally named _gate_scalp_reversal_after_
        loss, scoped to a loss-closed scalp SL only, and ALSO re-armed the
        original scalp side via Rule 6's own mechanism (scalp_continuation_
        gate) in parallel. User caught both as wrong: "rule 6 us se link
        nahi hai" (Rule 6 is Scalp TP — has nothing to do with this SL
        discussion, remove it) and confirmed the mechanism applies to
        BOTH outcomes — "sl with loss hit... rule 4 mein diye gaye rules
        copy ho jayenge rule 7 mein, aur sl with profit hit hone per woh
        rule copy ho jayenge jo rule 4 mein hain" (Rule 4's own mechanism,
        and ONLY Rule 4's, gets copied into Rule 7 for both a loss- and a
        profit-closed scalp SL alike). No Rule 6 involvement at all now.

        Replaces the old immediate, zero-confirmation `_reverse_scalp()`
        call (for XAUUSD) with a single isolated gate, `rule7_reversal_
        gate` — same shape as rule4_gate (own dedicated field +
        _check_rule7_reversal_gate, zero shared state with rule4_gate
        itself): blocks a fresh WITH_TREND entry on the REVERSAL (opposite)
        side only, until RULE4_MIN_COOLDOWN_SECONDS have passed AND EITHER
        that side's DI crosses its own benchmark OR rolling DI + forming
        candle color confirm — exactly Rule 4's own two clearing paths,
        copied. This gate does NOT force a trade — it only lifts a block;
        if a genuine signal exists on that side once unblocked, the bot's
        own normal decide() logic takes it from there, exactly like
        Rule 4. The scalp's own original side is not this gate's concern
        at all — nothing here touches it, in either direction."""
        opposite = 'SELL' if closed_side == 'BUY' else 'BUY'
        self.state.rule7_reversal_gate = {
            'side': opposite,
            'benchmark': _relevant_di(opposite, live_snap),
            'sl_time': time.time(),
        }
        label = '-DI' if opposite == 'SELL' else '+DI'
        candle_word = 'green' if opposite == 'BUY' else 'red'
        self.state.log(
            f"Rule 7 (XAUUSD): Scalp SL ({closed_side}) — no immediate reversal. "
            f"{opposite}-side blocked {cfg.RULE4_MIN_COOLDOWN_SECONDS:.0f}s minimum, THEN "
            f"EITHER {label} crossing {self.state.rule7_reversal_gate['benchmark']:.1f} (benchmark) OR "
            f"rolling {label} rising + forming candle definitely {candle_word}"
        )

    def _check_rule6_gate(self, live_snap):
        """Rule 6 (Scalp TP hit) — self-contained clearing check. Fully
        independent implementation — zero shared code/state with any
        other gate.

        CHANGED 2026-08-13 (requested directly): no longer requires
        waiting for a genuinely NEW candle to even start. Now clears
        WITHIN the same candle the TP happened on, the moment full
        confirmation passes: ADX >= ADX_MIN, this side's DI still
        dominant (opposing the big trend, the scalp definition) AND
        rolling (rising vs the immediately preceding candle), RSI inside
        the scalp band, ATR strong, and the currently forming candle
        DEFINITELY the required color.

        CHANGED 2026-09-03 (cfg.ATR_CHECK_ENABLED, per-symbol, all 6
        symbols now — XAUUSD explicitly named same day, exempting it from
        the standing freeze) — requested directly, mirroring Rule 5's own
        matching change (see strategy.evaluate_entry's own comment for the
        full REASON/IMPACT/history, including how this flag's scope grew
        same day): ATR is now only actually enforced when this flag is
        True. ADX/DI/rolling-DI/RSI/candle-color all stay, unconditionally.

        CHANGED AGAIN, same day (cfg.CONDITION_CHECK_ENABLED, Rules
        2/3/4/5/6/7, all 6 symbols): user asked to replace the ATR idea
        with a different signal entirely — `live_snap.condition` (NORMAL/
        RANGING/VOLATILE, already computed every tick in
        strategy.build_snapshot but never read by any rule before this).
        Allow when NORMAL or VOLATILE, block when RANGING. See config.py's
        own comment on this flag for the full REASON/IMPACT."""
        gate = self.state.scalp_continuation_gate
        if not gate:
            return
        side = gate['side']
        if side == 'BUY':
            cleared = (
                live_snap.adx >= self.cfg.ADX_MIN
                and live_snap.di_plus > live_snap.di_minus
                and live_snap.di_plus > live_snap.prev_di_plus       # rolling DI
                and live_snap.rsi > self.cfg.RSI_SCALP_BUY_MIN
                and (live_snap.atr_strong or not self.cfg.ATR_CHECK_ENABLED)
                and (live_snap.condition != 'RANGING' or not self.cfg.CONDITION_CHECK_ENABLED)  # 2026-09-03
                and _bullish_candle(live_snap)                        # forming candle definitely green
            )
        else:
            cleared = (
                live_snap.adx >= self.cfg.ADX_MIN
                and live_snap.di_minus > live_snap.di_plus
                and live_snap.di_minus > live_snap.prev_di_minus     # rolling DI
                and live_snap.rsi < self.cfg.RSI_SCALP_SELL_MAX
                and (live_snap.atr_strong or not self.cfg.ATR_CHECK_ENABLED)
                and (live_snap.condition != 'RANGING' or not self.cfg.CONDITION_CHECK_ENABLED)  # 2026-09-03
                and _bearish_candle(live_snap)                        # forming candle definitely red
            )
        if cleared:
            self.state.scalp_continuation_gate = None
            self.state.scalp_armed = True
            atr_part = "ATR" if self.cfg.ATR_CHECK_ENABLED else "ATR-check-disabled"
            self.state.log(
                f"Rule 6 gate cleared ({side}) — ADX/DI/rolling-DI/RSI/{atr_part}/condition/candle all confirmed "
                f"(same-candle re-arm now allowed once confirmed)"
            )

    def _rearm_scalp_after_sl_no_reversal(self, side: str, live_snap, trigger: str):
        """Not yet a formalized numbered rule — pre-existing behavior for
        when a scalp SL's reversal attempt didn't end up opening a
        position (cap already used / insufficient margin / order failed —
        see _reverse_scalp). Its own dedicated gate (scalp_no_reversal_gate),
        cleared by the original rolling-DI + last-CLOSED-candle-color
        standard (strategy._momentum_recovered) — kept fully independent
        of every other gate."""
        self.state.scalp_no_reversal_gate = {'side': side, 'bar_time': live_snap.bar_time}
        label = '-DI' if side == 'SELL' else '+DI'
        candle_word = 'green' if side == 'BUY' else 'red'
        self.state.log(
            f"{trigger} ({side}) — waiting next candle + {label} rising + {candle_word} candle "
            f"before re-arming another {side} scalp"
        )

    def _check_scalp_no_reversal_gate(self, live_snap, closed_snap):
        """Runs every tick while state.scalp_no_reversal_gate is active
        (set in _rearm_scalp_after_sl_no_reversal). Unchanged pre-existing
        logic — kept in its own function/field, fully independent of every
        other gate."""
        gate = self.state.scalp_no_reversal_gate
        if not gate:
            return
        side = gate['side']
        if _momentum_recovered(side, live_snap, closed_snap, gate):
            self.state.scalp_armed = True
            self.state.scalp_no_reversal_gate = None
            self.state.log(f"Scalp re-armed ({side}) — next candle + DI rising + candle confirmed")

    def _check_rule3_gate(self, live_snap):
        """Rule 3 (WITH_TREND TP hit) — self-contained clearing check, set
        in _classify_and_record_close. Fully independent implementation —
        editing this function can never affect any other rule, and editing
        any other rule can never affect this one.

        CHANGED 2026-08-13 (requested directly): no longer requires
        waiting for a genuinely NEW CLOSED candle — that was blocking the
        trend from continuing right after a clean TP. Now clears WITHIN
        the SAME candle the TP happened on, the moment full confirmation
        passes on live data: ADX >= ADX_MIN, DI dominant in the trade's
        direction AND rolling (rising vs the immediately preceding
        candle), RSI inside the WITH_TREND band, ATR strong, and the
        CURRENTLY FORMING candle definitely the required color (an
        absolute requirement, not just "not opposite" — the previous
        version's weaker check).

        CHANGED 2026-09-03 (cfg.ATR_CHECK_ENABLED, all 6 symbols — XAUUSD
        explicitly named same day, exempting it from the standing freeze)
        — found while implementing a Rule 5/6 ATR-removal request (this
        gate was the one WITH_TREND-family check that DID check ATR, even
        though a fresh Rule 2 entry never has), flagged to the user, then
        explicitly asked to be included too: "rule 3 se bhi remove karo."
        ATR is now only actually enforced when this flag is True — same
        flag Rule 5/6 read (see config.py's own comment for the full
        history of how its scope grew same day). ADX/DI/rolling-DI/RSI/
        candle-color all stay, unconditionally.

        CHANGED AGAIN, same day (cfg.CONDITION_CHECK_ENABLED, Rules
        2/3/4/5/6/7, all 6 symbols): user asked to replace the ATR idea
        with a different signal entirely — `live_snap.condition` (NORMAL/
        RANGING/VOLATILE, already computed every tick in
        strategy.build_snapshot but never read by any rule before this).
        Allow when NORMAL or VOLATILE, block when RANGING. See config.py's
        own comment on this flag for the full REASON/IMPACT."""
        gate = self.state.rule3_gate
        if not gate:
            return
        side = gate['side']
        if side == 'BUY':
            cleared = (
                live_snap.adx >= self.cfg.ADX_MIN
                and live_snap.di_plus > live_snap.di_minus
                and live_snap.di_plus > live_snap.prev_di_plus     # rolling DI
                and live_snap.rsi <= _rsi_buy_ceiling(live_snap, self.cfg)
                and live_snap.rsi >= 40
                and (live_snap.atr_strong or not self.cfg.ATR_CHECK_ENABLED)
                and (live_snap.condition != 'RANGING' or not self.cfg.CONDITION_CHECK_ENABLED)  # 2026-09-03
                and _bullish_candle(live_snap)                      # forming candle definitely green
            )
        else:
            cleared = (
                live_snap.adx >= self.cfg.ADX_MIN
                and live_snap.di_minus > live_snap.di_plus
                and live_snap.di_minus > live_snap.prev_di_minus   # rolling DI
                and live_snap.rsi >= _rsi_sell_floor(live_snap, self.cfg)
                and live_snap.rsi <= 60
                and (live_snap.atr_strong or not self.cfg.ATR_CHECK_ENABLED)
                and (live_snap.condition != 'RANGING' or not self.cfg.CONDITION_CHECK_ENABLED)  # 2026-09-03
                and _bearish_candle(live_snap)                      # forming candle definitely red
            )
        if cleared:
            self.state.rule3_gate = None
            atr_part = "ATR" if self.cfg.ATR_CHECK_ENABLED else "ATR-check-disabled"
            self.state.log(
                f"Rule 3 gate cleared ({side}) — ADX/DI/rolling-DI/RSI/{atr_part}/condition/candle all confirmed "
                f"(same-candle re-entry now allowed once confirmed)"
            )

    def _check_rule4_gate(self, live_snap):
        """Rule 4 (WITH_TREND SL hit) — self-contained clearing check, set
        in _classify_and_record_close (which also blocks the SAME candle
        entirely via last_bar_time). Fully independent implementation.

        CHANGED 2026-08-13 (requested directly, same fix as Rule 3/6):
        no longer requires waiting for a genuinely NEW candle. User caught
        this live on XAUUSD: SL hit, price reversed straight back into the
        trend direction (-DI rising vs the preceding candle, forming
        candle red — both already true), but the gate stayed blocked for
        several more minutes purely because it was still the SAME candle
        as the SL — this same-candle wait had been removed from Rule 3/6
        but was never extended to Rule 4.

        CHANGED AGAIN, same day: clears via EITHER of two independent
        paths, whichever comes first — same two-path shape as Rule 7's
        own reversal-SL benchmark re-arm:
        1. FAST: that side's DI crosses back above `gate['benchmark']`
           (the DI reading at the moment of THIS SL — a genuine recovery
           past the failure point), by itself, no candle-color check.
        2. SLOWER: the original check — that side's DI above the
           immediately preceding candle (rolling) AND the CURRENTLY
           FORMING candle DEFINITELY the required color (absolute
           requirement, not just "not opposite").

        CHANGED 2026-08-27 (requested directly, real XAUUSD case): a
        minimum-time floor now gates BOTH paths above. Caught live: SL hit,
        then a fresh same-side WITH_TREND entry opened again almost
        immediately — the fast path's benchmark is captured AT THE SL
        ITSELF, so a single noisy tick right after can clear it trivially,
        and the slow path only needs one favorable tick too. Neither path
        checks AT ALL until cfg.RULE4_MIN_COOLDOWN_SECONDS has elapsed
        since the SL — not a full-candle wait (that was tried and removed
        in v2.2/v2.5), just a real floor before either is even evaluated.

        CORRECTED 2026-08-28: this floor only applies when the SL closed
        at an actual LOSS — `gate['sl_time']` is None for a profitable
        trailing-SL close (set in _classify_and_record_close), meaning
        this cooldown check is skipped entirely and clearing falls
        straight through to the two original paths, exactly as it worked
        before 2026-08-27 for that case. See that call site's own comment
        for the full reasoning (a live XAUUSD case where a +160 profit
        trailing exit wrongly got the full loss-cooldown treatment)."""
        gate = self.state.rule4_gate
        if not gate:
            return
        if gate['sl_time'] is not None:
            elapsed = time.time() - gate['sl_time']
            if elapsed < cfg.RULE4_MIN_COOLDOWN_SECONDS:
                return  # still inside the minimum cooldown — neither path checked yet
        side = gate['side']
        current_di = _relevant_di(side, live_snap)
        benchmark_crossed = current_di > gate['benchmark']
        if side == 'BUY':
            slow_path = live_snap.di_plus > live_snap.prev_di_plus and live_snap.close > live_snap.open
        else:
            slow_path = live_snap.di_minus > live_snap.prev_di_minus and live_snap.close < live_snap.open
        # CONDITION_CHECK_ENABLED, 2026-09-03 (Rules 2/3/4/5/6/7, all 6
        # symbols) — requested directly, replacing the ATR idea entirely
        # with `live_snap.condition` (NORMAL/RANGING/VOLATILE): allow when
        # NORMAL or VOLATILE, block when RANGING. Gates the WHOLE clear —
        # neither path above matters if the market is currently RANGING.
        # See config.py's own comment on this flag for the full REASON.
        condition_ok = live_snap.condition != 'RANGING' or not self.cfg.CONDITION_CHECK_ENABLED
        if (benchmark_crossed or slow_path) and condition_ok:
            self.state.rule4_gate = None
            reason = f"DI {current_di:.1f} crossed benchmark {gate['benchmark']:.1f}" if benchmark_crossed \
                else f"rolling DI rising + forming candle definitely {'green' if side == 'BUY' else 'red'}"
            self.state.log(f"Rule 4 gate cleared ({side}) — {reason}")

    def _check_rule7_reversal_gate(self, live_snap):
        """XAUUSD only (cfg.SCALP_SL_REVERSAL_COOLDOWN), 2026-09-02 —
        self-contained clearing check for rule7_reversal_gate (set in
        _gate_scalp_reversal, for ANY scalp SL close, profit or loss
        alike). Fully independent implementation — zero shared code/state
        with _check_rule4_gate or any other gate, even though the shape is
        deliberately identical (copied directly, per the user's own
        explicit instruction: Rule 4's mechanism, and only Rule 4's, is
        copied into Rule 7 for both a loss- and a profit-closed scalp SL).

        Same cooldown floor (cfg.RULE4_MIN_COOLDOWN_SECONDS, read-only
        constant reuse — not shared state) applies unconditionally here —
        unlike Rule 4 (which skips the floor on a profit-close, since
        there it's a successful trailing exit, not a failed entry), this
        gate is about the REVERSAL side, which was never the position that
        actually closed, so there's no equivalent case to skip it for.
        Clears via EITHER of two independent paths, whichever comes first:
        1. FAST: the gated (reversal) side's DI crosses back above
           `gate['benchmark']` (captured at the moment of the scalp SL).
        2. SLOWER: that side's DI above the immediately preceding candle
           (rolling) AND the currently forming candle DEFINITELY that
           side's color.

        Clearing here ONLY lifts the block (`rule7_reversal_gate = None`)
        — exactly like Rule 4, no trade is forced. If a genuine WITH_TREND
        signal exists on that side once unblocked, evaluate_entry's own
        normal checks decide from there; if not, nothing happens until
        they do. The scalp's own original side is not this gate's concern
        at all — nothing here touches it, in either direction."""
        gate = self.state.rule7_reversal_gate
        if not gate:
            return
        elapsed = time.time() - gate['sl_time']
        if elapsed < cfg.RULE4_MIN_COOLDOWN_SECONDS:
            return  # still inside the minimum cooldown — neither path checked yet
        side = gate['side']
        current_di = _relevant_di(side, live_snap)
        benchmark_crossed = current_di > gate['benchmark']
        if side == 'BUY':
            slow_path = live_snap.di_plus > live_snap.prev_di_plus and live_snap.close > live_snap.open
        else:
            slow_path = live_snap.di_minus > live_snap.prev_di_minus and live_snap.close < live_snap.open
        # CONDITION_CHECK_ENABLED, 2026-09-03 (Rules 2/3/4/5/6/7, all 6
        # symbols) — same as Rule 4's own addition, see that function's
        # comment for the full REASON; config.py's own comment on this
        # flag has the complete history.
        condition_ok = live_snap.condition != 'RANGING' or not self.cfg.CONDITION_CHECK_ENABLED
        if (benchmark_crossed or slow_path) and condition_ok:
            self.state.rule7_reversal_gate = None
            reason = f"DI {current_di:.1f} crossed benchmark {gate['benchmark']:.1f}" if benchmark_crossed \
                else f"rolling DI rising + forming candle definitely {'green' if side == 'BUY' else 'red'}"
            self.state.log(f"Rule 7 reversal gate cleared ({side}) — {reason}")

    def _reverse_scalp(self, closed_side: str, live_snap):
        """Rule 7 (Scalp SL hit) — a COUNTER_SCALP just got stopped out;
        immediately try the opposite side once, tight SL/TP regardless of
        which mode classify_side() picks (this is a reactive,
        zero-confirmation entry — full trend-size risk here meant a
        single wrong reversal could cost as much as a properly-confirmed
        trend trade). Capped at one attempt per DI regime
        (scalp_reversal_used).

        SIZING CHANGED 2026-08-14 (requested directly): used to call
        _sl_tp_scalp() directly, meaning Rule 7's SL was ALWAYS whatever
        Rule 5's scalp SL happened to be — the two could never differ.
        User: "har rule independent hona chahiye... reversal ke levels
        alag, scalp ke alag" — now calls its own _sl_tp_reversal(), which
        checks cfg.REVERSAL_FIXED_SL_POINTS first (Rule 7's own,
        independent override) before falling through the same chain
        _sl_tp_scalp uses. Setting one rule's SL can no longer silently
        change the other's.

        Every exit that does NOT end in a confirmed open position falls
        through to the shared _rearm_scalp_after_sl_no_reversal() gate
        instead of returning bare — corrected 2026-08-11, found by audit
        after a live report (USA100) turned up the first instance of this
        class of bug (the reversal-cap branch, below). Three exits shared
        the same flaw before this fix: reversal cap already used,
        insufficient margin, and send_order() itself failing — each one
        left scalp_armed False with NO gate watching to re-arm it (stuck
        until a full DI regime flip, which can take a long time or never
        happen). State (scalp_reversal_used, the gates, scalp_armed) is
        now only mutated AFTER send_order() confirms a real ticket — the
        same confirm-before-mutate pattern bot_tick() already used
        correctly for fresh scalp entries (`if after > before: ...`),
        which this function had never matched.

        NOTE: this whole re-arm-on-failed-reversal mechanism is not yet a
        formalized numbered rule — kept on its own separate, isolated
        gate, unaffected by any numbered rule's own changes."""
        if self.state.scalp_reversal_used:
            self._rearm_scalp_after_sl_no_reversal(closed_side, live_snap, trigger="Scalp SL (reversal cap reached)")
            return
        if not self.should_take_trade():
            self._rearm_scalp_after_sl_no_reversal(closed_side, live_snap, trigger="Scalp SL (reversal skipped — insufficient margin)")
            return
        # CONDITION_CHECK_ENABLED, 2026-09-03 (Rules 2/3/4/5/6/7, all 6
        # symbols) — requested directly, replacing the ATR idea entirely
        # with live_snap.condition (NORMAL/RANGING/VOLATILE): allow when
        # NORMAL or VOLATILE, block when RANGING. This is Rule 7's own
        # forced, zero-confirmation reversal — the one path in this whole
        # project with NO other confirmation at all, so a RANGING market
        # blocking it here matters most of anywhere. See config.py's own
        # comment on this flag for the full REASON/IMPACT.
        if self.cfg.CONDITION_CHECK_ENABLED and live_snap.condition == 'RANGING':
            self._rearm_scalp_after_sl_no_reversal(closed_side, live_snap, trigger="Scalp SL (reversal skipped — condition RANGING)")
            return
        opposite = 'SELL' if closed_side == 'BUY' else 'BUY'
        mode, _sl, _tp, _trail = classify_side(opposite, live_snap, self.cfg)
        sl, tp = _sl_tp_reversal(opposite, live_snap.close, live_snap.atr, self.cfg)
        self.state.log(f"Scalp SL -> immediately opening opposite {opposite} [{mode}, tight SL — unconfirmed reversal]")
        ticket = self.send_order(
            opposite, sl, tp, f'SCALP_REV_{mode}', mode,
            f"Rule 7: Immediate reversal after COUNTER_SCALP {closed_side} stopped out (tight SL, unconfirmed)",
        )
        if ticket is None:
            # Order genuinely never opened — don't burn the one-per-regime
            # cap on a trade that doesn't exist, and don't leave scalp_armed
            # stranded either.
            self._rearm_scalp_after_sl_no_reversal(closed_side, live_snap, trigger="Scalp SL (reversal order failed)")
            return
        self.state.scalp_reversal_used = True
        self.state.rule3_gate = None  # a fresh entry just opened — old gate is moot
        self.state.rule4_gate = None  # ditto
        self.state.scalp_continuation_gate = None  # ditto
        self.state.scalp_no_reversal_gate = None  # ditto
        self.state.scalp_reversal_di = {'side': closed_side, 'di_at_sl': _relevant_di(closed_side, live_snap)}
        if mode == 'COUNTER_SCALP':
            self.state.scalp_armed = False
        self.state.last_bar_time = live_snap.bar_time  # this bar already acted on — decide() should just MANAGE

    def _reverse_trend(self, closed_side: str, live_snap):
        """NEW mechanism, 2026-08-14, requested directly — GBPUSD/USDJPY
        ONLY (cfg.TREND_SL_REVERSAL_ENABLED), NOT a numbered rule, NOT a
        modification to Rule 4. REASON: with Rule 5/6/7/FLIP disabled on
        these two symbols (2026-08-13's "late signals" fix), a WITH_TREND
        SL used to just sit there until Rule 4's gate cleared on its own
        — no reaction. User: "SL hit hote hi reversal trade open kar do,
        again with fast trailing SL." Mirrors Rule 7's own shape (zero
        confirmation, purely directional, one attempt per DI regime via
        its own trend_reversal_used field) but triggers off a WITH_TREND
        SL instead of a scalp SL, and is called ALONGSIDE Rule 4's own
        gate-setting in _classify_and_record_close — never inside it,
        never touching rule4_gate itself. Sized by the symbol's own
        WITH_TREND SL/TP (_sl_tp_trend) — GBPUSD/USDJPY's flat
        0.00050/0.050 (2026-08-14) — same value a fresh Rule 2 entry
        would use, so this reversal is exactly as tight and trails
        exactly as fast (trail_all_positions() has no mode branch) as
        every other position on these two symbols now does.

        State is only mutated AFTER send_order() confirms a real ticket —
        same confirm-before-mutate pattern as _reverse_scalp(). No
        separate re-arm-on-failure gate (unlike Rule 7's
        _rearm_scalp_after_sl_no_reversal) — kept deliberately simple, as
        asked ("chota sa kaam"); trend_reversal_used just stays False on
        any failed/skipped attempt, so the next WITH_TREND SL on this
        symbol tries again naturally without needing a dedicated gate."""
        if not self.should_take_trade():
            self.state.log("Trend-SL reversal skipped — insufficient margin")
            return
        opposite = 'SELL' if closed_side == 'BUY' else 'BUY'
        sl, tp = _sl_tp_trend(opposite, live_snap.close, live_snap.atr, self.cfg)
        self.state.log(f"WITH_TREND SL -> immediately opening opposite {opposite} [fast-trailing reversal, unconfirmed]")
        ticket = self.send_order(
            opposite, sl, tp, f'TREND_REV_{opposite}', 'WITH_TREND',
            f"Immediate reversal after WITH_TREND {closed_side} stopped out (tight SL, unconfirmed)",
        )
        if ticket is None:
            return  # never opened — trend_reversal_used stays False, next SL tries again
        self.state.trend_reversal_used = True
        self.state.rule3_gate = None  # a fresh entry just opened — old gate is moot
        self.state.rule4_gate = None  # ditto
        self.state.last_bar_time = live_snap.bar_time

    # ---------- order placement / management ----------

    def should_take_trade(self) -> bool:
        info = mt5.account_info()
        if info is None or info.equity <= 0:
            return False
        if info.margin / info.equity <= 0.1:
            return True
        self.state.log("Insufficient margin room")
        return False

    def _build_order_request(self, side: str, sl: float, tp: float, comment: str, margin_mult: float,
                              mode: str = "") -> dict:
        """Shared by send_order()'s first attempt and its retry — margin_mult
        widens the safety margin on the retry (fresh price, wider buffer).
        `mode` is only used to decide SL rounding coarseness (see
        cfg.TREND_SL_FINE_ROUNDING) — everything else about the request is
        mode-agnostic."""
        tick = mt5.symbol_info_tick(self.cfg.SYMBOL)
        if tick is None:
            return None
        digits = self._digits()
        order_type = mt5.ORDER_TYPE_BUY if side == 'BUY' else mt5.ORDER_TYPE_SELL
        price = tick.ask if side == 'BUY' else tick.bid  # what we actually enter at
        # Broker validates stop distance against the OPPOSITE side of the
        # spread from the entry — a BUY's stops are checked against Bid (what
        # it would close at), a SELL's against Ask — not against the entry
        # price itself. Using entry price for both was wrong on any symbol
        # with a wide spread: USA30's spread here is ~3.8 price units, ~6x
        # its own min-stop-distance (0.60), so a stop that looked fine
        # measured from the entry (ask) could still be inside the forbidden
        # zone measured from the broker's real reference (bid).
        stops_ref = tick.bid if side == 'BUY' else tick.ask
        min_dist = self._min_stop_distance() * margin_mult
        if min_dist > 0:
            if side == 'BUY':
                if stops_ref - sl < min_dist:
                    sl = stops_ref - min_dist
                if tp - stops_ref < min_dist:
                    tp = stops_ref + min_dist
            else:
                if sl - stops_ref < min_dist:
                    sl = stops_ref + min_dist
                if stops_ref - tp < min_dist:
                    tp = stops_ref - min_dist
        sl_coarse = not (mode == 'WITH_TREND' and self.cfg.TREND_SL_FINE_ROUNDING)
        return {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.cfg.SYMBOL,
            "volume": float(self.cfg.LOT),  # MT5's API rejects an int here ("Invalid volume argument")
            "type": order_type,
            "price": price,
            "sl": self._round_price(sl, reference=stops_ref, coarse=sl_coarse),
            "tp": self._round_price(tp, reference=stops_ref),
            "magic": randrange(1000000),
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

    def send_order(self, side: str, sl: float, tp: float, comment: str, mode: str, reason: str = "") -> Optional[int]:
        digits = self._digits()
        request = self._build_order_request(side, sl, tp, comment, margin_mult=1.2, mode=mode)
        if request is None:
            self.state.log("No tick data")
            return None
        with _mt5_lock:
            result = mt5.order_send(request)
        if result is None:
            self.state.log(f"Order failed: {mt5.last_error()}")
            return None
        if result.retcode == mt5.TRADE_RETCODE_INVALID_STOPS:
            # On a fast-moving instrument (USA30 confirmed directly via
            # order_check() 2026-08-11: its real minimum stop distance
            # tracks the current SPREAD, not the static trade_stops_level
            # field, and both drift tick to tick) the price can move enough
            # between building this request and the server processing it
            # that even a correctly-clamped SL/TP falls invalid by the time
            # it lands. One retry with a completely fresh tick and a wider
            # (2x) margin — rather than just logging and giving up — is
            # what actually gets it to stick, since the client-side clamp
            # alone can't fully rule out this race.
            self.state.log(f"Order error {result.retcode}: {result.comment} — retrying with fresh price")
            request = self._build_order_request(side, sl, tp, comment, margin_mult=2.0, mode=mode)
            if request is None:
                self.state.log("No tick data on retry")
                return None
            with _mt5_lock:
                result = mt5.order_send(request)
            if result is None:
                self.state.log(f"Order failed on retry: {mt5.last_error()}")
                return None
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            self.state.log(f"Order error {result.retcode}: {result.comment}")
            return None
        self.state.log(
            f"{side} placed order={result.order} SL={request['sl']:.{digits}f} "
            f"TP={request['tp']:.{digits}f} ({comment})"
        )
        # Map mode onto the newest open position ticket
        time.sleep(0.15)
        positions = mt5.positions_get(symbol=self.cfg.SYMBOL) or []
        side_type = mt5.ORDER_TYPE_BUY if side == 'BUY' else mt5.ORDER_TYPE_SELL
        candidates = [p for p in positions if p.type == side_type and p.ticket not in self.state.position_modes]
        if candidates:
            newest = max(candidates, key=lambda p: p.time)
            self.state.position_modes[newest.ticket] = mode
            self.state.position_open_info[newest.ticket] = {
                "reason": reason,
                "opened_at": self._broker_ts_to_local_str(newest.time),
            }
            return newest.ticket
        return result.order

    def _close_ticket(self, position, comment: str) -> bool:
        """Close a single open position immediately at market."""
        tick = mt5.symbol_info_tick(self.cfg.SYMBOL)
        if tick is None:
            return False
        close_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.cfg.SYMBOL,
            "volume": position.volume,
            "type": close_type,
            "position": position.ticket,
            "price": price,
            "magic": randrange(1000000),
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        with _mt5_lock:
            result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            side = "BUY" if position.type == mt5.ORDER_TYPE_BUY else "SELL"
            snap = {
                "sl": position.sl, "tp": position.tp, "price_open": position.price_open,
                "mode": self.state.position_modes.get(position.ticket, "?"),
            }
            self._push_trade_history(position.ticket, side, snap, position.profit, comment)
            self.state.log(f"Closed ticket {position.ticket} ({comment}), profit {position.profit:+.2f}")
            self.state.position_modes.pop(position.ticket, None)
            self.state.position_snapshot.pop(position.ticket, None)
            return True
        self.state.log(f"Close failed {position.ticket}: {getattr(result, 'comment', mt5.last_error())}")
        return False

    def close_positions_of_type(self, order_type: int) -> int:
        positions = mt5.positions_get(symbol=self.cfg.SYMBOL) or []
        closed = 0
        for p in positions:
            if p.type != order_type:
                continue
            if self._close_ticket(p, "FLIP"):
                closed += 1
        return closed

    def trail_all_positions(self):
        """Trails every open position — WITH_TREND, COUNTER_SCALP, and the
        _reverse_scalp() reversal trade alike (corrected 2026-08-11: scalps
        used to be skipped entirely here — 'mode != WITH_TREND: continue' —
        which let a scalp that ran into profit sit untrailed and give it
        all back on a reversal; no reason to protect a WITH_TREND winner
        but not a COUNTER_SCALP one).

        Activation/lock distances are sized off THIS POSITION's own actual
        TP distance (p.tp - p.price_open), not a fixed cfg lookup — every
        symbol currently has SCALP_TP_POINTS == TREND_TP_POINTS so a cfg
        lookup would coincidentally work today, but the reversal trade in
        particular (_reverse_scalp) is always sized scalp-tight even when
        classify_side() labels it 'WITH_TREND' in position_modes, so a
        mode-keyed cfg lookup for tp_dist would silently use the wrong
        number the moment scalp/trend TPs ever diverge for some symbol.
        Reading the real p.tp is correct for all four cases (trend, scalp,
        FLIP, and the with_trend-labelled reversal) with no mode branch at
        all.
        """
        positions = mt5.positions_get(symbol=self.cfg.SYMBOL) or []
        tick = mt5.symbol_info_tick(self.cfg.SYMBOL)
        if tick is None:
            return
        for p in positions:
            if not p.tp:
                continue  # nothing to size the trail against
            mode = self.state.position_modes.get(p.ticket, "")
            # UNIFIED TRAIL, 2026-08-15, requested directly on ALL 6 symbols
            # ("trail sub symbols per aeise hi laga do jeise meine bataya
            # hai") — the three symbol-specific staircase/continuous
            # mechanisms below (_trail_staircase, _trail_staircase_pct,
            # _trail_fixed_points) are no longer selected by any symbol
            # (every TRAIL_STEP_POINTS/TRAIL_STEP_PCT/TRAIL_FIXED_ACTIVATE_POINTS
            # is None now) — kept in the code, unused, in case a future
            # symbol ever needs one of those shapes again; every symbol
            # today falls through to this one CONTINUOUS %-of-TP formula.
            if self.cfg.TRAIL_STEP_POINTS:
                self._trail_staircase(p, tick, mode)
                continue
            if self.cfg.TRAIL_STEP_PCT:
                self._trail_staircase_pct(p, tick, mode)
                continue
            if self.cfg.TRAIL_FIXED_ACTIVATE_POINTS is not None:
                self._trail_fixed_points(p, tick, mode)
                continue
            # CORRECTED, 2026-08-15 (real bug found by the user in the
            # discrete per-symbol staircases this replaces): a discrete
            # staircase only moves SL at fixed jump points and sits FLAT
            # between them — "USA30 ki price ka difference dekho lekin
            # trailing SL aage nahi barh raha hai" (price kept moving but
            # the trailed SL visibly hadn't, between two staircase steps).
            # This formula is CONTINUOUS instead — recomputed fresh from
            # the actual live price every tick, so SL keeps creeping
            # forward as price keeps moving, not just at discrete jumps.
            # Levels set from the user's own worked example (verbatim):
            # "jab yeh 25% ho tab trail 12.5% ho... jab 50% ho tab trail
            # 25% ho... jab 75% ho tab 50% ho jaye." That maps exactly to
            # activate=25% / lock_back=25% (behind live price,
            # continuously) / min_lock=12.5% (floor at first activation,
            # since current-lock_back is 0% right at the 25% activation
            # point) — verified algebraically: 25%->12.5%, 50%->25%,
            # 75%->50%, matching the user's three examples exactly.
            # IMPACT: activates earlier than the old 40% default AND keeps
            # tracking price continuously past that point (not just at
            # fixed jumps) — locks in meaningfully more profit on a strong
            # continuation, at the same trade-off every earlier trail
            # speed-up in this bot has had (possibly exiting sooner on a
            # trade that dips before continuing).
            tp_dist = abs(p.tp - p.price_open)
            activate_at = tp_dist * 0.25  # start trailing 25% of the way to TP
            lock_back = tp_dist * 0.25    # trailed SL stays this far behind current price
            min_lock = tp_dist * 0.125    # guaranteed minimum profit once trailing engages
            if p.type == mt5.ORDER_TYPE_BUY:
                profit_pts = tick.bid - p.price_open
                if profit_pts >= activate_at:
                    nsl = max(tick.bid - lock_back, p.price_open + min_lock)
                    if p.sl == 0 or nsl > p.sl:
                        self._modify_sltp(p.ticket, nsl, p.tp, tick.bid, 'BUY', current_sl=p.sl, mode=mode)
            else:
                profit_pts = p.price_open - tick.ask
                if profit_pts >= activate_at:
                    nsl = min(tick.ask + lock_back, p.price_open - min_lock)
                    if p.sl == 0 or nsl < p.sl:
                        self._modify_sltp(p.ticket, nsl, p.tp, tick.ask, 'SELL', current_sl=p.sl, mode=mode)

    def _trail_staircase(self, p, tick, mode):
        """Symbol-specific staircase trailing (XAUUSD, 2026-08-14,
        requested directly) — the generic trail above waits for 40% of
        TP distance before it even starts (XAUUSD's TP is 5.5, so that's
        2.2 points of room for price to reverse and hit the flat 5.00 SL
        before any protection engages at all). User: "SL baar baar hit
        hona hai... trailing kafi late update ho raha hai" — asked for
        much earlier, much finer-grained locking instead: every
        `cfg.TRAIL_STEP_POINTS` of favorable movement, the SL steps
        forward by `cfg.TRAIL_INCREMENT_POINTS` — starting from the very
        first step (SL moves PAST open price at step 1, not just to
        breakeven). Pure function of current price vs. entry, recomputed
        fresh every tick — no memory of previous steps needed. Reuses
        _modify_sltp()'s existing protections unchanged (min-stop-distance
        clamp, the "never regress" guard added for USDJPY/GBPUSD, the
        "no changes" skip) — this function only supplies a different
        target `nsl`, nothing about how it's sent changes. Scoped via
        cfg.TRAIL_STEP_POINTS being set (XAUUSD only) — every other
        symbol keeps the exact generic trailing behavior, untouched."""
        step = self.cfg.TRAIL_STEP_POINTS
        increment = self.cfg.TRAIL_INCREMENT_POINTS
        if p.type == mt5.ORDER_TYPE_BUY:
            profit_pts = tick.bid - p.price_open
            steps = math.floor(profit_pts / step)
            if steps >= 1:
                nsl = p.price_open + increment * steps
                if p.sl == 0 or nsl > p.sl:
                    self._modify_sltp(p.ticket, nsl, p.tp, tick.bid, 'BUY', current_sl=p.sl, mode=mode)
        else:
            profit_pts = p.price_open - tick.ask
            steps = math.floor(profit_pts / step)
            if steps >= 1:
                nsl = p.price_open - increment * steps
                if p.sl == 0 or nsl < p.sl:
                    self._modify_sltp(p.ticket, nsl, p.tp, tick.ask, 'SELL', current_sl=p.sl, mode=mode)

    def _trail_staircase_pct(self, p, tick, mode):
        """Percentage-of-TP staircase trailing (USA100/USA30, 2026-08-14,
        requested directly) — same non-delayed staircase SHAPE as
        _trail_staircase() above (SL already in profit at step 1), but
        each step/increment is a FRACTION of THIS position's own TP
        distance (cfg.TRAIL_STEP_PCT / TRAIL_INCREMENT_PCT) instead of a
        fixed point value, so it scales with each symbol's own TP size
        automatically. User: "trailing SL ki dynamic increment fast set
        karo... 20% se start karo with each 20% increment... first
        benchmark price reach hote hi TSL profit mein aa jaye" (USA100);
        "50% ka wait na kare balke 25% par upar aa jaye" (USA30, its own
        override — 0.25 instead of the 0.20 default). Reuses
        _modify_sltp()'s existing protections unchanged, same as every
        other trail variant — only supplies a different target `nsl`."""
        tp_dist = abs(p.tp - p.price_open)
        if tp_dist <= 0:
            return
        step = self.cfg.TRAIL_STEP_PCT * tp_dist
        increment = self.cfg.TRAIL_INCREMENT_PCT * tp_dist
        if p.type == mt5.ORDER_TYPE_BUY:
            profit_pts = tick.bid - p.price_open
            steps = math.floor(profit_pts / step)
            if steps >= 1:
                nsl = p.price_open + increment * steps
                if p.sl == 0 or nsl > p.sl:
                    self._modify_sltp(p.ticket, nsl, p.tp, tick.bid, 'BUY', current_sl=p.sl, mode=mode)
        else:
            profit_pts = p.price_open - tick.ask
            steps = math.floor(profit_pts / step)
            if steps >= 1:
                nsl = p.price_open - increment * steps
                if p.sl == 0 or nsl < p.sl:
                    self._modify_sltp(p.ticket, nsl, p.tp, tick.ask, 'SELL', current_sl=p.sl, mode=mode)

    def _trail_fixed_points(self, p, tick, mode):
        """Fixed-POINT continuous trailing (USA500, 2026-08-14, requested
        directly, with an exact worked example): open 7800 -> +1pt profit
        -> SL 7800 (breakeven, "taake loss na ho") -> +2pt profit -> SL
        7801 -> +3pt -> SL 7802, i.e. SL continuously trails
        cfg.TRAIL_FIXED_LOCKBACK_POINTS behind current price once
        cfg.TRAIL_FIXED_ACTIVATE_POINTS of profit is reached, floored at
        cfg.TRAIL_FIXED_MINLOCK_POINTS past entry — same formula SHAPE as
        the generic %-of-TP trail, just with fixed point values instead
        of TP-percentage-derived ones (unlike _trail_staircase(), this is
        NOT a delayed/stepped lock — it moves every tick, continuously
        1:1 with price, matching the worked example exactly: at the
        activation threshold itself, SL lands precisely at breakeven, not
        already past it)."""
        activate = self.cfg.TRAIL_FIXED_ACTIVATE_POINTS
        lockback = self.cfg.TRAIL_FIXED_LOCKBACK_POINTS
        minlock = self.cfg.TRAIL_FIXED_MINLOCK_POINTS or 0.0
        if p.type == mt5.ORDER_TYPE_BUY:
            profit_pts = tick.bid - p.price_open
            if profit_pts >= activate:
                nsl = max(tick.bid - lockback, p.price_open + minlock)
                if p.sl == 0 or nsl > p.sl:
                    self._modify_sltp(p.ticket, nsl, p.tp, tick.bid, 'BUY', current_sl=p.sl, mode=mode)
        else:
            profit_pts = p.price_open - tick.ask
            if profit_pts >= activate:
                nsl = min(tick.ask + lockback, p.price_open - minlock)
                if p.sl == 0 or nsl < p.sl:
                    self._modify_sltp(p.ticket, nsl, p.tp, tick.ask, 'SELL', current_sl=p.sl, mode=mode)

    def _modify_sltp(self, ticket: int, sl: float, tp: float, current_price: float, side: str,
                      current_sl: Optional[float] = None, mode: str = ""):
        """Runs every tick a WITH_TREND position is favorably past the
        trail-activation threshold — a rejected modify here used to fail
        completely silently (no log branch on failure at all), so a
        transient "Invalid stops" (or anything else) left the SL stuck at
        whatever it last successfully reached, with zero visibility that it
        had stopped tracking price at all (found directly: USA30,
        2026-08-11 — SL locked in at +8pts and never moved again even once
        price ran to +35). 2x margin (same as send_order()'s retry tier,
        not its first-attempt 1.2x) since there's no race to be first here
        — this call repeats every tick regardless, so correctness matters
        more than shaving the buffer."""
        digits = self._digits()
        min_dist = self._min_stop_distance() * 2.0
        if min_dist > 0:
            if side == 'BUY' and current_price - sl < min_dist:
                sl = current_price - min_dist
            elif side == 'SELL' and sl - current_price < min_dist:
                sl = current_price + min_dist
        # Found directly, 2026-08-13: USDJPY/GBPUSD trailing SL oscillating
        # backward tick to tick instead of only ever ratcheting forward
        # (e.g. BUY: ...159.388 -> 159.382 -> 159.392 -> 159.369...).
        # trail_all_positions()'s own "nsl > p.sl" guard only checks the
        # RAW, pre-clamp candidate — but since v2.3 flattened these two
        # symbols' TP to a small fixed value, lock_back (0.3x tp_dist) is
        # now often TIGHTER than the broker's real min-stop-distance, so
        # the clamp above engages almost every tick, silently overriding
        # the guarded value with `current_price -+ min_dist` — which
        # moves backward whenever current_price itself pulls back,
        # completely defeating the "only ratchet forward" guarantee the
        # caller thought it already enforced. Re-checked here, AFTER
        # clamping, against the position's actual current SL — the last
        # point before sending, so it catches backward movement from
        # ANY source (this clamp or a future one), not just the specific
        # case that prompted it: if the clamp pulled `sl` backward past
        # what's already on the position, skip sending entirely (keep the
        # existing SL, which is already at least as good) rather than
        # forcibly regress it.
        if current_sl is not None and current_sl != 0:
            if side == 'BUY' and sl < current_sl:
                return
            elif side == 'SELL' and sl > current_sl:
                return
        sl_coarse = not (mode == 'WITH_TREND' and self.cfg.TREND_SL_FINE_ROUNDING)
        rounded_sl = self._round_price(sl, reference=current_price, coarse=sl_coarse)
        rounded_tp = self._round_price(tp, reference=current_price)
        # trail_all_positions() decides to call this based on the RAW,
        # pre-rounding nsl (moves every tick as price moves) vs. the
        # position's real current SL — but once ROUND_STEP or a broker
        # tick-size grid is coarser than that tick-to-tick movement,
        # several different raw nsl values round to the SAME price, which
        # can already be exactly what's on the position. Sending that
        # again gets rejected by the broker as retcode 10025 ("No
        # changes") — found directly on GBPUSD (2026-08-13): logged every
        # tick as "Trail SL FAILED" even though nothing was actually wrong,
        # just spam. Not specific to ROUND_STEP symbols — any symbol's
        # tick-size grid can produce this — so checked here generally: skip
        # the request entirely (and don't log it as a failure) when the
        # rounded target already matches what's on the position.
        tol = 0.5 * (10 ** -digits)
        if current_sl is not None and abs(rounded_sl - current_sl) < tol:
            return
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self.cfg.SYMBOL,
            "position": ticket,
            "sl": rounded_sl,
            "tp": rounded_tp,
            "comment": "Trail",
        }
        with _mt5_lock:
            result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            self.state.log(f"Trail SL ticket={ticket} -> {sl:.{digits}f}")
        elif result and result.retcode == mt5.TRADE_RETCODE_NO_CHANGES:
            # Same benign case as the pre-check above, just reached via a
            # path the pre-check didn't catch (e.g. current_sl wasn't
            # passed) — still not a real failure, don't log it as one.
            pass
        else:
            self.state.log(
                f"Trail SL FAILED ticket={ticket} -> {sl:.{digits}f}: "
                f"{getattr(result, 'retcode', None)} {getattr(result, 'comment', mt5.last_error())}"
            )

    def execute_signal(self, sig: Signal):
        if sig.action == 'HOLD' or sig.action == 'MANAGE':
            return

        if sig.action == 'CLOSE_SELLS_THEN_BUY':
            self.close_positions_of_type(mt5.ORDER_TYPE_SELL)
            time.sleep(0.3)
            if self.should_take_trade():
                self.send_order('BUY', sig.sl, sig.tp, 'FLIP_BUY', 'WITH_TREND', sig.reason)
            return

        if sig.action == 'CLOSE_BUYS_THEN_SELL':
            self.close_positions_of_type(mt5.ORDER_TYPE_BUY)
            time.sleep(0.3)
            if self.should_take_trade():
                self.send_order('SELL', sig.sl, sig.tp, 'FLIP_SELL', 'WITH_TREND', sig.reason)
            return

        if sig.action in ('BUY', 'SELL') and sig.sl is not None and sig.tp is not None:
            if not self.should_take_trade():
                return
            comment = sig.mode[:20]
            self.send_order(sig.action, sig.sl, sig.tp, comment, sig.mode, sig.reason)

    # ---------- main loop ----------

    def _fetch_rates(self) -> Optional[pd.DataFrame]:
        rates = mt5.copy_rates_from_pos(self.cfg.SYMBOL, mt5.TIMEFRAME_M15, 0, cfg.TIMEFRAME_BARS)
        if rates is None or len(rates) < 50:
            return None
        df = pd.DataFrame(rates)
        df.columns = ['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume']
        return df

    def bot_tick(self):
        self.state.attempt += 1
        self.state.connected = is_connected()
        if not self.state.connected:
            _maybe_reconnect()  # see module-level comment — is_connected() can be stale
            return

        tick = mt5.symbol_info_tick(self.cfg.SYMBOL)
        live = {}
        if tick is not None:
            live = {
                "bid": float(tick.bid),
                "ask": float(tick.ask),
                "mid": round((tick.bid + tick.ask) / 2, 2),
                "spread": round(tick.ask - tick.bid, 2),
                "time": datetime.fromtimestamp(tick.time).strftime("%H:%M:%S") if tick.time else "",
            }

        df = self._fetch_rates()
        if df is None:
            self.state.log("Not enough rate data")
            _maybe_reconnect()  # is_connected() said True but the real fetch still failed — stale connection
            with self.state.lock:
                self.state.live = live
                self.state.updated_at = datetime.now().strftime("%H:%M:%S")
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

        # Rule 1 (locked — do not modify without explicit permission): no
        # trade may open on the same candle that was forming at the moment
        # of the most recent start()/restart. Capture that bar_time on the
        # very first tick after start, then wait for a genuinely NEW
        # bar_time before lifting the gate — a real "next candle", not a
        # fixed time delay.
        if self.state.startup_bar_time is None:
            self.state.startup_bar_time = live_snap.bar_time
        if not self.state.startup_gate_cleared and live_snap.bar_time != self.state.startup_bar_time:
            self.state.startup_gate_cleared = True
            self.state.log("Rule 1: startup wait cleared — next candle has begun, normal signal evaluation resumes")
        startup_wait = not self.state.startup_gate_cleared

        # position_snapshot (not position_modes) is the "previously open" set —
        # it's populated for ANY open ticket unconditionally, including ones
        # already open before this process started (e.g. after a restart).
        prev_tracked_tickets = set(self.state.position_snapshot.keys())
        positions = self._refresh_positions()
        current_tickets = {p.ticket for p in positions}
        closed_tickets = prev_tracked_tickets - current_tickets
        for ticket in closed_tickets:
            self._classify_and_record_close(ticket, live_snap, live.get('bid'), live.get('ask'))

        has_buy = any(p.type == mt5.ORDER_TYPE_BUY for p in positions)
        has_sell = any(p.type == mt5.ORDER_TYPE_SELL for p in positions)

        # Track which DI is dominant. A regime change re-arms the
        # counter-scalp so it can only fire once per regime instead of on
        # every stop-out while -DI/+DI stays lopsided.
        if live_snap.di_plus > live_snap.di_minus:
            regime = 'PLUS'
        elif live_snap.di_minus > live_snap.di_plus:
            regime = 'MINUS'
        else:
            regime = self.state.di_regime
        if regime != self.state.di_regime:
            self.state.di_regime = regime
            self.state.scalp_armed = True
            self.state.scalp_reversal_used = False
            self.state.scalp_rearm_gate = None  # regime flip already re-armed it — this gate is moot
            self.state.scalp_reversal_di = None
            self.state.scalp_continuation_gate = None  # regime flip already re-armed it too
            self.state.scalp_no_reversal_gate = None  # ditto
            self.state.trend_reversal_used = False  # new mechanism's own cap, same regime-flip reset
            self.state.rule7_reversal_gate = None  # stale benchmark, regime moved on — XAUUSD only

        self._check_scalp_rearm(live_snap)
        self._check_rule6_gate(live_snap)
        self._check_scalp_no_reversal_gate(live_snap, closed_snap)
        self._check_rule3_gate(live_snap)
        self._check_rule4_gate(live_snap)
        self._check_rule7_reversal_gate(live_snap)

        # Only block a second ENTRY on the same forming M15 — reasons always from live
        already_entered = (
            self.state.last_bar_time is not None
            and live_snap.bar_time == self.state.last_bar_time
        )
        sig = decide(live_snap, closed_snap, self.cfg, has_buy, has_sell, already_entered,
                     self.state.scalp_armed, self.state.rule3_gate, self.state.rule4_gate,
                     self.state.rule7_reversal_gate)

        if startup_wait and sig.action in ('BUY', 'SELL', 'CLOSE_SELLS_THEN_BUY', 'CLOSE_BUYS_THEN_SELL'):
            # Rule 1 — block the order-placing action itself but keep showing
            # what the underlying analysis would otherwise have done, so the
            # dashboard stays informative during the wait.
            sig = Signal(
                'HOLD', 'NONE',
                f"Rule 1: waiting for next candle after bot start — no entry yet | would-be signal: {sig.reason}",
            )

        display = live_snap.to_dict()
        display['signal_close'] = closed_snap.close
        display['signal_bar_time'] = closed_snap.bar_time
        display['decision_source'] = 'LIVE_FORMING_M15'

        with self.state.lock:
            self.state.snapshot = display
            self.state.live = live
            self.state.last_signal = sig.to_dict()
            self.state.last_reason = sig.reason
            self.state.mode = sig.mode
            self.state.digits = self._digits()
            self.state.updated_at = datetime.now().strftime("%H:%M:%S")

        if sig.reason != self.state.last_logged_reason:
            self.state.log(sig.reason)
            self.state.last_logged_reason = sig.reason

        if sig.action in ('BUY', 'SELL', 'CLOSE_SELLS_THEN_BUY', 'CLOSE_BUYS_THEN_SELL'):
            before = len(mt5.positions_get(symbol=self.cfg.SYMBOL) or [])
            self.execute_signal(sig)
            after = len(mt5.positions_get(symbol=self.cfg.SYMBOL) or [])
            # REMOVED 2026-08-13 (requested directly): this used to mark
            # last_bar_time on ANY successful entry/flip, blocking every
            # other rule from re-entering for the rest of that candle even
            # though this generic cap was never one of the numbered rules'
            # own design (Rule 2/5 listed "not already entered this M15
            # candle" as one of their own conditions, but that always meant
            # "not already holding a position" — this generic same-candle
            # block was an unrelated side effect layered on top). Found
            # directly defeating Rule 3's whole point: a WITH_TREND TP that
            # hit 31 seconds into its own candle left `last_bar_time` set
            # for the rest of that candle regardless of whether Rule 3's
            # own gate had already cleared, silently overriding the
            # same-candle re-entry the user explicitly asked Rule 3/6 to
            # allow. `last_bar_time` is now set ONLY by Rule 4's own
            # explicit, locked "block all entries this candle after an
            # SL" behavior (_classify_and_record_close) — untouched here.
            if after > before:
                self.state.rule3_gate = None  # a fresh entry just opened — old gate is moot
                self.state.rule4_gate = None  # ditto
                self.state.scalp_continuation_gate = None  # ditto
                self.state.scalp_no_reversal_gate = None  # ditto
                self.state.rule7_reversal_gate = None  # ditto — XAUUSD only, no-op elsewhere
                if sig.mode == 'COUNTER_SCALP':
                    self.state.scalp_armed = False

        self.trail_all_positions()
        self._refresh_account()
        self._reconcile_commissions()

    def _loop(self):
        self.state.log("Bot loop started")
        if not is_connected():
            connect_mt5()
        self.state.connected = is_connected()
        if self.state.connected:
            try:
                self._sync_trades_from_broker()
            except Exception as e:
                self.state.log(f"History sync skipped: {e}")
            self._sync_stats_from_db()
        while not self._stop_event.is_set():
            if not self.state.running:
                time.sleep(0.5)
                continue
            try:
                self.bot_tick()
                # Re-check against MT5's own history periodically (~every 10
                # min at the default 2s poll) — catches anything the live
                # tick-based close detection missed while still running.
                if self.state.attempt % 300 == 0:
                    self._sync_trades_from_broker()
            except Exception as e:
                self.state.last_error = str(e)
                self.state.log(f"Error: {e}")
                time.sleep(cfg.POLL_SECONDS)
                continue
            time.sleep(cfg.POLL_SECONDS)
        self.state.log("Bot loop stopped")

    def start(self):
        with self.state.lock:
            self.state.running = True
        # Rule 1 (locked — do not modify without explicit permission):
        # re-arm the startup wait on every explicit start — a fresh process
        # launch AND a resume via the dashboard's Start button both count as
        # "bot start/restart".
        self.state.startup_bar_time = None
        self.state.startup_gate_cleared = False
        self._stop_event.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        elif self.state.connected:
            # Thread was already alive (resume-from-Stop, not a fresh process
            # start) — _loop()'s own startup sync only runs once per thread,
            # so re-check here in case anything closed while marked stopped.
            try:
                self._sync_trades_from_broker()
            except Exception as e:
                self.state.log(f"History sync skipped: {e}")
        self.state.log("Bot marked RUNNING")

    def stop(self):
        with self.state.lock:
            self.state.running = False
        self.state.log("Bot marked STOPPED (thread idle)")
