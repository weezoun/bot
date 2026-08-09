# MT5 / bot settings — edit here only (not in the UI)

MT5_LOGIN = 198433334
MT5_PASSWORD = "Prison3R!"
MT5_SERVER = "HFMarketsGlobal-Live16"

SYMBOL = "USA500"
LOT = .20
TIMEFRAME_BARS = 1000
POLL_SECONDS = 2

# Strategy thresholds
ADX_MIN = 15
RSI_PERIOD = 14
RSI_SCALP_SELL_MAX = 65   # counter-trend SELL when trend UP
RSI_SCALP_BUY_MIN = 35    # counter-trend BUY when trend DOWN
RSI_WITH_TREND_BUY_MAX = 80   # was 70 — RSI can stay pinned >70 for hours in a strong
                              # sustained uptrend; a hard 70 ceiling blocked entry the
                              # whole time and only let the bot in after price had
                              # already run far (e.g. missed ~34pts on 2026-08-03)
RSI_WITH_TREND_SELL_MIN = 20  # was 30 — same reasoning, mirrored for downtrends

# When ADX confirms a genuinely strong/persistent trend (not just a spike),
# give RSI even more room before treating it as "too extended to enter" —
# a confirmed strong trend can keep RSI pinned near its extreme for a long
# stretch without that meaning exhaustion/reversal.
ADX_STRONG_TREND = 25
RSI_WITH_TREND_BUY_MAX_STRONG = 90
RSI_WITH_TREND_SELL_MIN_STRONG = 10

SCALP_TP_POINTS = 10.0
SCALP_SL_ATR_MULT = 0.8
TREND_SL_ATR_MULT = 1.5
TREND_TP_ATR_MULT = 3.0

FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5050
LOG_MAX = 200

# When a position closes because its SL (or a trailing-adjusted SL) got hit,
# hold off on any new entry until the NEXT M15 candle starts, then let
# decide()/evaluate_entry() re-evaluate fresh with full confirmation (RSI,
# ADX, DI, candle color) — no direction is forced either way.
SL_COOLDOWN_UNTIL_NEXT_CANDLE = True
