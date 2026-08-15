# MT5 / bot settings — edit here only (not in the UI)

# MT5_LOGIN = 198433334
MT5_LOGIN = 49825877
MT5_PASSWORD = "Prison3R!"
# MT5_SERVER = "HFMarketsGlobal-Live16"
MT5_SERVER = "HFMarketsGlobal-Demo"

TIMEFRAME_BARS = 1000
POLL_SECONDS = 2
RSI_PERIOD = 14  # shared across symbols — it's a ratio-based indicator, not price-scale dependent

FLASK_HOST = "127.0.0.1"
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
USA500 = SymbolConfig(
    symbol="USA500", lot=1.0,
    adx_min=15, rsi_scalp_sell_max=65, rsi_scalp_buy_min=35,
    rsi_with_trend_buy_max=80, rsi_with_trend_sell_min=20,
    adx_strong_trend=25, rsi_with_trend_buy_max_strong=90, rsi_with_trend_sell_min_strong=10,
    scalp_tp_points=5.5, scalp_sl_atr_mult=0.8, scalp_sl_floor=3.0,
    trend_sl_atr_mult=0.75, trend_tp_points=5.5, min_atr=2.0,
    fixed_sl_points=5.00,
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
    fixed_sl_points=5.00,
    # Staircase trailing (2026-08-14, requested directly): "SL baar baar
    # hit hona hai, trailing kafi late update ho raha hai" — the generic
    # trail (40% of TP = 2.2pts before it even starts) left too much room
    # for a reversal to hit the flat 5.00 SL first. Every 1.00pt of
    # favorable movement, SL now steps forward by 0.5pt, starting at the
    # very first point (past open price immediately): +1 -> open+0.5,
    # +2 -> open+1.0, +3 -> open+1.5, ... (mirrored for SELL). Applies to
    # WITH_TREND, scalp, and reversal alike (trail_all_positions() has no
    # mode branch). All other symbols unaffected (TRAIL_STEP_POINTS=None).
    trail_step_points=1.00,
    trail_increment_points=0.5,
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
    scalp_tp_points=0.00100, scalp_sl_atr_mult=0.8, scalp_sl_floor=0.00024,
    trend_sl_atr_mult=0.75, trend_tp_points=0.00100, min_atr=0.0002,
    fixed_sl_points=0.00100,
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
    scalp_tp_points=0.100, scalp_sl_atr_mult=0.8, scalp_sl_floor=0.046,
    trend_sl_atr_mult=0.75, trend_tp_points=0.100, min_atr=0.03,
    fixed_sl_points=0.100,
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
    symbol="USA100", lot=1.0,
    adx_min=15, rsi_scalp_sell_max=65, rsi_scalp_buy_min=35,
    rsi_with_trend_buy_max=80, rsi_with_trend_sell_min=20,
    adx_strong_trend=25, rsi_with_trend_buy_max_strong=90, rsi_with_trend_sell_min_strong=10,
    scalp_tp_points=30.0, scalp_sl_atr_mult=0.8, scalp_sl_floor=22.0,
    trend_sl_atr_mult=0.75, trend_tp_points=30.0, min_atr=2.0,
    fixed_sl_points=30.0,
)

USA30 = SymbolConfig(  # mean M15 ATR ~53.7
    # SL and TP both fixed at flat 50pts (2026-08-11, requested directly) —
    # ATR-based SL kept racing the broker's real minimum stop distance on
    # this fast-moving symbol, causing repeated "Invalid stops" even with a
    # retry (see bot_runner._min_stop_distance / send_order). 50pts is far
    # above any observed minimum (~8pts worst case), sidestepping that
    # entirely, and simple/predictable besides.
    symbol="USA30", lot=1.0,
    adx_min=15, rsi_scalp_sell_max=65, rsi_scalp_buy_min=35,
    rsi_with_trend_buy_max=80, rsi_with_trend_sell_min=20,
    adx_strong_trend=25, rsi_with_trend_buy_max_strong=90, rsi_with_trend_sell_min_strong=10,
    scalp_tp_points=50.0, scalp_sl_atr_mult=0.8, scalp_sl_floor=20.0,
    trend_sl_atr_mult=0.75, trend_tp_points=50.0, min_atr=2.0,
    fixed_sl_points=50.0,
)

SYMBOLS = {
    "USA500": USA500, "USA100": USA100, "USA30": USA30,
    "XAUUSD": XAUUSD, "GBPUSD": GBPUSD, "USDJPY": USDJPY,
}
