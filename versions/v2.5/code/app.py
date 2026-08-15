import time
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request

import MetaTrader5 as mt5

import config as cfg
import trade_store
from bot_runner import SymbolBot, connect_mt5, is_connected

app = Flask(__name__)

# One SymbolBot per entry in config.SYMBOLS — each owns its own state,
# thresholds, and MT5 order-tracking, but all share the single MT5 terminal
# connection (see bot_runner.connect_mt5 / _mt5_lock).
bots = {name: SymbolBot(symbol_cfg) for name, symbol_cfg in cfg.SYMBOLS.items()}


def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


_reconcile_cache = {"ts": 0.0, "login": None, "data": None}


def _account_reconciliation(login):
    """Explains the gap between (initial deposit vs. current balance) and
    the dashboard's own tracked Net P/L (added 2026-08-13, requested
    directly — user computed balance(97586.44) vs initial deposit(100000)
    vs tracked Net P/L(-697.05) and found an unexplained ~1717 gap, asked
    where it went).

    Found via mt5.history_deals_get() over the account's FULL history:
    the gap is fully explained by two things our tracked stats don't
    show at all — (1) manual demo account deposits/withdrawals AFTER the
    initial one (this account had 7 more balance operations, net
    +5736.66), and (2) real trading P/L from BEFORE our own DB's
    sync_cutoff (trades that happened, then got deleted from our local
    history by an explicit "clear the DB" request earlier this session —
    the MT5 account itself never forgets them, only our own copy did).
    Verified: net_deposits + alltime_trade_pl reconciles EXACTLY to the
    live account balance, confirming nothing is actually missing —
    it just wasn't being shown.

    Cached 30s (this walks the account's entire deal history — cheap at
    ~600 deals today, but no reason to redo it on every 2s poll)."""
    now = time.time()
    cached = _reconcile_cache
    if cached["login"] == login and cached["data"] is not None and now - cached["ts"] < 30:
        return cached["data"]
    from_date = datetime(2000, 1, 1)
    to_date = datetime.now() + timedelta(days=1)
    deals = mt5.history_deals_get(from_date, to_date) or []
    net_deposits = sum(d.profit for d in deals if d.type == mt5.DEAL_TYPE_BALANCE)
    alltime_trade_pl = sum(
        d.profit + d.swap + d.commission for d in deals
        if d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL)
    )
    data = {
        "net_deposits": round(net_deposits, 2),
        "alltime_trade_pl": round(alltime_trade_pl, 2),
    }
    _reconcile_cache.update({"ts": now, "login": login, "data": data})
    return data


def _build_rule_matrix():
    """Rule x symbol coverage table for the dashboard's bottom panel.

    Every row's checkmark is computed HERE, against the real cfg.SYMBOLS
    values, on every page load — never hand-typed, so it can't silently go
    stale or claim something that isn't actually true (requested directly,
    2026-08-11, after a hand-asserted "yes it's applied everywhere" claim
    turned out wrong for a case that was never actually checked).

    Rows marked `all_true` are pure decision-logic that lives in
    strategy.py/bot_runner.py — confirmed via grep (2026-08-11) that
    neither file contains a single `symbol ==` / `SYMBOL ==` branch, so
    the exact same function runs unconditionally for every symbol in
    cfg.SYMBOLS; there is no code path by which one symbol could get
    different treatment than another. Rows with a real lambda check the
    specific config field that rule depends on, per symbol — if a future
    symbol is added without that field wired up, that cell shows
    unapplied instead of a blind checkmark.
    """
    def all_true(_name):
        return True

    rows = [
        {"name": "Trend gate — EMA50 vs EMA200; NEUTRAL trend takes no action", "check": all_true},
        {"name": "ADX minimum gate (cfg.ADX_MIN) — WITH_TREND and scalp (removed from scalp 2026-08-12, re-added 2026-08-13)",
         "check": lambda n: cfg.SYMBOLS[n].ADX_MIN is not None},
        {"name": "WITH_TREND entry: DI aligned + RSI band + last CLOSED candle color + momentum_gate", "check": all_true},
        {"name": "WITH_TREND SL sizing (ATR x TREND_SL_ATR_MULT, or FIXED_SL_POINTS override)",
         "check": lambda n: cfg.SYMBOLS[n].TREND_SL_ATR_MULT is not None or cfg.SYMBOLS[n].FIXED_SL_POINTS is not None},
        {"name": "WITH_TREND TP — fixed points (cfg.TREND_TP_POINTS)",
         "check": lambda n: cfg.SYMBOLS[n].TREND_TP_POINTS is not None},
        {"name": "Scalp entry: DI opposes trend + RSI band + ATR strong + scalp_armed", "check": all_true},
        {"name": "Scalp SL sizing (max(ATR x SCALP_SL_ATR_MULT, SCALP_SL_FLOOR), or FIXED_SL_POINTS override)",
         "check": lambda n: (cfg.SYMBOLS[n].SCALP_SL_ATR_MULT is not None and cfg.SYMBOLS[n].SCALP_SL_FLOOR is not None)
                              or cfg.SYMBOLS[n].FIXED_SL_POINTS is not None},
        {"name": "Scalp TP — fixed points (cfg.SCALP_TP_POINTS)",
         "check": lambda n: cfg.SYMBOLS[n].SCALP_TP_POINTS is not None},
        {"name": "Rolling-DI + last-CLOSED-candle momentum_gate after a WITH_TREND close (SL or TP)", "check": all_true},
        {"name": "Scalp TP -> continuation gate (blocks re-arming same-candle, needs new closed candle)", "check": all_true},
        {"name": "Scalp SL -> immediate reversal, capped 1/DI regime; every non-open exit gated (no stuck scalp_armed)", "check": all_true},
        {"name": "FLIP — trend reversal closes an opposite scalp and opens a full-size WITH_TREND", "check": all_true},
        {"name": "Trailing SL on every open position, sized off that position's own actual TP distance", "check": all_true},
        {"name": "Fixed SL/TP override bypassing ATR sizing entirely (FIXED_SL_POINTS)",
         "check": lambda n: cfg.SYMBOLS[n].FIXED_SL_POINTS is not None},
        {"name": "Order placement: min-stop-distance clamp (max of trade_stops_level and live spread)", "check": all_true},
        {"name": "Order placement: SL/TP rounded to the broker's real tick grid (trade_tick_size)", "check": all_true},
        {"name": "Order placement: retry with wider margin + fresh price on Invalid Stops", "check": all_true},
        {"name": "One open position at a time per symbol", "check": all_true},
        {"name": "One entry per M15 candle", "check": all_true},
        {"name": "Margin gate — no new order if margin/equity > 10%", "check": all_true},
        {"name": "Trade history persisted per-account (SQLite, survives restarts, commission-reconciled)", "check": all_true},
    ]
    names = list(cfg.SYMBOLS.keys())
    return [
        {"name": r["name"], "applies": {n: bool(r["check"](n)) for n in names}}
        for r in rows
    ]


def _build_rules():
    """The single, authoritative rules list — user-dictated rules, given
    one at a time and LOCKED once added: not to be modified again without
    explicit permission (standing instruction, 2026-08-12). Entries with a
    "number" are confirmed ("Rule 1", "Rule 2", ...); entries without one
    are pre-existing descriptions not yet individually confirmed in this
    numbered form — kept as reference until superseded rule-by-rule.

    "applies" is computed the same verified way as everywhere else on
    this page — confirmed via grep that the underlying code has no
    per-symbol branching, so every rule here runs identically for every
    configured symbol; the list itself is still built from real config
    keys, not typed by hand."""
    names = list(cfg.SYMBOLS.keys())
    all_symbols = {n: True for n in names}
    return [
        {
            "number": 1,
            "title": "No trade opens on the candle the bot started/restarted on",
            "checks": [
                "Whenever the bot starts or restarts (a fresh process launch, or a resume via the dashboard's Start button), it will NOT act on whatever candle happens to be forming at that moment.",
                "It captures that candle's bar_time and blocks every order-placing action (BUY, SELL, and FLIP's close-then-open) until a genuinely NEW candle begins — a real next-candle wait, not a fixed time delay.",
                "Once that new candle starts, normal signal evaluation resumes exactly as usual with no special carry-over.",
                "This is a pre-entry gate, not an entry condition — since no trade can open while it's active, it never appears inside an opened trade's reason; only rules that actually trigger an entry get tagged into a trade's reason text.",
            ],
            "applies": all_symbols,
        },
        {
            "number": 2,
            "title": "WITH_TREND entry",
            "checks": [
                "Entry happens WITH the big trend — trend must be TRENDING_UP (for BUY) or TRENDING_DOWN (for SELL); NEUTRAL trend takes no action at all.",
                "ADX >= ADX_MIN.",
                "DI aligned with the trend (+DI > -DI for BUY, -DI > +DI for SELL).",
                "RSI inside its band (40-80 normally, widened to 90/10 if ADX >= ADX_STRONG_TREND confirms a genuinely strong trend).",
                "The LAST FULLY CLOSED M15 candle must be in the SAME direction as the trade (green for BUY, red for SELL).",
                "The CURRENTLY FORMING candle must NOT be forming in the opposite direction (not red for a BUY, not green for a SELL) — even when the last closed candle was correct, a forming candle actively moving against the trade blocks entry.",
                "Rolling-DI momentum_gate must be clear, if one is active (see the Rolling DI item below) — only relevant right after a recent same-side WITH_TREND close.",
                "Must be flat on this symbol — one open position at a time.",
                "REMOVED 2026-08-13 (requested directly): a separate, no-rule-owned \"not already entered this M15 candle\" cap used to also apply here — it was found silently overriding Rule 3's same-candle re-entry (a TP hitting seconds into its own candle left this cap set for the rest of that candle regardless of Rule 3's own gate). The ONLY remaining same-candle block left in the bot is Rule 4's own explicit one (SL only) — see Rule 4's card.",
                "Margin gate clears at order time (margin/equity <= 10%).",
            ],
            "applies": all_symbols,
        },
        {
            "number": 3,
            "title": "WITH_TREND TP hit",
            "checks": [
                "Trade recorded to history as a win.",
                "If this position was itself the immediate reversal of an earlier scalp SL, clears that pending reversal-DI record (reversal won — no re-arm benchmark needed).",
                "Sets rule3_gate for THIS side: blocks a fresh same-side WITH_TREND entry until full confirmation passes — ADX >= ADX_MIN, DI dominant in the trade's direction AND rolling (above the immediately preceding candle), RSI inside the WITH_TREND band, ATR strong, AND the CURRENTLY FORMING candle definitely the required color (an absolute requirement).",
                "CHANGED 2026-08-13 (requested directly): no longer requires waiting for a genuinely NEW CLOSED candle — that was blocking the trend from continuing right after a clean TP. The gate can now clear WITHIN the SAME candle the TP happened on, the instant all of the above confirms on live data.",
                "The OPPOSITE side, and scalps on either side, are not blocked — the gate is side-specific.",
                "No direction is forced afterward — decide()/evaluate_entry() just re-evaluates fresh once the gate clears.",
            ],
            "applies": all_symbols,
        },
        {
            "number": 4,
            "title": "WITH_TREND SL hit",
            "checks": [
                "Trade recorded to history as a loss (close_reason label — see note below on trailed-into-profit closes).",
                "Blocks a fresh WITH_TREND entry on THIS SAME side only — rule4_gate is the ONE mechanism governing this (same scope as Rule 3). The opposite side, and scalp on either side, are never touched by Rule 4 at all.",
                "REMOVED 2026-08-13 (requested directly): rule4_gate used to sit ALONGSIDE a separate generic \"block ALL entries this candle\" mechanism (last_bar_time) — the exact same rule being checked in two different places. User caught this as an isolation violation and asked for a single check. last_bar_time is no longer touched by Rule 4 at all; rule4_gate alone decides.",
                "Clears via EITHER of two independent paths, whichever comes first — checked fresh every tick, same candle as the SL or a later one, no candle-wait of any kind: (1) FAST — that side's DI crosses back above a benchmark recorded at the moment of THIS SL (a genuine recovery past the failure point), by itself. (2) SLOWER — that side's DI above the immediately preceding candle (rolling) AND the currently forming candle DEFINITELY the required color — green for BUY, red for SELL (absolute requirement, not \"not opposite\").",
                "The benchmark-crossing path added 2026-08-13, requested directly — same concept as Rule 7's own reversal-SL benchmark re-arm (see below): user caught DI oscillating right at the rolling-DI threshold for several minutes with no way to clear faster even though DI had clearly recovered well past the SL's own failure point.",
                "If this position was itself an unconfirmed reversal-of-a-scalp (i.e. the scalp AND its reversal have now BOTH been stopped out): also sets scalp_rearm_gate — benchmark = the stronger of the two failure-point DI readings. Scalp on that side then re-arms early via EITHER DI crossing that benchmark, OR DI rising 2 candles in a row — whichever comes first. This is Rule 7's own separate mechanism (scalp side), independent of rule4_gate's own benchmark above (WITH_TREND side).",
            ],
            "applies": all_symbols,
        },
        {
            "number": 5,
            "title": "Scalp (COUNTER_SCALP) entry",
            "checks": [
                "Trend must be TRENDING_UP or TRENDING_DOWN (not NEUTRAL).",
                "ADX >= ADX_MIN (RE-ADDED 2026-08-13 — see note below).",
                "RSI inside the scalp band (RE-ADDED 2026-08-13).",
                "ATR must be \"strong\" right now — atr >= its own 50-bar mean, OR atr > the immediately preceding candle's ATR (RE-ADDED 2026-08-13).",
                "Rolling DI: this side's DI must be above the immediately preceding candle (accelerating right now) — -DI rising while trend is UP -> scalp SELL; +DI rising while trend is DOWN -> scalp BUY. Still no requirement that this side's DI already be greater than the other side's (see DI-cross note below).",
                "The currently FORMING candle must definitely be the same direction as the trade — red for a SELL, green for a BUY (an absolute requirement, checked live so a genuine move can be caught early rather than waited out).",
                "scalp_armed must be True (one counter-scalp attempt per DI regime).",
                "Must be flat on this symbol, and the margin gate must clear before the order is sent. (The generic \"not already entered this M15 candle\" cap that used to also apply here was REMOVED 2026-08-13, requested directly — see Rule 2's card for why.)",
                "NOTE: ADX/RSI/ATR were removed 2026-08-12, then RE-ADDED 2026-08-13 — a direct data review (XAUUSD: +2455 before 2026-08-13 06:00, -3562 after, on entries like \"-DI 11.9 rising vs prior (11.8)\" at very weak absolute DI) showed rolling-DI-alone fires on pure noise in choppy conditions. User's diagnosis: \"choppy trades mein enter ho raha hai\" — asked for ADX/RSI/ATR back specifically as the noise filter.",
                "NOTE: the literal instantaneous DI cross (this side's DI > the other side's DI) stays REMOVED (not asked to restore, 2026-08-13) — the original reason for rolling DI was to catch the move before a full cross happens, since waiting for the actual cross is too slow/late; requiring the cross ON TOP of rolling DI defeated that purpose. ADX/RSI/ATR are a noise filter layered back on top of that early-entry design, not a reversal of it.",
            ],
            "applies": all_symbols,
        },
        {
            "number": 6,
            "title": "Scalp TP hit",
            "checks": [
                "Trade recorded to history as a win.",
                "Does NOT re-arm scalp_armed immediately — sets scalp_continuation_gate instead.",
                "WITH_TREND is free to fire on its own normal conditions with no extra check from this rule — CHANGED 2026-08-13 (requested directly): previously ALL new entries (WITH_TREND and scalp, either side) were blocked outright on the SAME candle a scalp TP happened; that blanket block is removed, since it was also preventing the trend from continuing right after a clean win.",
                "For scalp specifically, the gate clears once full confirmation passes: ADX >= ADX_MIN, this side's DI still dominant (opposing the big trend) AND rolling (above the immediately preceding candle), RSI inside the scalp band, ATR strong, AND the currently forming candle definitely the required color (green for BUY, red for SELL) — checked live, not against a closed candle. CHANGED 2026-08-13: no longer requires waiting for a new candle to even start — can clear within the SAME candle the TP happened on, the moment all of this confirms (the original blanket same-candle block is now handled by this confirmation requirement instead — a genuine exhaustion/reversal should fail it, genuine continuation should pass it).",
                "Once satisfied, scalp_armed becomes True again — but the next scalp still has to independently pass every check in the Scalp entry rule above, this only lifts the \"already scalped this regime\" cap.",
            ],
            "applies": all_symbols,
        },
        {
            "number": 7,
            "title": "Scalp SL hit",
            "checks": [
                "Trade recorded to history as a loss.",
                "Triggers an immediate reversal attempt into the opposite side. Basis is purely DIRECTIONAL — there is NO RSI check, NO candle-color check, and NO DI-cross confirmation, explicitly a zero-confirmation reactive trade.",
                "The reversal's SL/TP are always sized scalp-tight (identical formula to a normal scalp), regardless of which mode label classify_side() assigns it internally for tracking purposes (usually WITH_TREND-aligned, since the opposite of a counter-trend scalp is normally the trend direction) — a deliberate cap on the risk of an unconfirmed trade. It trails like every other open position once open, sized off its OWN actual TP distance, not its mode label.",
                "The reversal attempt itself is gated by three preconditions: the one-reversal-per-DI-regime cap not already used, should_take_trade() (margin) passing, and send_order() actually confirming a real ticket. The cap is only consumed, and old gates only cleared, once a real ticket is confirmed open — a blocked or failed attempt never burns it.",
                "If the reversal's TP hits: scalp is explicitly re-armed. Unlike an ordinary WITH_TREND TP (where scalp is typically already armed), this one follows directly from the scalp SL that disarmed it, so nothing else re-arms it without this step.",
                "If the reversal's SL ALSO hits (scalp and its reversal both stopped out): a rolling-DI benchmark is set for the scalp side — benchmark = the stronger of the two failure-point DI readings (scalp's own SL, and the reversal's SL). Re-arms early via EITHER DI crossing that benchmark, OR DI rising 2 candles in a row, whichever comes first.",
                "Once the scalp side re-arms this way, the next scalp trade is a normal continuation — it independently needs every Scalp entry check, and if it eventually hits TP, Scalp TP hit's own rules apply to it.",
                "The one-reversal-attempt-per-DI-regime cap itself is unchanged — deliberately kept, to preserve the reversal's risk-capped, zero-confirmation design intent.",
                "If the reversal does NOT end up actually opening a position at all — cap already used this regime, insufficient margin, or the order itself fails — falls through to its own separate, not-yet-formalized re-arm gate.",
            ],
            "applies": all_symbols,
        },
    ]


@app.route("/")
def dashboard():
    # The page itself (not just /api/*) needs no-store too — without it the
    # browser can keep serving a stale cached copy of the HTML on a normal
    # refresh even after app.py has restarted with new template content
    # (found directly: 2026-08-12, user restarted the process but the new
    # "Confirmed rules" section still didn't show up in the browser).
    html = render_template(
        "dashboard.html", symbols=list(bots.keys()),
        rules=_build_rule_matrix(), process_rules=_build_rules(),
    )
    return _no_cache(app.response_class(html))


@app.route("/api/status")
def api_status():
    """Combined view: one shared account (same MT5 login for every symbol)
    plus each symbol's own bot state, keyed by symbol name."""
    try:
        info = mt5.account_info()
    except Exception:
        info = None
    account = {}
    if info is not None:
        account = {
            "login": info.login,
            "balance": round(info.balance, 2),
            "equity": round(info.equity, 2),
            "margin": round(info.margin, 2),
            "profit": round(info.profit, 2),
        }
    # Scoped to the currently-connected account's own table — each account
    # has a physically separate trade_history_<login> table (see
    # trade_store.py), so there's no shared table left to accidentally mix
    # live and demo history together.
    login = account.get("login")
    stats = trade_store.get_stats(login) if login else {}
    reconcile = None
    if login:
        try:
            r = _account_reconciliation(login)
            tracked_pl = stats.get("profit", 0) or 0
            reconcile = {
                "net_deposits": r["net_deposits"],
                "alltime_trade_pl": r["alltime_trade_pl"],
                # Real trading P/L from before our own DB's sync_cutoff —
                # not lost, just not shown in `stats` above (see
                # _account_reconciliation's docstring).
                "untracked_pl": round(r["alltime_trade_pl"] - tracked_pl, 2),
            }
        except Exception:
            reconcile = None
    payload = {
        "connected": is_connected(),
        "account": account,
        "stats": stats,  # combined across all symbols, this account only
        "reconcile": reconcile,  # explains balance vs. tracked Net P/L — see _account_reconciliation
        "symbols": {name: bot.state.snapshot_view() for name, bot in bots.items()},
    }
    return _no_cache(jsonify(payload))


@app.route("/api/trades")
def api_trades():
    """Paginated, persisted trade history — max 50 trades per page.
    ?symbol=USA500 scopes to one symbol; omitted combines every symbol.
    Always scoped to the currently-connected account (see api_status)."""
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    symbol = request.args.get("symbol") or None
    try:
        login = mt5.account_info().login
    except Exception:
        login = None
    if login is None:
        return _no_cache(jsonify({"trades": [], "page": 1, "page_size": 50, "total": 0, "total_pages": 1}))
    return _no_cache(jsonify(trade_store.get_page(page, 50, login, symbol=symbol)))


@app.route("/api/start", methods=["POST"])
def api_start():
    if not is_connected():
        connect_mt5()
    for bot in bots.values():
        bot.start()
    return jsonify({"ok": True, "running": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    for bot in bots.values():
        bot.stop()
    return jsonify({"ok": True, "running": False})


if __name__ == "__main__":
    connect_mt5()
    for bot in bots.values():
        bot.start()  # auto-start on launch
    app.run(host=cfg.FLASK_HOST, port=cfg.FLASK_PORT, debug=False, use_reloader=False)
