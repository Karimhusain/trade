import asyncio
import websockets
import json
import ccxt
import ta
import pandas as pd
import requests
import logging
from datetime import datetime

# === KONFIG TELEGRAM ===
TELEGRAM_TOKEN = '7035454220:AAF9OtWRsS4sIobpMIIFyhckEhlRYFDpGEA'
CHAT_ID = '6593134178'

# === KONFIG PAIR & TIMEFRAME ===
PAIR = 'BTC/USDT'
LIMIT = 200

# Setup logging
logging.basicConfig(
    filename='trading_bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def send_to_telegram(msg):
    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
        res = requests.post(url, data={'chat_id': CHAT_ID, 'text': msg})
        if res.status_code != 200:
            logging.error(f"Telegram send failed: {res.text}")
    except Exception as e:
        logging.error(f"Exception sending Telegram: {e}")

exchange = ccxt.binance()

def fetch_ohlcv_safe(pair, timeframe='1m', limit=LIMIT):
    try:
        data = exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        logging.error(f"Error fetching OHLCV: {e}")
        return None

def calculate_indicators(df):
    try:
        df['ema50'] = ta.trend.ema_indicator(df['close'], 50)
        df['ema200'] = ta.trend.ema_indicator(df['close'], 200)
        df['rsi'] = ta.momentum.rsi(df['close'], 14)
        df['macd'] = ta.trend.macd_diff(df['close'])
        df['avg_vol'] = df['volume'].rolling(20).mean()
    except Exception as e:
        logging.error(f"Error calculating indicators: {e}")

def bullish_engulfing(df):
    try:
        return df['close'].iloc[-1] > df['open'].iloc[-1] and df['open'].iloc[-2] > df['close'].iloc[-2]
    except:
        return False

def bearish_pinbar(df):
    try:
        last = df.iloc[-1]
        body = abs(last['close'] - last['open'])
        wick = last['high'] - last['low']
        return body / wick < 0.3 and last['high'] - max(last['open'], last['close']) < wick * 0.2
    except:
        return False

def multi_timeframe_analysis():
    try:
        df_1h = fetch_ohlcv_safe(PAIR, '1h')
        df_4h = fetch_ohlcv_safe(PAIR, '4h')
        if df_1h is None or df_4h is None:
            return None, None
        df_1h['ema50'] = ta.trend.ema_indicator(df_1h['close'], 50)
        df_4h['ema50'] = ta.trend.ema_indicator(df_4h['close'], 50)
        trend_1h = 'UP' if df_1h['ema50'].iloc[-1] > df_1h['ema50'].iloc[-2] else 'DOWN'
        trend_4h = 'UP' if df_4h['ema50'].iloc[-1] > df_4h['ema50'].iloc[-2] else 'DOWN'
        return trend_1h, trend_4h
    except Exception as e:
        logging.error(f"Error in multi_timeframe_analysis: {e}")
        return None, None

def macro_global_trend(df):
    try:
        if df['ema200'].iloc[-1] > df['ema200'].iloc[-2]:
            return 'Pasar Bullish (Sentimen Global Positif)'
        elif df['ema200'].iloc[-1] < df['ema200'].iloc[-2]:
            return 'Pasar Bearish (Sentimen Global Negatif)'
        else:
            return 'Pasar Netral (Sentimen Global Stabil)'
    except Exception as e:
        logging.error(f"Error in macro_global_trend: {e}")
        return 'Data tidak valid'

def calculate_trade_levels(df, trade_type):
    try:
        entry_price = df['close'].iloc[-1]
        atr = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14).iloc[-1]
        if trade_type == 'LONG':
            take_profit = entry_price + atr * 2
            stop_loss = entry_price - atr
        elif trade_type == 'SHORT':
            take_profit = entry_price - atr * 2
            stop_loss = entry_price + atr
        else:
            return None, None, None
        return entry_price, take_profit, stop_loss
    except Exception as e:
        logging.error(f"Error calculating trade levels: {e}")
        return None, None, None

def risk_reward_ratio(entry, tp, sl):
    try:
        if not all([entry, tp, sl]):
            return None
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        if risk == 0:
            return None
        rr = reward / risk
        return round(rr, 2)
    except Exception as e:
        logging.error(f"Error calculating risk reward ratio: {e}")
        return None

async def price_feed():
    url = "wss://stream.binance.com:9443/ws/btcusdt@trade"
    async with websockets.connect(url) as websocket:
        while True:
            try:
                message = await websocket.recv()
                data = json.loads(message)
                price = float(data['p'])
                logging.info(f"Harga BTC terbaru: {price}")

                df = fetch_ohlcv_safe(PAIR, '1m')
                if df is None:
                    logging.warning("Tidak bisa fetch OHLCV data, skip analisa.")
                    await asyncio.sleep(30)
                    continue

                calculate_indicators(df)

                long_trend_now = 'UP' if df['ema50'].iloc[-1] > df['ema200'].iloc[-1] else 'DOWN'
                vol_spike_now = df['volume'].iloc[-1] > df['avg_vol'].iloc[-1] * 1.5
                wick_low_now = df['low'].iloc[-1] < df['low'].iloc[-2] and df['close'].iloc[-1] > df['low'].iloc[-1] + (df['high'].iloc[-1] - df['low'].iloc[-1]) * 0.5
                wick_high_now = df['high'].iloc[-1] > df['high'].iloc[-2] and df['close'].iloc[-1] < df['high'].iloc[-1] - (df['high'].iloc[-1] - df['low'].iloc[-1]) * 0.5

                trend_1h_now, trend_4h_now = multi_timeframe_analysis()
                sentiment_now = 'Netral'
                macd_sentiment_now = 'Bullish' if df['macd'].iloc[-1] > 0 else 'Bearish'
                global_trend_now = macro_global_trend(df)

                bias = ''
                entry_price, take_profit, stop_loss = None, None, None

                if long_trend_now == 'UP' and bullish_engulfing(df) and vol_spike_now and wick_low_now:
                    bias = 'BUY'
                    entry_price, take_profit, stop_loss = calculate_trade_levels(df, 'LONG')
                elif long_trend_now == 'DOWN' and bearish_pinbar(df) and vol_spike_now and wick_high_now:
                    bias = 'SELL'
                    entry_price, take_profit, stop_loss = calculate_trade_levels(df, 'SHORT')
                elif long_trend_now == 'UP' and df['macd'].iloc[-1] > 0 and df['rsi'].iloc[-1] < 70:
                    bias = 'BUY'
                    entry_price, take_profit, stop_loss = calculate_trade_levels(df, 'LONG')
                elif long_trend_now == 'DOWN' and df['macd'].iloc[-1] < 0 and df['rsi'].iloc[-1] > 30:
                    bias = 'SELL'
                    entry_price, take_profit, stop_loss = calculate_trade_levels(df, 'SHORT')

                rr = risk_reward_ratio(entry_price, take_profit, stop_loss)

                msg = f"""
📊 [Analisis Real-Time BTCUSDT]
⏰ Waktu: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC
💰 Harga: {price}
📈 Tren Jangka Panjang: {'🔼 UP' if long_trend_now == 'UP' else '🔽 DOWN'}
⏳ Multi Time Frame: 1H -> {('🔼 UP' if trend_1h_now == 'UP' else '🔽 DOWN') if trend_1h_now else '-'}, 4H -> {('🔼 UP' if trend_4h_now == 'UP' else '🔽 DOWN') if trend_4h_now else '-'}
📊 Volume Spike: {'⚡ Ya' if vol_spike_now else '❌ Tidak'}
🕯️ Pola Candlestick: {'🔥 Bullish Engulfing' if bullish_engulfing(df) else '🛑 Bearish Pinbar' if bearish_pinbar(df) else '— Tidak Ada'}
💡 Liquidity Grab: {'⬇️ Wick Down' if wick_low_now else '⬆️ Wick Up' if wick_high_now else '— Tidak Ada'}
📉 Sentimen Pasar (RSI): {sentiment_now}
📊 Sentimen MACD: {'📈 Bullish' if macd_sentiment_now == 'Bullish' else '📉 Bearish'}
🌐 Tren Global: {global_trend_now}
🚦 Sinyal: {('🟢 LONG' if bias == 'BUY' else '🔴 SHORT') if bias else '⚪ Tidak Ada setup yang valid'}
🔖 Harga Entry: {(f'{entry_price:.2f}') if entry_price else '-'}
🎯 Take Profit: {(f'{take_profit:.2f}') if take_profit else '-'}
⛔ Stop Loss: {(f'{stop_loss:.2f}') if stop_loss else '-'}
📊 Risk/Reward Ratio: {rr if rr else '-'}
"""
                if bias:
                    send_to_telegram(msg)
                else:
                    logging.info("Tidak ada setup valid, tidak kirim ke Telegram.")

                await asyncio.sleep(1800)  # delay 30 menit

            except Exception as e:
                logging.error(f"Error di price_feed loop: {e}")
                await asyncio.sleep(30)

if __name__ == '__main__':
    logging.info("Bot mulai berjalan...")
    try:
        asyncio.run(price_feed())
    except Exception as e:
        logging.error(f"Fatal error, bot berhenti: {e}")
        send_to_telegram(f"Bot mengalami error fatal: {e}")
