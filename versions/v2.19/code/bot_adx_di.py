import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime, timedelta
from random import randrange
import numpy as np

__attempt__ = 0


class USA500:

    def __init__(self, data, mt5, symbol, lot, last_trade_bar_time=None):
        self.data = data.copy()
        self.mt5 = mt5
        self.symbol = symbol
        self.lot = lot
        self.current_date = datetime.now().date()
        self.close = 0.0
        self.high = 0.0
        self.low = 0.0
        self.open = 0.0
        self.previous_close = 0.0
        self.previous_high = 0.0
        self.previous_low = 0.0
        self.previous_open = 0.0
        self.positions = 0.0
        self.last_trade_bar_time = last_trade_bar_time  # one entry per closed candle
        self.init()

    def calculate_indicators(self):
        self.data['50EMA'] = self.data['close'].ewm(span=50, adjust=False).mean()
        self.data['200EMA'] = self.data['close'].ewm(span=200, adjust=False).mean()

        # Proper ATR (True Range + Wilder smooth) — old code used high-low only
        prev_close = self.data['close'].shift(1)
        tr = pd.concat([
            self.data['high'] - self.data['low'],
            (self.data['high'] - prev_close).abs(),
            (self.data['low'] - prev_close).abs()
        ], axis=1).max(axis=1)
        self.data['ATR'] = tr.ewm(alpha=1 / 14, adjust=False).mean()

        if len(self.data) >= 30:
            self.calculate_adx(14)
        else:
            print(f"Not enough data for ADX calculation. Current data length: {len(self.data)}")
            self.data['ADX'] = 0
            self.data['+DI_14'] = 0
            self.data['-DI_14'] = 0

    def calculate_adx(self, period=14):
        df = self.data.copy(deep=True)

        if len(df) < period + 1:
            print(f"Warning: Not enough data for ADX calculation. Need at least {period + 1} bars.")
            self.data['ADX'] = np.nan
            return

        df['H-L'] = df['high'] - df['low']
        df['H-PC'] = abs(df['high'] - df['close'].shift(1))
        df['L-PC'] = abs(df['low'] - df['close'].shift(1))
        df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)

        df['H-PH'] = df['high'] - df['high'].shift(1)
        df['PL-L'] = df['low'].shift(1) - df['low']

        df['+DM'] = np.where((df['H-PH'] > df['PL-L']) & (df['H-PH'] > 0), df['H-PH'], 0)
        df['-DM'] = np.where((df['PL-L'] > df['H-PH']) & (df['PL-L'] > 0), df['PL-L'], 0)

        def wilder_smooth(series, period):
            return series.ewm(alpha=1 / period, adjust=False).mean()

        df[f'TR_{period}'] = wilder_smooth(df['TR'], period)
        df[f'+DM_{period}'] = wilder_smooth(df['+DM'], period)
        df[f'-DM_{period}'] = wilder_smooth(df['-DM'], period)

        df[f'+DI_{period}'] = 100 * (df[f'+DM_{period}'] / df[f'TR_{period}']).replace([np.inf, -np.inf], 0).fillna(0)
        df[f'-DI_{period}'] = 100 * (df[f'-DM_{period}'] / df[f'TR_{period}']).replace([np.inf, -np.inf], 0).fillna(0)

        di_sum = (df[f'+DI_{period}'] + df[f'-DI_{period}']).replace(0, np.nan)
        df['DX'] = 100 * abs(df[f'+DI_{period}'] - df[f'-DI_{period}']) / di_sum
        df['DX'] = df['DX'].fillna(0)

        df['ADX'] = wilder_smooth(df['DX'], period)
        df['ADX'] = df['ADX'].replace([np.inf, -np.inf], 0).ffill().bfill()
        self.data['ADX'] = df['ADX']
        self.data[f'+DI_{period}'] = df[f'+DI_{period}']
        self.data[f'-DI_{period}'] = df[f'-DI_{period}']

    def detect_market_condition(self):
        # Use last CLOSED candle (iloc[-2]) — forming bar [-1] causes false signals
        i = -2
        current_50ema = self.data['50EMA'].iloc[i]
        current_200ema = self.data['200EMA'].iloc[i]
        current_close = self.data['close'].iloc[i]
        previous_close = self.data['close'].iloc[i - 1]
        atr_mean = self.data['ATR'].iloc[-50:].mean()
        current_atr = self.data['ATR'].iloc[i]

        # EMA cross only (original style) — price>EMA was blocking too often
        if current_50ema > current_200ema:
            trend = 'TRENDING_UP'
            print(f"50EMA: {current_50ema:.2f}, 200EMA: {current_200ema:.2f}")
        elif current_50ema < current_200ema:
            trend = 'TRENDING_DOWN'
            print(f"50EMA: {current_50ema:.2f}, 200EMA: {current_200ema:.2f}")
        else:
            trend = 'NEUTRAL'

        if current_atr > atr_mean * 1.2:
            condition = 'VOLATILE'
        elif abs(current_close - previous_close) < (current_atr * 0.25):
            condition = 'RANGING'
        else:
            condition = 'NORMAL'

        return condition, trend

    def init(self):
        self.positions = 0.0
        self.next()

    def should_take_trade(self):
        account_info = mt5.account_info()
        if account_info is None or account_info.equity <= 0:
            return False
        equity = account_info.equity
        margin = account_info.margin
        if margin / equity <= 0.1:
            return True
        print("Don't have sufficient funds to trade")
        return False

    def _atr_sl_tp(self, side):
        """ATR-based SL/TP — fixed 10/40 stops were too tight on M15 USA500."""
        atr = float(self.data['ATR'].iloc[-2])
        atr = max(atr, 2.0)
        entry = float(self.data['close'].iloc[-2])
        sl_dist = atr * 1.5
        tp_dist = atr * 3.0  # ~1:2 risk-reward
        if side == 'BUY':
            return entry - sl_dist, entry + tp_dist
        return entry + sl_dist, entry - tp_dist

    def close_order(self):
        open_positions = mt5.positions_get(symbol=self.symbol)
        if not open_positions:
            return

        atr = float(self.data['ATR'].iloc[-2]) if 'ATR' in self.data.columns else 5.0
        atr = max(atr, 2.0)
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return

        for position in open_positions:
            if position.type == mt5.ORDER_TYPE_BUY:
                price = tick.bid
                profit_pts = price - position.price_open
                # Lock profit once price moves 1 ATR in favor; trail by 0.8 ATR
                if profit_pts >= atr:
                    nsl = price - atr * 0.8
                    nsl = max(nsl, position.price_open + atr * 0.2)  # keep BE+ buffer
                    if position.sl == 0 or nsl > position.sl:
                        self.trailing_stop(
                            symbol=self.symbol,
                            ticket=position.ticket,
                            new_sl=nsl,
                            new_tp=position.tp,
                            comment="Stoploss_Updated"
                        )

            elif position.type == mt5.ORDER_TYPE_SELL:
                price = tick.ask
                profit_pts = position.price_open - price
                if profit_pts >= atr:
                    nsl = price + atr * 0.8
                    nsl = min(nsl, position.price_open - atr * 0.2)
                    if position.sl == 0 or nsl < position.sl:
                        self.trailing_stop(
                            symbol=self.symbol,
                            ticket=position.ticket,
                            new_sl=nsl,
                            new_tp=position.tp,
                            comment="Stoploss_Updated"
                        )

    def _signal_ok(self, side, trend, condition, current_adx, prev_adx,
                   current_di_plus, current_di_minus, prev_di_plus, prev_di_minus):
        """Relaxed entry — closer to original, keeps closed-candle + DI direction."""
        if condition == 'RANGING' or trend == 'NEUTRAL':
            print(f"Skip: condition={condition}, trend={trend}")
            return False

        # Was 25 (too strict). Market ab ADX ~16–18 pe hai.
        if current_adx < 15:
            print(f"ADX ({current_adx:.2f}) < 15 — skip")
            return False

        o = self.data['open'].iloc[-2]
        c = self.data['close'].iloc[-2]

        if side == 'BUY':
            if trend != 'TRENDING_UP':
                return False
            if current_di_plus <= current_di_minus:
                print(f"BUY skip: +DI ({current_di_plus:.2f}) <= -DI ({current_di_minus:.2f})")
                return False
            if c <= o:
                print("BUY skip: closed candle not bullish (red)")
                return False
            return True

        if side == 'SELL':
            if trend != 'TRENDING_DOWN':
                return False
            if current_di_minus <= current_di_plus:
                print(f"SELL skip: -DI ({current_di_minus:.2f}) <= +DI ({current_di_plus:.2f})")
                return False
            if c >= o:
                print("SELL skip: closed candle not bearish (green)")
                return False
            return True

        return False

    def open_order(self):
        condition, trend = self.detect_market_condition()
        open_positions = mt5.positions_get(symbol=self.symbol) or []

        has_buy_position = any(pos.type == mt5.ORDER_TYPE_BUY for pos in open_positions)
        has_sell_position = any(pos.type == mt5.ORDER_TYPE_SELL for pos in open_positions)

        # One evaluation per closed M15 bar (signals don't change on forming bar)
        bar_time = self.data['time'].iloc[-2]
        if self.last_trade_bar_time is not None and bar_time == self.last_trade_bar_time:
            print("Already evaluated this closed bar — manage open trades only")
            return

        if 'ADX' not in self.data.columns or len(self.data) < 5:
            print("ADX not calculated or data empty")
            return

        current_adx = self.data['ADX'].iloc[-2]
        current_di_plus = self.data['+DI_14'].iloc[-2]
        current_di_minus = self.data['-DI_14'].iloc[-2]
        prev_adx = self.data['ADX'].iloc[-3]
        prev_di_plus = self.data['+DI_14'].iloc[-3]
        prev_di_minus = self.data['-DI_14'].iloc[-3]

        if pd.isna(current_adx):
            print("Warning: ADX value is NaN")
            return

        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            print("No tick data")
            return

        # Mark bar evaluated so we don't re-enter every 5 seconds
        self.last_trade_bar_time = bar_time

        # Single position only — no same-side stacking, no hedging
        if not has_buy_position and not has_sell_position:
            if self._signal_ok('BUY', trend, condition, current_adx, prev_adx,
                               current_di_plus, current_di_minus, prev_di_plus, prev_di_minus):
                if self.should_take_trade():
                    sl, tp = self._atr_sl_tp('BUY')
                    self.order(
                        price=tick.ask,
                        type=mt5.ORDER_TYPE_BUY,
                        comment="BUY",
                        sl=sl,
                        tp=tp
                    )
                    return

            if self._signal_ok('SELL', trend, condition, current_adx, prev_adx,
                               current_di_plus, current_di_minus, prev_di_plus, prev_di_minus):
                if self.should_take_trade():
                    sl, tp = self._atr_sl_tp('SELL')
                    self.order(
                        price=tick.bid,
                        type=mt5.ORDER_TYPE_SELL,
                        comment="SELL",
                        sl=sl,
                        tp=tp
                    )
                    return

        if has_buy_position or has_sell_position:
            print("Position already open — no new entry")
        elif condition == 'RANGING':
            print("Market is Range Bound, wait for the signal")
        elif trend == 'NEUTRAL':
            print("Market trend is Neutral, wait for the signal")
        else:
            print("No valid entry setup on this bar")

    def increment_attempt(self):
        global __attempt__
        __attempt__ += 1

    def display_attempt(self):
        print("Attempt #", __attempt__)
        now = datetime.now()
        dt_string = now.strftime("%d/%m/%Y %H:%M:%S")
        print("date and time =", dt_string)
        condition, trend = self.detect_market_condition()
        print(f"Market condition detected: Condition: {condition}, Trend: {trend}")

        if 'ADX' in self.data.columns and len(self.data) > 2:
            current_adx = self.data['ADX'].iloc[-2]
            if pd.isna(current_adx):
                current_adx = 0
        else:
            current_adx = 0

        if '+DI_14' in self.data.columns and len(self.data) > 2:
            current_di_plus = self.data['+DI_14'].iloc[-2]
            if pd.isna(current_di_plus):
                current_di_plus = 0
        else:
            current_di_plus = 0

        if '-DI_14' in self.data.columns and len(self.data) > 2:
            current_di_minus = self.data['-DI_14'].iloc[-2]
            if pd.isna(current_di_minus):
                current_di_minus = 0
        else:
            current_di_minus = 0

        atr = self.data['ATR'].iloc[-2] if 'ATR' in self.data.columns else 0
        print(f"Current ADX value: {current_adx:.2f}")
        print(f"Current +DI: {current_di_plus:.2f}")
        print(f"Current -DI: {current_di_minus:.2f}")
        print(f"ATR(14): {atr:.2f}")

    def next(self):
        # Signal candle = last closed bar
        self.close = self.data['close'].values[-2]
        self.open = self.data['open'].values[-2]
        self.high = self.data['high'].values[-2]
        self.low = self.data['low'].values[-2]
        self.previous_high = self.data['high'].values[-3]
        self.previous_low = self.data['low'].values[-3]

        self.positions = mt5.positions_total()

        self.calculate_indicators()
        self.increment_attempt()
        self.display_attempt()
        self.open_order()
        self.close_order()

    def order(self, price, type, comment, sl, tp):
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": self.lot,
            "type": type,
            "price": price,
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "magic": randrange(1000000),
            "comment": "{}".format(comment),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK
        }
        result = mt5.order_send(request)
        if result is None:
            print("Order send failed, error code =", mt5.last_error())
            return
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"Order Send Error: Retcode = {result.retcode}")
            if result.comment:
                print(f"Error Comment: {result.comment}")
            if result.volume:
                print(f"Volume Traded: {result.volume}")
        else:
            print(f"{result.request.comment} Order successfully placed! SL={sl:.2f} TP={tp:.2f}")
            print(f"Position # {self.positions}, Ticket # {result.order}")

    def trailing_stop(self, symbol, ticket, new_sl, new_tp, comment):
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return
        position = positions[0]
        current_sl = position.sl

        if position.type == mt5.ORDER_TYPE_BUY and (current_sl == 0 or new_sl > current_sl):
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": symbol,
                "position": ticket,
                "sl": round(new_sl, 2),
                "tp": new_tp,
                "comment": comment,
            }
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"Trailing stop updated for BUY: New SL = {new_sl:.2f}")

        elif position.type == mt5.ORDER_TYPE_SELL and (current_sl == 0 or new_sl < current_sl):
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": symbol,
                "position": ticket,
                "sl": round(new_sl, 2),
                "tp": new_tp,
                "comment": comment,
            }
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"Trailing stop updated for SELL: New SL = {new_sl:.2f}")

    def get_trade_stats(self):
        start_date = datetime(2025, 1, 1)
        end_date = datetime.now()

        deals = mt5.history_deals_get(start_date, end_date)
        if deals is None or len(deals) == 0:
            print("No deals found, check your account history settings!")
            return
        total_trades = 600
        df = pd.DataFrame(list(deals), columns=deals[0]._asdict().keys())
        df = df.tail(total_trades)

        zero_profit_rows = df[df['profit'] == 0].shape[0]
        df = df[df['profit'] != 0]

        if zero_profit_rows > 0:
            extra_deals = mt5.history_deals_get(start_date - timedelta(days=30), end_date)
            if extra_deals:
                extra_df = pd.DataFrame(list(extra_deals), columns=extra_deals[0]._asdict().keys())
                extra_df = extra_df[extra_df['profit'] != 0]
                df = pd.concat([df, extra_df]).tail(total_trades)

        winning_trades = df[df['profit'] > 0].shape[0]
        losing_trades = df[df['profit'] < 0].shape[0]
        total_profit = df['profit'].sum()

        print("Trade Statistics:")
        print(f"Total Trades: {df.shape[0]}")
        print(f"Total Profit: {total_profit}")
        print(f"Winning Trades: {winning_trades}")
        print(f"Losing Trades: {losing_trades}")
        if df.shape[0] > 0:
            print(f"Win Ratio: {winning_trades / df.shape[0] * 100:.2f}%")

        return df


if __name__ == "__main__":
    mt5.initialize()
    authorized = mt5.login(198433334, password="Prison3R!", server="HFMarketsGlobal-Live16")
    if authorized:
        print("Connected to MT5 account")
        # Persist last-evaluated bar across loop iterations
        last_bar_time = None
        while True:
            try:
                symbol = "USA500"
                lot = 1.0
                ha_data = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 1000)
                ha_data = pd.DataFrame(ha_data)
                ha_data.columns = ['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume']
                if len(ha_data) >= 30:
                    bot = USA500(ha_data, mt5, symbol, lot, last_trade_bar_time=last_bar_time)
                    last_bar_time = bot.last_trade_bar_time
                else:
                    print(f"Not enough data to process. Need at least 30 bars, got {len(ha_data)}")

                time.sleep(5)
            except Exception as e:
                print(f"Error encountered: {e}")
                time.sleep(10)
    else:
        print("Failed to connect:", mt5.last_error())
