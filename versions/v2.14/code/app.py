import hmac
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

import MetaTrader5 as mt5

import config as cfg
import trade_store
from bot_runner import SymbolBot, connect_mt5, is_connected

app = Flask(__name__)

# Session-based login, 2026-08-16, requested directly — replaces nginx's
# HTTP Basic Auth (2026-08-15) so the dashboard can have a real login
# PAGE and a real EXPIRING session (Basic Auth has neither: no server
# state, browser just resends cached credentials forever). See
# config.py's DASHBOARD_* comment for the full REASON.
#
# app.secret_key signs the session cookie (integrity, not secrecy — the
# cookie's CONTENTS are still visible to the client, just tamper-proof).
# Persisted to a file next to the code rather than regenerated on every
# restart: a fresh key on every restart would silently log everyone out
# every time the bot is restarted for a code update, which has been
# happening often this session — not the intended trade-off (the
# explicit 30-minute idle timeout is the intended expiry mechanism, not
# "restarted the bot").
_SECRET_KEY_PATH = Path(__file__).resolve().parent / ".flask_secret_key"
if _SECRET_KEY_PATH.exists():
    app.secret_key = _SECRET_KEY_PATH.read_text().strip()
else:
    _generated_key = secrets.token_hex(32)
    _SECRET_KEY_PATH.write_text(_generated_key)
    app.secret_key = _generated_key

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,   # JS can never read the session cookie (XSS mitigation)
    SESSION_COOKIE_SECURE=True,     # only sent over HTTPS — the only path real users take (nginx)
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=cfg.SESSION_LIFETIME_MINUTES),
)

# One SymbolBot per entry in config.SYMBOLS — each owns its own state,
# thresholds, and MT5 order-tracking, but all share the single MT5 terminal
# connection (see bot_runner.connect_mt5 / _mt5_lock).
bots = {name: SymbolBot(symbol_cfg) for name, symbol_cfg in cfg.SYMBOLS.items()}


@app.before_request
def _require_login():
    """Every route needs a valid session EXCEPT /login itself and static
    assets. API routes (fetched by the dashboard's own JS, not navigated
    to directly) get a 401 JSON body instead of a redirect — the
    frontend's own fetch wrapper below sends the browser to /login on
    seeing one, since a raw HTTP redirect response to a fetch() call
    isn't something the page could otherwise react to sensibly.

    Role check for the two admin-only control endpoints lives here too
    (not duplicated into each route) — one place decides who can do
    what, matching this project's own stated preference elsewhere for a
    single source of truth over scattered checks."""
    if request.endpoint in ("login", "static"):
        return None
    if not session.get("user"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "not authenticated"}), 401
        return redirect(url_for("login"))
    if request.path in ("/api/start", "/api/stop") and session.get("role") != "admin":
        return jsonify({"error": "forbidden — view-only account"}), 403
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        # hmac.compare_digest for the password specifically — constant-time,
        # avoids leaking password length/prefix via response timing.
        if username == cfg.DASHBOARD_ADMIN_USERNAME and hmac.compare_digest(password, cfg.DASHBOARD_ADMIN_PASSWORD):
            session.clear()
            session["user"] = username
            session["role"] = "admin"
            session.permanent = True
            return redirect(url_for("dashboard"))
        if username == cfg.DASHBOARD_GUEST_USERNAME and hmac.compare_digest(password, cfg.DASHBOARD_GUEST_PASSWORD):
            session.clear()
            session["user"] = username
            session["role"] = "guest"
            session.permanent = True
            return redirect(url_for("dashboard"))
        error = "Invalid username or password"
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


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
        {"name": "Trend direction — live price vs BOTH EMAs takes priority (2026-08-14); falls back to EMA50 vs EMA200 only when price straddles them; NEUTRAL trend takes no action", "check": all_true},
        {"name": "ADX minimum gate (cfg.ADX_MIN) — WITH_TREND and scalp (removed from scalp 2026-08-12, re-added 2026-08-13)",
         "check": lambda n: cfg.SYMBOLS[n].ADX_MIN is not None},
        {"name": "WITH_TREND entry: DI aligned + RSI band + last CLOSED candle color + momentum_gate", "check": all_true},
        {"name": "WITH_TREND SL sizing (ATR x TREND_SL_ATR_MULT, or FIXED_SL_POINTS override)",
         "check": lambda n: cfg.SYMBOLS[n].TREND_SL_ATR_MULT is not None or cfg.SYMBOLS[n].FIXED_SL_POINTS is not None},
        {"name": "WITH_TREND TP — fixed points (cfg.TREND_TP_POINTS)",
         "check": lambda n: cfg.SYMBOLS[n].TREND_TP_POINTS is not None},
        {"name": "Scalp entry: DI opposes trend + RSI band + ATR strong + scalp_armed (GBPUSD/USDJPY: DISABLED 2026-08-14 — see Rule 5 card)",
         "check": lambda n: cfg.SYMBOLS[n].SCALPING_ENABLED},
        {"name": "Scalp SL sizing (max(ATR x SCALP_SL_ATR_MULT, SCALP_SL_FLOOR), or FIXED_SL_POINTS override) — moot where scalping is disabled",
         "check": lambda n: cfg.SYMBOLS[n].SCALPING_ENABLED and (
             (cfg.SYMBOLS[n].SCALP_SL_ATR_MULT is not None and cfg.SYMBOLS[n].SCALP_SL_FLOOR is not None)
             or cfg.SYMBOLS[n].FIXED_SL_POINTS is not None)},
        {"name": "Scalp TP — fixed points (cfg.SCALP_TP_POINTS) — moot where scalping is disabled",
         "check": lambda n: cfg.SYMBOLS[n].SCALPING_ENABLED and cfg.SYMBOLS[n].SCALP_TP_POINTS is not None},
        {"name": "Rolling-DI + last-CLOSED-candle momentum_gate after a WITH_TREND close (SL or TP)", "check": all_true},
        {"name": "Scalp TP -> continuation gate (blocks re-arming same-candle, needs new closed candle) — moot where scalping is disabled",
         "check": lambda n: cfg.SYMBOLS[n].SCALPING_ENABLED},
        {"name": "Scalp SL -> immediate reversal, capped 1/DI regime; every non-open exit gated (no stuck scalp_armed) — moot where scalping is disabled",
         "check": lambda n: cfg.SYMBOLS[n].SCALPING_ENABLED},
        {"name": "FLIP — trend reversal closes an opposite scalp and opens a full-size WITH_TREND (GBPUSD/USDJPY: DISABLED 2026-08-14)",
         "check": lambda n: cfg.SYMBOLS[n].FLIP_ENABLED},
        {"name": "Trailing SL on every open position, sized off that position's own actual TP distance — UNIFIED 2026-08-15, all 6 symbols identical: continuous %-of-TP trail, activate=25%/lock_back=25%/min_lock=12.5% (replaced 3 earlier symbol-specific staircase/continuous variants; see docs)", "check": all_true},
        {"name": "Fixed SL/TP override bypassing ATR sizing entirely (FIXED_SL_POINTS = Rule 2/WITH_TREND)",
         "check": lambda n: cfg.SYMBOLS[n].FIXED_SL_POINTS is not None},
        {"name": "Rule 7 (reversal) SL — independent of Rule 5 since 2026-08-14 (REVERSAL_FIXED_SL_POINTS when set, else falls back to Rule 5's own value)",
         "check": all_true},
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
    # Rule 5 (and 6/7, which need a scalp position to exist at all) is
    # disabled per-symbol via cfg.SCALPING_ENABLED (GBPUSD/USDJPY,
    # 2026-08-14 — see Rule 5's own card for the full reason). Computed
    # live here, same verified-not-typed guarantee as every other row.
    scalp_symbols = {n: cfg.SYMBOLS[n].SCALPING_ENABLED for n in names}
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
                "GBPUSD/USDJPY only, 2026-08-14 (cfg.TREND_SL_REVERSAL_ENABLED): an ADDITIONAL, separate, NOT-a-numbered-rule mechanism also fires here, alongside (never inside) this rule's own gate-setting above — an immediate, zero-confirmation reversal into the opposite side, sized by this symbol's own flat WITH_TREND SL/TP, capped at one attempt per DI regime. See docs' \"New mechanism\" write-up. Every other symbol: unaffected, this bullet does nothing.",
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
                "GBPUSD/USDJPY: Rule 5 (and by extension Rule 6/7, which need a scalp position to exist at all) DISABLED entirely, 2026-08-14, requested directly. REASON: user reported these two symbols taking \"late signals\" and losing money; investigation (real trade data, no rule changes at the time) found Rule 7 (reversal) and FLIP at 0% win rate on both symbols, and Rule 5 (scalp) as the single biggest $ loss contributor on both — every Rule 7/FLIP entry landed 33-884 seconds INTO its M15 candle (reactive, not anchored to a candle boundary like Rule 2 is), which is the literal \"late signal\" being described. IMPACT: GBPUSD/USDJPY now only ever trade WITH_TREND (Rule 2) — this removes those loss sources, but also removes whatever wins Rule 5/FLIP occasionally produced, and means these two symbols simply sit flat during stretches where Rule 2 isn't confirmed. Every other symbol is completely unaffected — `cfg.SCALPING_ENABLED` defaults `True` everywhere else.",
                "GBPUSD/USDJPY FOLLOW-UP, 2026-08-14: Rule 2 alone was still losing even with Rule 5/6/7/FLIP off (GBPUSD -361/14, USDJPY -145.28/8). User: \"in ki stats kisi kaam ke nahi... yeh signal ghalat time per le rahe hein\" — 4 changes to Rule 2/4 instead of re-enabling anything: SL halved (0.00100->0.00050 GBPUSD, 0.100->0.050 USDJPY), TP cut to match (1:1), faster trailing, and a brand-new zero-confirmation reversal-on-SL mechanism added (see Rule 4's card). FOLLOW-UP 2, 2026-08-15: USDJPY's SL/TP raised again 0.050->0.075 (\"itna chota ho gaya hai trail kaam hi nahi kare ga\") — too small for the trail to have meaningful room; GBPUSD's 0.00050 untouched. Trailing itself: see the trailing row above (unified across all 6 symbols same day). Rule 5's own entry conditions above are untouched — it's still fully disabled on these two, this follow-up only touched Rule 2/4's sizing and the trailing mechanism.",
            ],
            "applies": scalp_symbols,
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
                "GBPUSD/USDJPY: moot — Rule 5 disabled means no scalp position ever opens, so this rule's own trigger (a scalp TP) can never fire on these two symbols. See Rule 5's card.",
            ],
            "applies": scalp_symbols,
        },
        {
            "number": 7,
            "title": "Scalp SL hit",
            "checks": [
                "Trade recorded to history as a loss.",
                "Triggers an immediate reversal attempt into the opposite side. Basis is purely DIRECTIONAL — there is NO RSI check, NO candle-color check, and NO DI-cross confirmation, explicitly a zero-confirmation reactive trade.",
                "The reversal's SL/TP are sized by their OWN dedicated function (strategy._sl_tp_reversal, since 2026-08-14), independent of Rule 5's scalp sizing — CHANGED 2026-08-14, requested directly: previously this always inherited Rule 5's exact SL (same shared function), so the two could never differ; user caught this as an isolation violation when asked for USA500/USA30 to have genuinely different Rule 5 vs. Rule 7 SL values. cfg.REVERSAL_FIXED_SL_POINTS is checked FIRST; only falls back to Rule 5's own value when a symbol hasn't been given its own reversal number. Sized regardless of which mode label classify_side() assigns it internally for tracking purposes (usually WITH_TREND-aligned, since the opposite of a counter-trend scalp is normally the trend direction) — a deliberate cap on the risk of an unconfirmed trade. It trails like every other open position once open, sized off its OWN actual TP distance, not its mode label.",
                "The reversal attempt itself is gated by three preconditions: the one-reversal-per-DI-regime cap not already used, should_take_trade() (margin) passing, and send_order() actually confirming a real ticket. The cap is only consumed, and old gates only cleared, once a real ticket is confirmed open — a blocked or failed attempt never burns it.",
                "If the reversal's TP hits: scalp is explicitly re-armed. Unlike an ordinary WITH_TREND TP (where scalp is typically already armed), this one follows directly from the scalp SL that disarmed it, so nothing else re-arms it without this step.",
                "If the reversal's SL ALSO hits (scalp and its reversal both stopped out): a rolling-DI benchmark is set for the scalp side — benchmark = the stronger of the two failure-point DI readings (scalp's own SL, and the reversal's SL). Re-arms early via EITHER DI crossing that benchmark, OR DI rising 2 candles in a row, whichever comes first.",
                "Once the scalp side re-arms this way, the next scalp trade is a normal continuation — it independently needs every Scalp entry check, and if it eventually hits TP, Scalp TP hit's own rules apply to it.",
                "The one-reversal-attempt-per-DI-regime cap itself is unchanged — deliberately kept, to preserve the reversal's risk-capped, zero-confirmation design intent.",
                "If the reversal does NOT end up actually opening a position at all — cap already used this regime, insufficient margin, or the order itself fails — falls through to its own separate, not-yet-formalized re-arm gate.",
                "GBPUSD/USDJPY: moot — Rule 5 disabled means no scalp position ever opens, so this rule's own trigger (a scalp SL) can never fire on these two symbols. See Rule 5's card.",
            ],
            "applies": scalp_symbols,
        },
    ]


@app.route("/")
def dashboard():
    # The page itself (not just /api/*) needs no-store too — without it the
    # browser can keep serving a stale cached copy of the HTML on a normal
    # refresh even after app.py has restarted with new template content
    # (found directly: 2026-08-12, user restarted the process but the new
    # "Confirmed rules" section still didn't show up in the browser).
    #
    # is_guest, 2026-08-15, requested directly: "guest k liye rules wala
    # part hide kerdo totally". UPDATED 2026-08-16: was read from an
    # nginx-set X-Auth-User header (back when nginx did the authenticating
    # via Basic Auth) — now read straight from the Flask session set by
    # /login, since auth moved into the app itself. Same behavior, same
    # role names ("admin"/"guest"), just sourced from `session` instead
    # of a request header — _require_login() above already guarantees
    # `session["role"]` exists by the time this route body runs.
    is_guest = session.get("role") == "guest"
    html = render_template(
        "dashboard.html", symbols=list(bots.keys()),
        rules=_build_rule_matrix(), process_rules=_build_rules(),
        is_guest=is_guest, current_user=session.get("user"),
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
