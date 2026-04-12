import os
import threading
import asyncio
import ccxt
import pandas as pd
import requests
import time
from flask import Flask
from datetime import datetime

app = Flask(__name__)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# مخزن مؤقت في الذاكرة بدلاً من قاعدة البيانات
ACTIVE_TRADES = {} # { 'BTC/USDT': {'entry_price': 60000, 'highest_price': 61000, ...} }

# إعدادات التداول
TP_ACTIVATE = 3.0
TRAILING_DROP = 0.5
SL_VAL = -3.0
TRADE_INVESTMENT = 50.0
EXCLUDE_LIST = ['USDT', 'USDC', 'BUSD', 'DAI', 'BEAR', 'BULL', '3L', '5L', '3S', '5S']

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

# --- ANALYSIS LOGIC ---
def analyze_indicators(symbol, exchange):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # حساب بسيط للـ EMA
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # شرط دخول مبسط (يمكنك إعادة تفعيل السكور الكامل هنا)
        if last['close'] > last['ema200'] and last['ema9'] > last['ema21'] and prev['ema9'] <= prev['ema21']:
            return True, last['close']
        return False, 0
    except:
        return False, 0

async def monitor_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    send_telegram_msg("🚀 *Bot v616 Online (Sans DB)*\nMode: Local RAM Memory")

    while True:
        try:
            # 1. إدارة الصفقات المفتوحة في الذاكرة
            for symbol in list(ACTIVE_TRADES.keys()):
                ticker = exchange.fetch_ticker(symbol)
                curr_p = float(ticker['last'])
                trade_data = ACTIVE_TRADES[symbol]
                
                entry_p = trade_data['entry_price']
                pnl = ((curr_p - entry_p) / entry_p) * 100
                
                # تحديث أعلى سعر للملاحقة
                trade_data['highest_price'] = max(trade_data.get('highest_price', curr_p), curr_p)
                highest_p = trade_data['highest_price']

                # شروط الخروج
                if pnl <= SL_VAL:
                    send_telegram_msg(f"❌ *Stop Loss:* {symbol} ({pnl:.2f}%)")
                    del ACTIVE_TRADES[symbol]
                elif ((highest_p - entry_p) / entry_p) * 100 >= TP_ACTIVATE:
                    drop = ((highest_p - curr_p) / highest_p) * 100
                    if drop >= TRAILING_DROP:
                        send_telegram_msg(f"💰 *Trailing TP:* {symbol} ({pnl:.2f}%)")
                        del ACTIVE_TRADES[symbol]

            # 2. البحث عن صفقات جديدة
            markets = exchange.load_markets()
            symbols = [s for s in markets if '/USDT' in s and not any(ex in s for ex in EXCLUDE_LIST)][:50]

            for sym in symbols:
                if sym not in ACTIVE_TRADES and len(ACTIVE_TRADES) < 5:
                    ready, price = analyze_indicators(sym, exchange)
                    if ready:
                        ACTIVE_TRADES[sym] = {
                            'entry_price': price,
                            'highest_price': price,
                            'time': datetime.now()
                        }
                        send_telegram_msg(f"✅ *Nouvel Ordre:* {sym}\nPrix: {price}")

            await asyncio.sleep(120) # فحص كل دقيقتين
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(30)

@app.route('/')
def home():
    return f"Bot Running v616 (No DB) - Active Trades: {len(ACTIVE_TRADES)}"

if __name__ == "__main__":
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
