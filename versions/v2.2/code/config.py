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


# USA500: TP capped at fixed points rather than an ATR multiple — a 3x-ATR
# target (~17-27pts observed) almost never got hit (backtested 2026-08-10:
# 31% win rate over 957 historical WITH_TREND signals); most losers reversed
# within ~5pts of entry. SL halved (was 1.5x) to sit closer to that TP
# instead of risking 2-3x the reward on every trade.
USA500 = SymbolConfig(
    symbol="USA500", lot=1.0,
    adx_min=15, rsi_scalp_sell_max=65, rsi_scalp_buy_min=35,
    rsi_with_trend_buy_max=80, rsi_with_trend_sell_min=20,
    adx_strong_trend=25, rsi_with_trend_buy_max_strong=90, rsi_with_trend_sell_min_strong=10,
    scalp_tp_points=5.5, scalp_sl_atr_mult=0.8, scalp_sl_floor=3.0,
    trend_sl_atr_mult=0.75, trend_tp_points=5.5, min_atr=2.0,
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
    # (2026-08-13, requested directly, values only — e.g. open 4565.00 ->
    # SL 4563.00). WITH_TREND SL (trend_sl_atr_mult below) and every TP
    # untouched, exactly as before — see SCALP_FIXED_SL_POINTS in
    # config.py's SymbolConfig for how this stays scoped to scalp only.
    symbol="XAUUSD", lot=1.0,
    adx_min=15, rsi_scalp_sell_max=65, rsi_scalp_buy_min=35,
    rsi_with_trend_buy_max=80, rsi_with_trend_sell_min=20,
    adx_strong_trend=25, rsi_with_trend_buy_max_strong=90, rsi_with_trend_sell_min_strong=10,
    scalp_tp_points=5.5, scalp_sl_atr_mult=0.8, scalp_sl_floor=3.0,
    trend_sl_atr_mult=0.75, trend_tp_points=5.5, min_atr=2.0,
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
    # touched). NOTE: ROUND_STEP's away-from-entry rounding can still add
    # up to one more 0.00100 step unevenly to each side — see USDJPY's
    # comment above for a worked example; same caveat applies here.
    # FOLLOW-UP, same day: WITH_TREND's SL specifically was landing up to
    # ~0.00200 away from entry (nearly double the intended 0.00100) —
    # user: "GBPUSD ka stoploss bohat door ja raha hai... .00100 tak le
    # kar ao WITH_TREND ke liye." trend_sl_fine_rounding=True below skips
    # ROUND_STEP for WITH_TREND's SL only (fresh orders AND trailing),
    # keeping it close to the flat 0.00100 target; scalp's SL, and every
    # TP, still round on the coarse 0.00100 grid as before.
    symbol="GBPUSD", lot=1.0,
    adx_min=15, rsi_scalp_sell_max=65, rsi_scalp_buy_min=35,
    rsi_with_trend_buy_max=80, rsi_with_trend_sell_min=20,
    adx_strong_trend=25, rsi_with_trend_buy_max_strong=90, rsi_with_trend_sell_min_strong=10,
    scalp_tp_points=0.00100, scalp_sl_atr_mult=0.8, scalp_sl_floor=0.00024,
    trend_sl_atr_mult=0.75, trend_tp_points=0.00100, min_atr=0.0002,
    round_step=0.00100,  # 100 points = 10 pips, requested directly 2026-08-12
    fixed_sl_points=0.00100,
    trend_sl_fine_rounding=True,
)

USDJPY = SymbolConfig(  # mean M15 ATR ~0.124 (~12.4 pips at JPY's 0.01-pip scale)
    # TP widened from 0.084 to 0.5 (2026-08-11, requested directly) — 0.084
    # was too tight relative to its SL, opposite problem from USA500/etc.
    # SUPERSEDED 2026-08-13 (requested directly): a live WITH_TREND position
    # showed SL close (0.122) but TP blown far out (0.578) — TP fixed at
    # 0.5 was already ~5x the ATR-based SL even before ROUND_STEP grid
    # rounding added on top. User asked for TP at the SAME level as SL, then
    # chose flat/fixed over ATR-based entirely (same pattern as USA30/
    # USA100): SL and TP both now fixed at flat 0.100 pre-rounding. NOTE:
    # ROUND_STEP's away-from-entry rounding (see bot_runner._round_price)
    # can still add up to one more 0.100 step unevenly to each side
    # depending on where entry falls on the grid — verified directly: SL
    # 0.100 -> ~0.122 actual, TP 0.100 -> ~0.178 actual in one worked
    # example. Distances are now close (~1.1-1.8x apart) instead of the old
    # ~5x gap, but not perfectly identical every time; flag to the user if
    # exact 1:1 turns out to matter more than this.
    symbol="USDJPY", lot=1.0,
    adx_min=15, rsi_scalp_sell_max=65, rsi_scalp_buy_min=35,
    rsi_with_trend_buy_max=80, rsi_with_trend_sell_min=20,
    adx_strong_trend=25, rsi_with_trend_buy_max_strong=90, rsi_with_trend_sell_min_strong=10,
    # Scalp (and its reversal) SL cut further, 2026-08-13, requested
    # directly — was 0.100 (same flat value as WITH_TREND, set above),
    # now flat 0.025, SCALP-ONLY (same SCALP_FIXED_SL_POINTS mechanism as
    # XAUUSD's 2.00pt override same day). WITH_TREND SL stays at flat
    # 0.100 via FIXED_SL_POINTS below, completely untouched — see
    # strategy._sl_tp_scalp, which checks SCALP_FIXED_SL_POINTS before
    # FIXED_SL_POINTS, vs. _sl_tp_trend, which never reads
    # SCALP_FIXED_SL_POINTS at all. TP unchanged (still flat 0.100, both
    # modes).
    scalp_tp_points=0.100, scalp_sl_atr_mult=0.8, scalp_sl_floor=0.046,
    trend_sl_atr_mult=0.75, trend_tp_points=0.100, min_atr=0.03,
    round_step=0.100,  # 100 points = 10 pips, requested directly 2026-08-12
    fixed_sl_points=0.100,
    scalp_fixed_sl_points=0.025,
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
