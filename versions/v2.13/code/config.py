# MT5 / bot settings — edit here only (not in the UI)

# MT5_LOGIN = 198433334
MT5_LOGIN = 49825877
MT5_PASSWORD = "Prison3R!"
# MT5_SERVER = "HFMarketsGlobal-Live16"
MT5_SERVER = "HFMarketsGlobal-Demo"

TIMEFRAME_BARS = 1000
POLL_SECONDS = 2
RSI_PERIOD = 14  # shared across symbols — it's a ratio-based indicator, not price-scale dependent

# Bound to 0.0.0.0, 2026-08-15, requested directly: exposing the dashboard
# publicly via a domain (trading.weezoun.com), reverse-proxied through
# nginx running inside WSL2. WSL2 and the Windows host share the same
# public IP (198.44.118.152, a bridged network setup on this VPS) but do
# NOT share loopback (127.0.0.1 in WSL2 is not the same as Windows'), so
# nginx can only reach Flask via that shared public IP, not localhost.
# REASON this is still safe: a Windows Firewall rule
# ("TradingBot-Flask-InternalOnly") allows inbound on 5050 ONLY from
# 198.44.118.152 itself (i.e. only WSL2/nginx) — the default inbound
# policy is Block, so genuine external internet traffic to :5050 directly
# is blocked regardless of this bind change. The ONLY public entry point
# is nginx on 443.
FLASK_HOST = "0.0.0.0"

# Dashboard login, 2026-08-16, requested directly: "login window ko
# behtar karo" (a real login page instead of the browser's native Basic
# Auth popup) "aur... session ko expire karo" (Basic Auth has NO concept
# of session expiry at all — once a browser caches the credentials it
# resends them forever, until the browser itself is closed). Neither
# ask is possible with nginx's HTTP Basic Auth (the mechanism used
# 2026-08-15) — both require real server-side sessions, so auth moved
# from nginx (auth_basic, two .htpasswd files) into Flask itself
# (signed session cookie, app.py's /login /logout routes + before_request
# guard). nginx is now a plain reverse proxy again — no auth_basic left
# in its config, see the trading-bot nginx site.
# Same two accounts, same passwords, as before (unchanged, just moved):
# "weezoun" = full access (view + start/stop), "guest" = view-only
# (before_request blocks /api/start and /api/stop for any non-admin
# role, and dashboard()'s is_guest flag hides the Rules/Rule-coverage
# sections server-side, exactly as it did with nginx's X-Auth-User
# header before — same behavior, different mechanism).
DASHBOARD_ADMIN_USERNAME = "weezoun"
DASHBOARD_ADMIN_PASSWORD = "Prison3R!"
DASHBOARD_GUEST_USERNAME = "guest"
DASHBOARD_GUEST_PASSWORD = "14august"
# "Session ko expire karo" — requested directly, chose 30 minutes of
# INACTIVITY (not a fixed 30 minutes from login): Flask's
# SESSION_REFRESH_EACH_REQUEST (default True) re-issues the cookie's
# expiry on every request while the session is valid, so actively using
# the dashboard keeps it alive indefinitely; only 30 real minutes of no
# requests at all logs the user out.
SESSION_LIFETIME_MINUTES = 30
FLASK_PORT = 5050
LOG_MAX = 200

# When a position closes because its SL (or a trailing-adjusted SL) got hit,
# hold off on any new entry until the NEXT M15 candle starts, then let
# decide()/evaluate_entry() re-evaluate fresh with full confirmation (RSI,
# ADX, DI, candle color) — no direction is forced either way.
SL_COOLDOWN_UNTIL_NEXT_CANDLE = True


class SymbolConfig:
    """Per-symbol strategy settings. strategy.py takes one of these as an
    explicit `cfg` argument (instead of importing the config module globally)
    so multiple symbols can run the same decision logic with independent
    thresholds at the same time — see bot_runner.SymbolBot."""

    def __init__(
        self, symbol, lot,
        adx_min, rsi_scalp_sell_max, rsi_scalp_buy_min,
        rsi_with_trend_buy_max, rsi_with_trend_sell_min,
        adx_strong_trend, rsi_with_trend_buy_max_strong, rsi_with_trend_sell_min_strong,
        scalp_tp_points, scalp_sl_atr_mult, scalp_sl_floor,
        trend_sl_atr_mult, trend_tp_points, min_atr,
        fixed_sl_points=None, round_step=None, scalp_fixed_sl_points=None,
        trend_sl_fine_rounding=False,
        trail_step_points=None, trail_increment_points=None,
        scalping_enabled=True, flip_enabled=True,
        reversal_fixed_sl_points=None,
        trail_fixed_activate_points=None, trail_fixed_lockback_points=None,
        trail_fixed_minlock_points=None,
        trail_step_pct=None, trail_increment_pct=None,
        trend_sl_reversal_enabled=False,
    ):
        self.SYMBOL = symbol
        self.LOT = lot
        self.ADX_MIN = adx_min
        self.RSI_SCALP_SELL_MAX = rsi_scalp_sell_max   # counter-trend SELL when trend UP
        self.RSI_SCALP_BUY_MIN = rsi_scalp_buy_min     # counter-trend BUY when trend DOWN
        self.RSI_WITH_TREND_BUY_MAX = rsi_with_trend_buy_max
        self.RSI_WITH_TREND_SELL_MIN = rsi_with_trend_sell_min
        # When ADX confirms a genuinely strong/persistent trend (not just a spike),
        # give RSI even more room before treating it as "too extended to enter".
        self.ADX_STRONG_TREND = adx_strong_trend
        self.RSI_WITH_TREND_BUY_MAX_STRONG = rsi_with_trend_buy_max_strong
        self.RSI_WITH_TREND_SELL_MIN_STRONG = rsi_with_trend_sell_min_strong

        self.SCALP_TP_POINTS = scalp_tp_points
        self.SCALP_SL_ATR_MULT = scalp_sl_atr_mult
        self.SCALP_SL_FLOOR = scalp_sl_floor  # minimum scalp SL distance, in price points
        self.TREND_SL_ATR_MULT = trend_sl_atr_mult
        self.TREND_TP_POINTS = trend_tp_points  # fixed points, not an ATR multiple — see below
        # Floor under the ATR value itself before any multiplier is applied
        # (strategy._sl_tp_scalp/_sl_tp_trend, bot_runner.trail_all_positions).
        # This used to be a single hardcoded 2.0 everywhere — fine for
        # USA500-scale instruments, but GBPUSD's real ATR (~0.0006) got
        # clamped UP to 2.0, a value ~3000x too large for its price scale,
        # producing an SL over a full price unit away (16,000+ pips) on a
        # ~1.35 pair. Must be sized to each symbol's own price scale.
        self.MIN_ATR = min_atr
        # Overrides both SL formulas (scalp AND trend) to a flat points
        # distance instead of ATR-based, when set. Added for USA30
        # (2026-08-11): it moves fast enough that ATR-sized SL/TP kept
        # racing the broker's real (spread-tracking, not
        # trade_stops_level-tracking — see bot_runner._min_stop_distance)
        # minimum stop distance, causing repeated "Invalid stops" even with
        # a retry. A flat 50pt SL/TP is nowhere near that boundary (never
        # observed above ~8pts), sidestepping the whole question.
        self.FIXED_SL_POINTS = fixed_sl_points
        # SCALP-ONLY flat SL override — unlike FIXED_SL_POINTS above (which
        # overrides BOTH scalp and trend SL), this touches only
        # strategy._sl_tp_scalp(), leaving _sl_tp_trend()/WITH_TREND SL on
        # its existing ATR-based calculation, completely untouched. Added
        # for XAUUSD (2026-08-13, requested directly, values only): scalp
        # AND the scalp-SL reversal (bot_runner._reverse_scalp always calls
        # _sl_tp_scalp() regardless of the mode label it gets classified
        # under, so this same override covers the reversal automatically,
        # with no separate field needed) both move off ATR onto a flat
        # 2.00-point SL; TP and everything else stays exactly as it was.
        self.SCALP_FIXED_SL_POINTS = scalp_fixed_sl_points
        # Rounds a computed SL/TP price to this pip-scale grid (e.g. 0.100
        # for USDJPY = 100 points = 10 pips, 0.00100 for GBPUSD = 100 points
        # = 10 pips), ALWAYS rounding away from the reference price (entry
        # for a fresh order, current price for a trail) rather than to the
        # nearest grid point — so the stop/target distance only ever grows
        # from what the strategy computed, never shrinks below it. None
        # (default) leaves the existing broker-tick-size-only rounding in
        # bot_runner._round_price() unchanged for every other symbol. Added
        # 2026-08-12 at the user's direct request — this is a display/level
        # preference (round SL/TP to clean pip levels), not a broker-grid
        # validity fix like USA30's trade_tick_size mismatch.
        self.ROUND_STEP = round_step
        # WITH_TREND-SL-ONLY escape hatch from ROUND_STEP's coarse grid.
        # Added for GBPUSD (2026-08-13, requested directly): ROUND_STEP's
        # away-from-reference rounding, applied to a flat SL target that's
        # the SAME size as the step itself (GBPUSD: 0.00100 SL on a
        # 0.00100 grid), could land anywhere up to ~0.00200 — nearly
        # double the intended distance. User: "GBPUSD ka stoploss bohat
        # door ja raha hai... .00100 tak le kar ao WITH_TREND ke liye."
        # When True, bot_runner._round_price() is called with coarse=False
        # for WITH_TREND's SL specifically (both fresh orders and
        # trailing) — skips ROUND_STEP, falls through to the fine
        # broker-tick rounding, so the real distance stays close to the
        # configured flat value. TP, and every other mode/symbol, are
        # unaffected — this only touches one specific (symbol, mode, leg)
        # combination.
        self.TREND_SL_FINE_ROUNDING = trend_sl_fine_rounding
        # Per-symbol staircase trailing override. When TRAIL_STEP_POINTS
        # is set, bot_runner.trail_all_positions() uses
        # _trail_staircase() instead of the generic TP-distance-based
        # trail for this symbol: every TRAIL_STEP_POINTS of favorable
        # price movement, SL steps forward by TRAIL_INCREMENT_POINTS,
        # starting from the first step (past open price immediately, not
        # just to breakeven). Added for XAUUSD (2026-08-14, requested
        # directly) — the generic trail's 40%-of-TP activation threshold
        # left too much room for price to reverse and hit XAUUSD's flat
        # SL before any protection engaged at all. None (default) leaves
        # every other symbol's trailing completely unchanged.
        self.TRAIL_STEP_POINTS = trail_step_points
        self.TRAIL_INCREMENT_POINTS = trail_increment_points
        # Per-symbol kill switches for Rule 5 (scalp entry) and FLIP.
        # Added for GBPUSD/USDJPY (2026-08-14, requested directly — see
        # the REASON/IMPACT block on those two symbols below for the
        # full data behind this). SCALPING_ENABLED=False makes Rule 5's
        # scalp_ok always False in strategy.evaluate_entry() — Rule 6
        # (scalp TP handling) and Rule 7 (scalp SL -> reversal) both need
        # no separate change at all, since neither can ever run without a
        # scalp position existing to close (they're triggered inside
        # bot_runner._classify_and_record_close only when
        # mode == 'COUNTER_SCALP'). FLIP_ENABLED=False makes
        # strategy.evaluate_flip() return None unconditionally. True
        # (default) for every other symbol — zero effect on them,
        # confirmed directly.
        self.SCALPING_ENABLED = scalping_enabled
        self.FLIP_ENABLED = flip_enabled
        # Rule 7 (reversal)'s OWN, INDEPENDENT SL override — added
        # 2026-08-14, requested directly. Previously Rule 7 always
        # inherited whatever Rule 5's SCALP_FIXED_SL_POINTS/FIXED_SL_POINTS
        # was (bot_runner._reverse_scalp called _sl_tp_scalp() directly) —
        # the two could never differ. User: "har rule independent hona
        # chahiye, koi kisi par dependent nahi... reversal ke levels alag,
        # scalp ke alag, with_trend ke alag." Read ONLY by
        # strategy._sl_tp_reversal() — None (default) falls through the
        # exact same chain _sl_tp_scalp uses, so a symbol not given its
        # own reversal value behaves identically to before; setting this
        # can never affect Rule 5, and changing SCALP_FIXED_SL_POINTS can
        # never affect Rule 7 once this is set.
        self.REVERSAL_FIXED_SL_POINTS = reversal_fixed_sl_points
        # Fixed-POINT continuous trail (distinct from the staircase
        # above) — added for USA500, 2026-08-14, requested directly, with
        # an exact worked example: open 7800, +1pt -> SL 7800 (breakeven),
        # +2pt -> SL 7801, i.e. SL trails a constant `lockback` points
        # behind current price once `activate` points of profit is
        # reached, floored at `minlock` points past entry. Same formula
        # shape as the generic %-of-TP trail below, just with FIXED point
        # values instead of TP-percentage-derived ones. None (default)
        # leaves every other symbol's trailing untouched — see
        # bot_runner.trail_all_positions()'s dispatch order.
        self.TRAIL_FIXED_ACTIVATE_POINTS = trail_fixed_activate_points
        self.TRAIL_FIXED_LOCKBACK_POINTS = trail_fixed_lockback_points
        self.TRAIL_FIXED_MINLOCK_POINTS = trail_fixed_minlock_points
        # Percentage-of-TP STAIRCASE trail (distinct from both the
        # fixed-point staircase and the fixed-point continuous trail
        # above) — added for USA100/USA30, 2026-08-14, requested
        # directly: "trailing SL ki dynamic increment fast set karo...
        # 20% se start karo with each 20% increment... first benchmark
        # price reach hote hi TSL profit mein aa jaye." Every
        # TRAIL_STEP_PCT of the position's OWN TP distance gained, SL
        # steps forward by TRAIL_INCREMENT_PCT of that same TP distance —
        # same non-delayed formula as the XAUUSD fixed-point staircase
        # (SL already in profit at step 1), just TP-relative instead of
        # a fixed point value, so it scales automatically with each
        # symbol's own TP size. None (default) leaves every other
        # symbol's trailing untouched.
        self.TRAIL_STEP_PCT = trail_step_pct
        self.TRAIL_INCREMENT_PCT = trail_increment_pct
        # NEW mechanism (not a numbered rule), GBPUSD/USDJPY only,
        # 2026-08-14, requested directly. With Rule 5/6/7/FLIP disabled
        # on these two symbols (2026-08-13), a WITH_TREND SL used to just
        # sit there until Rule 4's own gate cleared naturally — no
        # reaction. When True, bot_runner._reverse_trend() fires
        # immediately alongside Rule 4's own (unchanged) gate-setting —
        # zero-confirmation, one attempt per DI regime, sized by this
        # symbol's own WITH_TREND SL/TP. False (default) for every other
        # symbol — no effect on them at all (the trigger site itself is
        # gated on this flag).
        self.TREND_SL_REVERSAL_ENABLED = trend_sl_reversal_enabled


# USA500: TP capped at fixed points rather than an ATR multiple — a 3x-ATR
# target (~17-27pts observed) almost never got hit (backtested 2026-08-10:
# 31% win rate over 957 historical WITH_TREND signals); most losers reversed
# within ~5pts of entry. SL halved (was 1.5x) to sit closer to that TP
# instead of risking 2-3x the reward on every trade.
#
# SL moved off ATR to a flat 5.00, both modes (2026-08-14, requested
# directly). REASON (user's own words, kept verbatim for future
# reference — see the instruction at the bottom of this file about
# always recording WHY, not just WHAT): "USA500 per SL bohat qareeb lag
# raha hai jis ki wajah se trades bohat jaldi close ho rahi hain" — the
# ATR-based SL (0.75x/0.8x ATR, no floor override) was landing too close
# to entry on this symbol specifically, so ordinary noise was closing
# trades before the intended move had room to develop. Example given:
# open 7815 -> BUY SL 7810 (-5), SELL SL 7820 (+5) — i.e. a flat 5-point
# gap, not scaled by ATR at all. IMPACT: SL distance is now CONSTANT
# regardless of current volatility — on a low-ATR day this is more room
# than ATR would have given (fewer premature stops, the goal here), but
# on a genuinely high-ATR/fast day it could now be TIGHTER than ATR
# would have sized it (ATR-based sizing widens automatically when the
# market is moving fast; a flat number does not) — worth re-checking if
# USA500 starts stopping out on fast/volatile days specifically, as
# that's the opposite failure mode from the one this change targets.
#
# FOLLOW-UP, 2026-08-14 (brainstorm after seeing per-rule stats): Rule 5
# (scalp) had the most trades but only 34.8% win / -37.49 net; Rule 7
# (reversal) was the best performer at 83.3% win / +18.56.
# REASON (user's words): "SL kam kar ke 2.5 par dein to half loss cover
# ho jayega... reversal bhi acha perform karega" (point 1), "reversal
# kyunki acha perform kar raha hai iska SL change nahi karenge" (point
# 3) — Rule 5's SL cut to 2.5, Rule 7's SL explicitly held at the
# existing 5.00, independently. (Flagged this exact tension directly —
# Rule 7 always used to inherit Rule 5's SL via the same function; user's
# answer: "har rule independent hona chahiye... reversal ke levels alag"
# — built _sl_tp_reversal() as its OWN function, see strategy.py, so
# these two can now genuinely differ.)
# IMPACT: Rule 5 losses should shrink (smaller SL = smaller loss per
# stop-out) but Rule 5's WIN behavior is unaffected (TP unchanged at
# 5.5) — win rate itself won't necessarily improve, only loss size will
# shrink, unless paired with fix #2 below. Rule 7 completely unaffected
# by this specific change (its own independent 5.00 stays exactly as
# it was performing).
#
# Trailing changed to a fixed-point CONTINUOUS trail (not a staircase):
# "1 point aage barhne par SL open se upar taake loss na ho, phir har 1
# point aage barhne par trailing 1 point upar. e.g. open 7800, SL 7795,
# price 7801 -> SL 7800, price 7802 -> SL 7801." REASON: the old generic
# trail only activates at 40% of TP (2.2pts on a 5.5pt TP) — too much
# unprotected room before ANY lock-in starts. IMPACT: SL now locks to
# breakeven after just 1pt of favorable movement (vs. 2.2pt before) and
# keeps pace 1:1 with price after that — should meaningfully reduce
# how often a winning trade gives it all back before securing SOME
# profit, at the cost of potentially exiting slightly earlier on trades
# that pull back briefly before continuing (normal trailing-stop
# trade-off, just triggered sooner than before).
USA500 = SymbolConfig(
    symbol="USA500", lot=1.0,
    adx_min=15, rsi_scalp_sell_max=65, rsi_scalp_buy_min=35,
    rsi_with_trend_buy_max=80, rsi_with_trend_sell_min=20,
    adx_strong_trend=25, rsi_with_trend_buy_max_strong=90, rsi_with_trend_sell_min_strong=10,
    scalp_tp_points=5.5, scalp_sl_atr_mult=0.8, scalp_sl_floor=3.0,
    trend_sl_atr_mult=0.75, trend_tp_points=5.5, min_atr=2.0,
    # Rule 2 (WITH_TREND) SL cut 5.00 -> 2.50, 2026-08-16, requested
    # directly after comparing per-rule stats against the 2026-08-15
    # benchmark: "usa500... eventually yeh loss may hein... usa500 ka sl
    # 2.5 kerdo with_trend per scalp per already hum ne kum kia hoa hai."
    # REASON: post-benchmark Rule 2 alone was still net negative despite
    # a better win rate (64.4%) than before — a higher win rate doesn't
    # help if losing trades cost more than winning ones gain; now matches
    # Rule 5's already-cut 2.50 exactly (previously Rule 2 was double
    # Rule 5's SL). IMPACT: smaller loss per Rule 2 stop-out, same
    # trade-off as every other SL cut on this bot — win rate itself
    # doesn't change from this alone, only the cost of being wrong.
    fixed_sl_points=2.50,       # Rule 2 (WITH_TREND) — cut from 5.00
    scalp_fixed_sl_points=2.50, # Rule 5 (scalp) only — cut (unchanged this round)
    reversal_fixed_sl_points=5.00,  # Rule 7 (reversal) — held independently, unchanged
    # Fixed-point CONTINUOUS trail REMOVED, 2026-08-15 — superseded by the
    # unified %-of-TP continuous trail now used on all 6 symbols (see
    # bot_runner.trail_all_positions()'s generic branch, activate=25%/
    # lock_back=25%/min_lock=12.5%). User: "trail sub symbols per aeise hi
    # laga do jeise meine bataya hai." Values left in the code (commented)
    # for reference: activate_points=1.00, lockback_points=1.00,
    # minlock_points=0.00 (the exact worked example this used to match:
    # open 7800, +1pt->SL 7800, +2pt->SL 7801).
)

# All other symbols below: same thresholds as USA500 (ADX/RSI bands are
# ratios, not price-scale dependent, so they carry over directly). TP/SL
# points were NOT copied blind, though — "5.5 points" means a totally
# different move size on each instrument's price scale. Each was instead
# derived from that symbol's own M15 ATR(14) (last 1000 bars, checked
# 2026-08-11): TP ≈ 0.68x mean ATR, SL floor ≈ 0.37x mean ATR — the same
# ratios USA500's own numbers (5.5 / 3.0) work out to against its ATR
# (~8.1 at the time). Re-derive these if a symbol's typical ATR drifts far
# from what it was when this was set.
XAUUSD = SymbolConfig(  # mean M15 ATR ~8.1 (near-identical to USA500 currently)
    # SCALP (and its reversal) SL moved off ATR to a flat 2.00 points
    # (2026-08-13, requested directly) — WITH_TREND SL stayed ATR-based.
    # SUPERSEDED same day, requested directly again: "gold ka SL scalp aur
    # with_trend kam kar ke 5 par fix karo" — both modes now flat 5.00 via
    # FIXED_SL_POINTS (bypasses ATR entirely for WITH_TREND too), same
    # uniform-flat-SL pattern as USA30/USA100/GBPUSD/USDJPY.
    # SCALP_FIXED_SL_POINTS removed — scalp now falls back to
    # FIXED_SL_POINTS like WITH_TREND does, both the same flat value. TP
    # untouched (still 5.5, both modes) — only SL asked for.
    symbol="XAUUSD", lot=1.0,
    adx_min=15, rsi_scalp_sell_max=65, rsi_scalp_buy_min=35,
    rsi_with_trend_buy_max=80, rsi_with_trend_sell_min=20,
    adx_strong_trend=25, rsi_with_trend_buy_max_strong=90, rsi_with_trend_sell_min_strong=10,
    scalp_tp_points=5.5, scalp_sl_atr_mult=0.8, scalp_sl_floor=3.0,
    trend_sl_atr_mult=0.75, trend_tp_points=5.5, min_atr=2.0,
    # Rule 2 (WITH_TREND) SL cut 5.00 -> 2.00, 2026-08-16, requested
    # directly after comparing per-rule stats against the 2026-08-15
    # benchmark: "xauusd ka sl bhi with_trend 2 per kerdo" (same round as
    # USA500's cut above — see that symbol's comment for the full
    # reasoning: a higher post-benchmark win rate alone (64.6% here)
    # doesn't help when losses still outweigh wins in dollar terms). Now
    # matches Rule 5/7's already-cut 2.00 exactly (previously Rule 2 was
    # 2.5x Rule 5/7's SL). IMPACT: smaller loss per Rule 2 stop-out —
    # same trade-off as every other SL cut here, win rate itself doesn't
    # change from this alone.
    fixed_sl_points=2.00,       # Rule 2 (WITH_TREND) — cut from 5.00
    # Staircase trailing (2026-08-14, requested directly): "SL baar baar
    # hit hona hai, trailing kafi late update ho raha hai" — the generic
    # trail (40% of TP = 2.2pts before it even starts) left too much room
    # for a reversal to hit the flat 5.00 SL first. Every 1.00pt of
    # favorable movement, SL now steps forward by 0.5pt, starting at the
    # very first point (past open price immediately): +1 -> open+0.5,
    # +2 -> open+1.0, +3 -> open+1.5, ... (mirrored for SELL). Applies to
    # WITH_TREND, scalp, and reversal alike (trail_all_positions() has no
    # mode branch) — CONFIRMED still true 2026-08-14 when re-verified for
    # this same brainstorming round; user recalled setting this up
    # correctly and asked to double check, not to redo it.
    #
    # REPLACED, 2026-08-15 — superseded by the unified %-of-TP CONTINUOUS
    # trail now applied identically to all 6 symbols. User caught the
    # staircase SHAPE itself as the deeper problem (on USA30, discretely):
    # SL only moves at fixed jump points and sits FLAT between them, even
    # as price keeps advancing — "price ka difference dekho lekin trailing
    # SL aage nahi barh raha." Explicit instruction: "trail sub symbols
    # per aeise hi laga do jeise meine bataya hai" (apply the SAME new
    # continuous formula on every symbol, gold included). `trail_step_points`/
    # `trail_increment_points` removed — this symbol now falls through to
    # the generic branch in `trail_all_positions()` (activate=25%/
    # lock_back=25%/min_lock=12.5% of TP, continuous, recomputed every
    # tick from live price — see that function for the full derivation).
    # FOLLOW-UP, 2026-08-14 (brainstorm after seeing per-rule stats):
    # Rule 5 -1155 net, Rule 7 -575 net — the two weakest performers here
    # (Rule 2 the clear best at +330). REASON (user's words): "Rule 5 aur
    # 7 ke SL ko kam kar ke 2 kar do" — back down from the shared 5.00 to
    # a flat 2.00 for scalp specifically (mirrors the ORIGINAL 2026-08-13
    # design, superseded earlier the same day by the uniform-5.00 change
    # above — now reinstated, scalp/reversal only this time). Rule 7
    # follows automatically (no independent reversal value requested for
    # XAUUSD this round, unlike USA500/USA30) since _sl_tp_reversal()
    # falls back to SCALP_FIXED_SL_POINTS when unset. Rule 2 stays at the
    # existing flat 5.00, untouched.
    # IMPACT: same trade-off as every other SL cut here — Rule 5/7 losses
    # should shrink per-trade (smaller SL), win rate itself unaffected by
    # this alone (TP unchanged).
    scalp_fixed_sl_points=2.00,
)

GBPUSD = SymbolConfig(  # mean M15 ATR ~0.00048 currently (re-checked 2026-08-11)
    # TP was 0.005 (~50 pips) — ~10.4x mean ATR, wildly off the 0.68x-ATR
    # ratio every other floating symbol here is derived from (USA500 1.15x,
    # XAUUSD 0.61x, USA100 0.55x — all in the same neighborhood; GBPUSD
    # alone was 10x out), with no comment anywhere justifying it as a
    # deliberate override (unlike USDJPY's TP widening, which IS commented
    # as explicitly requested). Matches the observed result exactly: 0
    # wins / 3 losses — a TP needing a ~50-pip M15 move essentially never
    # hits on a pair averaging ~5-pip ATR, every trade just sits until SL.
    # Re-derived from CURRENT live ATR using this file's own stated
    # methodology (TP ~= 0.68x mean ATR = 0.00033), then nudged up to
    # 0.00040 (~0.83x ATR) for headroom above the broker's real min stop
    # distance (confirmed live: ~0.00031 with the 1.2x safety margin
    # already applied — 0.00033 cleared it by only ~6%, too thin against
    # normal spread fluctuation). Found + fixed 2026-08-11 during a full
    # audit requested directly after this exact class of per-symbol
    # inconsistency went unnoticed.
    # SL and TP both fixed at flat 0.00100 (2026-08-13, requested directly,
    # mirrors USDJPY's same-day fix above) — ATR removed entirely, same
    # fixed_sl_points pattern as USA30/USA100 (values only, no rule logic
    # touched).
    # FINAL FIX, same day (SUPERSEDES the two follow-ups below): user
    # reported SL/TP still not landing exactly at 0.00100 — "yeh abhi tak
    # fix nahi hain balke change hoti rehti hain... mujhe dynamic nahi
    # chahiye, is ko final fix karo." Root cause was `ROUND_STEP` itself:
    # rounding AWAY from a reference price on a 0.00100 grid, applied to a
    # target that's the SAME size as the grid step, could add up to
    # another full step every time — landing anywhere in [0.00100,
    # 0.00200), never exactly 0.00100, and different on every single
    # trade depending where entry happened to fall on the grid (hence
    # "keeps changing"). `round_step` REMOVED entirely (was 0.00100) —
    # with it gone, `bot_runner._round_price()` falls through to fine
    # broker-tick rounding (0.00001) for every SL/TP on this symbol,
    # WITH_TREND and scalp/reversal alike, always landing within one tick
    # of the exact 0.00100 target. This also makes `trend_sl_fine_rounding`
    # (the WITH_TREND-SL-only fix from the first follow-up) redundant —
    # removed too, since `ROUND_STEP=None` already gives fine rounding
    # everywhere with no mode-specific carve-out needed.
    symbol="GBPUSD", lot=1.0,
    adx_min=15, rsi_scalp_sell_max=65, rsi_scalp_buy_min=35,
    rsi_with_trend_buy_max=80, rsi_with_trend_sell_min=20,
    adx_strong_trend=25, rsi_with_trend_buy_max_strong=90, rsi_with_trend_sell_min_strong=10,
    scalp_tp_points=0.00050, scalp_sl_atr_mult=0.8, scalp_sl_floor=0.00024,
    trend_sl_atr_mult=0.75, trend_tp_points=0.00050, min_atr=0.0002,
    fixed_sl_points=0.00050,
    # Scalping (Rule 5, which cascades to Rule 6/7) and FLIP both
    # DISABLED for GBPUSD (2026-08-14, requested directly).
    # REASON (user's words): "GBPUSD... late signals le rahi hain jis ki
    # wajah se sirf loss ho raha hai" — investigated first (no rule
    # changes, per the user's own instruction at the time), found via
    # real trade data: Rule 7 (reversal) 0% win / -373, FLIP 0% win /
    # -201, Rule 5 (scalp) 38.5% win but -471 net (the single biggest
    # loss contributor) — vs. Rule 2 (fresh WITH_TREND, unaffected by
    # this change) at 40% win / -208. Every Rule 7/FLIP entry landed
    # 33-884 seconds INTO its M15 candle (reactive triggers, never
    # anchored to a candle boundary the way Rule 2 is) — that's the
    # literal "late signal" the user was seeing, and it was losing
    # unanimously. User's decision after seeing this data: turn all
    # three off, keep only Rules 1/2/3/4 (WITH_TREND + its own TP/SL
    # handling) live on this symbol.
    # IMPACT: GBPUSD now only ever trades WITH_TREND (Rule 2), never
    # counter-trend scalps and never a DI-flip reversal — this removes
    # the -471/-373/-201 loss sources entirely, but also removes
    # whatever wins those mechanisms occasionally produced (Rule 5 alone
    # still won 5 of 13 trades) and means GBPUSD will simply sit flat
    # during stretches where the big trend isn't confirmed enough for
    # Rule 2 (no scalp fallback to catch a counter-move, no FLIP to
    # catch a genuine reversal early) — fewer trades overall on this
    # symbol, not just fewer losing ones. Re-enabling either flag later
    # returns to the exact prior behavior; Rules 1-4 and every other
    # symbol are completely unaffected by this pair of flags.
    scalping_enabled=False, flip_enabled=False,
    # FOLLOW-UP, 2026-08-14: even with Rule 5/6/7/FLIP off, Rule 2 alone
    # was still losing (-361 over 14 trades since the disable). User: "in
    # k stats kisi kaam ke nahi, koi improvement ki gunjaish nazar nahi
    # aa rahi, yeh signal ghalat time par le rahe hain" — asked for 4
    # things instead of reverting the disable: (1) faster trailing, (2) a
    # NEW immediate reversal the instant a WITH_TREND SL hits (with the
    # same fast trailing), (3) SL cut in half (0.00100 -> 0.00050), (4)
    # TP set equal to SL (1:1).
    # REASON/IMPACT for each:
    # (3) fixed_sl_points halved to 0.00050 — smaller loss per stop-out,
    #     but also a tighter stop that ordinary noise can hit more often;
    #     this is a real trade-off, not a pure improvement.
    # (4) trend_tp_points/scalp_tp_points also set to 0.00050 (were
    #     0.00100) — 1:1 risk:reward means breakeven needs >50% win rate
    #     to be net profitable, vs. needing less than 50% when TP was
    #     larger than SL; this raises the bar for what counts as
    #     "working" going forward.
    # (1)+(2) see trail_step_pct/trend_sl_reversal_enabled below.
    # (values already set above: scalp_tp_points/trend_tp_points/
    # fixed_sl_points all 0.00050 — same call, no duplicate keywords.)
    # (1) Faster trailing — originally reused the %-of-TP STAIRCASE
    # mechanism (same as USA100/USA30, 2026-08-14), briefly corrected to
    # STEP=25%/INCREMENT=12.5% same day after a live-price-collision bug.
    # REPLACED AGAIN, 2026-08-15 — superseded entirely by the unified
    # %-of-TP CONTINUOUS trail now applied identically to all 6 symbols
    # (see bot_runner.trail_all_positions()'s generic branch and
    # XAUUSD's config comment for the full derivation). User caught the
    # discrete staircase SHAPE itself as the deeper problem, not just its
    # levels: "trail sub symbols per aeise hi laga do jeise meine bataya
    # hai." `trail_step_pct`/`trail_increment_pct` removed — this symbol
    # now falls through to the generic branch (activate=25%/lock_back=25%/
    # min_lock=12.5% of TP, continuous, recomputed every tick).
    # (2) New reversal-on-WITH_TREND-SL mechanism — see
    # bot_runner._reverse_trend() and BotState.trend_reversal_used for
    # the full isolated implementation. NOT Rule 7 (which stays disabled
    # here, scalping_enabled=False) — a separate, new, simpler mechanism
    # triggered by a WITH_TREND SL specifically, since Rule 5/6/7 have no
    # scalp position to ever trigger from on this symbol. Sized by this
    # same flat 0.00050 SL/TP, trails at the same corrected staircase as
    # every other position here.
    trend_sl_reversal_enabled=True,
)

USDJPY = SymbolConfig(  # mean M15 ATR ~0.124 (~12.4 pips at JPY's 0.01-pip scale)
    # TP widened from 0.084 to 0.5 (2026-08-11, requested directly) — 0.084
    # was too tight relative to its SL, opposite problem from USA500/etc.
    # SUPERSEDED 2026-08-13 (requested directly): a live WITH_TREND position
    # showed SL close (0.122) but TP blown far out (0.578) — TP fixed at
    # 0.5 was already ~5x the ATR-based SL even before ROUND_STEP grid
    # rounding added on top. User asked for TP at the SAME level as SL, then
    # chose flat/fixed over ATR-based entirely (same pattern as USA30/
    # USA100): SL and TP both now fixed at flat 0.100 pre-rounding.
    symbol="USDJPY", lot=1.0,
    adx_min=15, rsi_scalp_sell_max=65, rsi_scalp_buy_min=35,
    rsi_with_trend_buy_max=80, rsi_with_trend_sell_min=20,
    adx_strong_trend=25, rsi_with_trend_buy_max_strong=90, rsi_with_trend_sell_min_strong=10,
    # A same-day follow-up briefly cut SCALP's SL further to a flat 0.025
    # (SCALP_FIXED_SL_POINTS, scalp-only) while WITH_TREND stayed at 0.100.
    # SUPERSEDED the same day: user's final instruction was SL=100/TP=100
    # (i.e. flat 0.100) for WITH_TREND AND scalp AND reversal, ALL THREE,
    # uniformly — no more mode-specific carve-out. scalp_fixed_sl_points
    # removed; scalp now falls back to fixed_sl_points (0.100) below, same
    # as WITH_TREND — see strategy._sl_tp_scalp's fallback order.
    #
    # FINAL FIX, same day (also covers the ROUND_STEP removal): user
    # reported SL/TP still landing inconsistently — "yeh abhi tak fix
    # nahi hain balke change hoti rehti hain... mujhe dynamic nahi chahiye,
    # is ko final fix karo." Root cause was `ROUND_STEP` (0.100 grid):
    # rounding AWAY from a reference price, on a grid the SAME size as the
    # SL/TP target itself, added up to one more full 0.100 step every
    # time, landing anywhere in [0.100, 0.200) rather than exactly at
    # 0.100 — different on every trade depending where entry fell on the
    # grid. `round_step` REMOVED entirely (was 0.100) — with it gone,
    # `bot_runner._round_price()` falls through to fine broker-tick
    # rounding (0.001) for every SL/TP on this symbol, WITH_TREND and
    # scalp/reversal alike, always landing within one tick of the exact
    # 0.100 target.
    # SL/TP raised 0.050 -> 0.075, 2026-08-15, requested directly: "USDJPY
    # ka SL aur TP to ajeeb hi lag raha hai, us per to trail kaam hi nahi
    # kare ga, itna chota ho gaya hai, us ko increase ker ke 75 per
    # kerdo." REASON: at 0.050 (5 pips), the flat SL/TP had gotten so
    # small relative to the broker's real minimum stop distance that the
    # trail's %-of-TP math had almost no room to operate in — a 25% step
    # of an already-tiny 0.050 TP is well inside noise/rounding territory.
    # 0.075 (7.5 pips) keeps the 1:1 SL=TP shape from the prior follow-up,
    # just bigger. IMPACT: bigger loss per stop-out than 0.050 gave (the
    # opposite direction from the SL-halving asked for the day before —
    # this supersedes that specific number, not the reasoning behind it),
    # but now the trail actually has room to move.
    scalp_tp_points=0.075, scalp_sl_atr_mult=0.8, scalp_sl_floor=0.046,
    trend_sl_atr_mult=0.75, trend_tp_points=0.075, min_atr=0.03,
    fixed_sl_points=0.075,
    # Scalping (Rule 5, cascades to Rule 6/7) and FLIP both DISABLED for
    # USDJPY (2026-08-14, requested directly, same instruction as GBPUSD
    # above — see that symbol's comment for the full REASON/IMPACT
    # writeup, identical reasoning applies here).
    # REASON (data specific to USDJPY): Rule 7 (reversal) 0% win / -190.95,
    # FLIP 0% win / -105.46, Rule 5 (scalp) 0% win / -524.93 (the single
    # biggest loss contributor on this symbol) — vs. Rule 2 (fresh
    # WITH_TREND, unaffected) at 33% win / -3.63, essentially breakeven.
    # Every Rule 7/FLIP entry landed 33-505 seconds into its M15 candle —
    # the same "late signal" pattern found on GBPUSD.
    # IMPACT: identical trade-off to GBPUSD — USDJPY now only trades
    # WITH_TREND (Rule 2), removing all three loss sources above but also
    # removing scalp's occasional wins and FLIP's early-reversal catches;
    # fewer trades overall, not just fewer losing ones. Re-enabling
    # either flag returns to the exact prior behavior.
    scalping_enabled=False, flip_enabled=False,
    # FOLLOW-UP, 2026-08-14, same instruction as GBPUSD above (see that
    # symbol's comment for the full REASON — identical reasoning): Rule 2
    # alone still losing (-145.28 over 8 trades since the disable). Same
    # 4-part fix: SL halved, TP=SL, faster trailing, new WITH_TREND-SL
    # reversal.
    # (values above updated 2026-08-15 to 0.075 — see the SL/TP comment
    # just above; same call, no duplicate keywords.)
    # Trailing: was briefly a %-of-TP STAIRCASE (corrected same day from a
    # live-price-collision bug to STEP=25%/INCREMENT=12.5%), REPLACED
    # AGAIN 2026-08-15 — superseded by the unified %-of-TP CONTINUOUS
    # trail now applied identically to all 6 symbols (see XAUUSD's config
    # comment and bot_runner.trail_all_positions() for the full
    # derivation). `trail_step_pct`/`trail_increment_pct` removed — falls
    # through to the generic branch (activate=25%/lock_back=25%/
    # min_lock=12.5% of TP, continuous).
    trend_sl_reversal_enabled=True,
)

USA100 = SymbolConfig(  # mean M15 ATR ~60.7 — NOT in Market Watch by default on
    # this broker (visible=False); bot_runner.connect_mt5() explicitly
    # symbol_select()s every configured symbol so this still works.
    # TP cut from 41 to 20 (2026-08-11, requested directly) — still far
    # relative to typical room, re-check like USA500 was if it keeps missing.
    # SL and TP both fixed at flat 30pts (2026-08-12, requested directly,
    # values only — same fixed_sl_points pattern as USA30 below; no rule
    # logic touched). TP was already a fixed-points value (not ATR-based)
    # for every symbol — only the number changed, 20 -> 30. SL now bypasses
    # ATR entirely via fixed_sl_points, same as it did via scalp_sl_atr_mult
    # ATR-based sizing before; scalp_sl_atr_mult/scalp_sl_floor stay set but
    # go unused while fixed_sl_points is set (see strategy._sl_tp_scalp/
    # _sl_tp_trend).
    #
    # FOLLOW-UP, 2026-08-14 (brainstorm after seeing per-rule stats):
    # Rule 2 was healthiest (75% win/+44.62); Rule 5 and Rule 7 both
    # roughly breakeven but with room to improve.
    # REASON (user's words): "trailing SL ko behtar kar dein to acha ho
    # jayega Rule 2, 5 aur 7 ke liye, aur Rule 5 aur 7 ke liye SL ko tight
    # karna hoga, 15 tak lock kar do, baqi sab theek hai." Rule 5's SL cut
    # to a flat 15 (from the shared 30) — Rule 7 automatically follows to
    # 15 too here, since the user wants BOTH tightened together (no
    # independent-value request for this symbol, unlike USA500/USA30) and
    # _sl_tp_reversal() falls back to SCALP_FIXED_SL_POINTS when no
    # REVERSAL_FIXED_SL_POINTS is set. Rule 2 (WITH_TREND) stays at the
    # existing flat 30 via fixed_sl_points, untouched ("baqi sab theek
    # hai").
    # IMPACT: Rule 5/7 losses should shrink (smaller SL = smaller loss per
    # stop-out), same trade-off as USA500 above — win rate itself doesn't
    # necessarily improve from this alone.
    #
    # Trailing changed to a percentage-of-TP STAIRCASE (not the old
    # single-activation generic trail): "trailing SL ki dynamic increment
    # fast set karo, 20% se start karo with each 20% increment, first
    # benchmark price reach hote hi TSL profit mein aa jaye." REASON: the
    # old generic trail waits until 40% of TP before locking ANY profit
    # in.
    #
    # CORRECTED, 2026-08-14 (real bug, caught by the user): setting
    # TRAIL_STEP_PCT == TRAIL_INCREMENT_PCT (both 20%) meant the FIRST
    # trail step landed the new SL almost exactly AT live price the
    # instant it triggered (profit just barely crossed 20%*TP -> new
    # SL = open + 20%*TP = ~current price) — "trail lagte hi position
    # close ho jaye gi ya trail fail ho jaye ga, same live price hone ki
    # wajah se." User: the 20%-start-with-20%-increment wording was only
    # to EXPLAIN the concept ("meine apna tareeqa sirf samjhane k liye
    # diya tha"), not a literal spec — the mechanism to actually follow
    # is the one already built correctly for XAUUSD (`trail_step_points`/
    # `trail_increment_points` below, INCREMENT deliberately smaller than
    # STEP so the first trail sits "thora upper" open price, not at live
    # price) — reduce the ACTIVATION level only (was effectively 50%+
    # originally, now 25%), keep that same non-colliding shape. Now
    # STEP=25% (activation threshold), INCREMENT=12.5% (half of step,
    # same 2:1 ratio XAUUSD already uses) — first step: profit reaches
    # 25%*TP, SL jumps to open+12.5%*TP (comfortably behind live price,
    # never equal to it).
    # IMPACT: activation is later than the old (buggy) 20% trigger, but
    # the mechanism now actually WORKS (no more immediate-close risk);
    # same trade-off as every other trail change here otherwise — profit
    # protected earlier than the pre-staircase 40% default, at the cost
    # of possibly exiting slightly sooner on a trade that pulls back
    # before continuing.
    #
    # REPLACED AGAIN, 2026-08-15 — the discrete staircase SHAPE itself
    # (not just its levels) turned out to be the real problem: it only
    # moves SL at fixed jump points and sits FLAT in between, even while
    # price keeps advancing (caught live on USA30 — see that symbol's
    # comment). Superseded by the unified %-of-TP CONTINUOUS trail now
    # applied identically on all 6 symbols: "trail sub symbols per aeise
    # hi laga do jeise meine bataya hai." `trail_step_pct`/
    # `trail_increment_pct` removed — falls through to
    # `trail_all_positions()`'s generic branch (activate=25%/
    # lock_back=25%/min_lock=12.5% of TP, continuous, recomputed every
    # tick — see that function for the full derivation from the user's
    # worked example).
    symbol="USA100", lot=1.0,
    adx_min=15, rsi_scalp_sell_max=65, rsi_scalp_buy_min=35,
    rsi_with_trend_buy_max=80, rsi_with_trend_sell_min=20,
    adx_strong_trend=25, rsi_with_trend_buy_max_strong=90, rsi_with_trend_sell_min_strong=10,
    scalp_tp_points=30.0, scalp_sl_atr_mult=0.8, scalp_sl_floor=22.0,
    trend_sl_atr_mult=0.75, trend_tp_points=30.0, min_atr=2.0,
    # Rule 2 (WITH_TREND) SL — REVERSED SAME DAY, 2026-08-21. First tried
    # cutting 30.0 -> 15.0 (see version history / memory for that
    # reasoning), but the user reconsidered before it had a chance to run:
    # "mere khayal may hum sl ko tight ker rahe hein is k bajaye yeh karo
    # k sl ko agey barha do 50 per kerdo, kum ker k to aur ziada trade
    # lelega choti moves per aur ziada bahar nikale ga." REASON: the
    # diagnosed problem (Rule 4's benchmark-crossing fast path re-firing
    # rapidly in a choppy stretch, 18 WITH_TREND SELLs in 11 minutes,
    # 2026-08-21) is made WORSE by a tighter SL, not better — a smaller
    # stop is easier for ordinary short-term noise to reach, so tightening
    # it would make each of those rapid re-entries MORE likely to get
    # stopped out on chop rather than fewer. A WIDER SL gives each entry
    # more room to survive normal noise before being stopped — the
    # opposite lever from every other SL cut on this bot, deliberately,
    # because the underlying problem here is entry FREQUENCY/noise-
    # sensitivity, not "losses cost too much relative to wins."
    # IMPACT: each individual stop-out now costs MORE if it happens
    # (50 vs the original 30), but the bet is that fewer of the rapid
    # re-entries actually reach a 50-point adverse move than reach a
    # 15- or even 30-point one, so the NET effect on rapid-reentry bursts
    # specifically should be fewer stop-outs, not smaller ones. Genuinely
    # experimental, explicitly framed that way by the user — the opposite
    # direction from USA500/XAUUSD's own SL cuts earlier this version
    # chain, deliberately, since the diagnosis here is different.
    fixed_sl_points=50.0,       # Rule 2 (WITH_TREND) — widened from 30.0 (briefly tried 15.0 first, reversed same day)
    scalp_fixed_sl_points=15.0, # Rule 5 (scalp) — cut, 2026-08-14; Rule 7 (reversal) follows automatically (no independent override set)
)

USA30 = SymbolConfig(  # mean M15 ATR ~53.7
    # SL and TP both fixed at flat 50pts (2026-08-11, requested directly) —
    # ATR-based SL kept racing the broker's real minimum stop distance on
    # this fast-moving symbol, causing repeated "Invalid stops" even with a
    # retry (see bot_runner._min_stop_distance / send_order). 50pts is far
    # above any observed minimum (~8pts worst case), sidestepping that
    # entirely, and simple/predictable besides.
    #
    # FOLLOW-UP, 2026-08-14 (brainstorm after seeing per-rule stats): the
    # ONE symbol where Rule 2 was the biggest LOSER (31.2% win/-435.50)
    # and Rule 5 (scalp) the best performer (75% win/+181.70) — opposite
    # pattern from every other symbol.
    # REASON (user's words): "Rule 2 aur 7 ke liye SL kam kar do, 50 par
    # laga hai, 25 par le ao... Rule 5 aur FLIP ki conditions EXACT
    # rahengi, no change." Flagged directly that Rule 7 always used to
    # inherit Rule 5's SL via the same shared function — if Rule 5 must
    # stay at 50 while Rule 7 drops to 25, they need to be genuinely
    # independent. User's answer: "har rule independent hona chahiye...
    # naya mechanism banao." So: `fixed_sl_points` (Rule 2) cut 50 -> 25;
    # `scalp_fixed_sl_points` (Rule 5) explicitly SET to 50 — locking it
    # at its current value independently, since without this it would
    # have silently followed `fixed_sl_points` down to 25 too;
    # `reversal_fixed_sl_points` (Rule 7, via the new `_sl_tp_reversal()`)
    # independently set to 25. FLIP untouched (already `True`/default —
    # was never disabled on USA30). Rule 5's own ENTRY CONDITIONS
    # (ADX/RSI/DI/candle logic in strategy.py) are completely untouched —
    # only SL values changed anywhere on this symbol.
    # IMPACT: Rule 2's losses should shrink (smaller SL = smaller loss
    # per stop-out) — this is USA30's biggest problem area, so the
    # clearest potential win here. Rule 7 also gets a smaller SL,
    # independent of Rule 5 for the first time. Rule 5 completely
    # unaffected (still flat 50, still 75% win historically) — deliberately
    # left as the one thing NOT to touch on this symbol.
    #
    # Trailing changed to a percentage-of-TP STAIRCASE, same mechanism as
    # USA100 but with USA30's own faster threshold: "trailing SL ki speed
    # barhao, jaldi upar aaye, 50% ka wait na kare balke 25% par upar aa
    # jaye." IMPACT: same trade-off as every other trail change here —
    # profit locks in starting at 25% of TP distance instead of waiting
    # for the old ~40%, at the cost of possibly exiting slightly sooner on
    # a trade that pulls back before continuing.
    #
    # CORRECTED, 2026-08-14 (same real bug as USA100, see that symbol's
    # comment for the full explanation): TRAIL_STEP_PCT == TRAIL_INCREMENT_PCT
    # (both 25%) put the first trail's SL almost exactly at live price
    # the moment it triggered — risk of an immediate close/failed modify.
    # STEP stays 25% (this was already the correct, explicitly-requested
    # activation level) but INCREMENT is now 12.5% (half of step, same
    # 2:1 ratio as XAUUSD's already-correct mechanism) so the first trail
    # actually sits behind live price instead of on top of it.
    #
    # REPLACED AGAIN, 2026-08-15 — caught LIVE on this exact symbol: "USA30
    # ki price ka difference dekho lekin trailing SL aage nahi barh raha
    # hai" (a real open position showing meaningful price movement with
    # the trailed SL sitting flat) — the discrete staircase SHAPE is the
    # problem, not just its levels: it only jumps at fixed points and
    # doesn't move at all in between, even as price keeps advancing.
    # Superseded by the unified %-of-TP CONTINUOUS trail now applied
    # identically on all 6 symbols: "trail sub symbols per aeise hi laga
    # do jeise meine bataya hai." `trail_step_pct`/`trail_increment_pct`
    # removed — falls through to `trail_all_positions()`'s generic branch
    # (activate=25%/lock_back=25%/min_lock=12.5% of TP, continuous,
    # recomputed every tick from live price instead of jumping in fixed
    # steps — see that function for the full derivation from the user's
    # worked example: 25%->12.5%, 50%->25%, 75%->50%).
    symbol="USA30", lot=1.0,
    adx_min=15, rsi_scalp_sell_max=65, rsi_scalp_buy_min=35,
    rsi_with_trend_buy_max=80, rsi_with_trend_sell_min=20,
    adx_strong_trend=25, rsi_with_trend_buy_max_strong=90, rsi_with_trend_sell_min_strong=10,
    scalp_tp_points=50.0, scalp_sl_atr_mult=0.8, scalp_sl_floor=20.0,
    trend_sl_atr_mult=0.75, trend_tp_points=50.0, min_atr=2.0,
    fixed_sl_points=25.0,        # Rule 2 (WITH_TREND) — cut from 50
    scalp_fixed_sl_points=50.0,  # Rule 5 (scalp) — explicitly HELD at 50, independent
    reversal_fixed_sl_points=25.0,  # Rule 7 (reversal) — independent, cut to match Rule 2
)

# Six-symbol addition (Coffee/Copper/Cocoa/Cotton/Palladium/Platinum),
# 2026-08-18, REVERTED same day — requested directly: "in jo add kiye
# hein remove ker do, yeh sub system hi bigar diya hai, reverse ker do
# pehle wali state may le jao." Removed entirely, back to the original 6
# symbols only. Not kept commented-out here (unlike smaller superseded
# values elsewhere in this file) since it's a full symbol addition/removal,
# not a value tweak — see the version history / memory file if the exact
# config values are ever needed again.

SYMBOLS = {
    "USA500": USA500, "USA100": USA100, "USA30": USA30,
    "XAUUSD": XAUUSD, "GBPUSD": GBPUSD, "USDJPY": USDJPY,
}
