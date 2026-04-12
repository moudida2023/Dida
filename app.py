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

ACTIVE_TRADES = {} 
EXCLUDE_LIST = ['USDT', 'USDC', 'BUSD', 'DAI', 'BEAR', 'BULL', '3L', '5L', '3S', '5S']

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except: pass

# --- دالة تحليل نبض السوق (Market Pulse) ---
def get_market_pulse(exchange):
    try:
        # فحص البيتكوين كمرجع للسوق
        btc = exchange.fetch_ticker('BTC/USDT')
        change_24h = float(btc['percentage'])
        status = "🔥 نشط" if abs(change_24h) > 2 else "😴 هادئ"
        return f"حالة السوق: {status} ({change_24h:+.2f}%)"
    except: return "حالة السوق: غير معروفة"

# --- المحلل الفني الصارم (شرط 100/100) ---
def analyze_strict_100(symbol, exchange):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # المتوسطات الذهبية
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        
        # البولنجر (قياس الانفجار)
        sma20 = df['close'].rolling(20).mean()
        std20 = df['close'].rolling(20).std()
        upper_bb = sma20 + (std20 * 2)
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        score = 0
        # 1. فلتر الاتجاه (40 نقطة)
        if last['close'] > last['ema200']: score += 40
        # 2. فلتر الزخم (30 نقطة)
        if last['ema9'] > last['ema21'] and prev['ema9'] <= prev['ema21']: score += 30
        # 3. فلتر الاختراق (30 نقطة)
        if last['close'] > upper_bb.iloc[-1]: score += 30
        
        return score, last['close']
    except: return 0, 0

async def monitor_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    pulse = get_market_pulse(exchange)
    send_telegram_msg(f"🚀 *Bot v620 Active*\n🎯 Mode: **Strict 100/100**\n📊 {pulse}")

    while True:
        try:
            # 1. ملاحقة الأرباح (Trailing Take Profit)
            for sym in list(ACTIVE_TRADES.keys()):
                ticker = exchange.fetch_ticker(sym)
                curr_p = float(ticker['last'])
                data = ACTIVE_TRADES[sym]
                
                pnl = ((curr_p - data['entry_price']) / data['entry_price']) * 100
                data['highest_price'] = max(data['highest_price'], curr_p)
                
                # تفعيل الملاحقة عند 3% والخروج عند تراجع 0.5%
                if ((data['highest_price'] - data['entry_price']) / data['entry_price']) * 100 >= 3.0:
                    drop = ((data['highest_price'] - curr_p) / data['highest_price']) * 100
                    if drop >= 0.5:
                        send_telegram_msg(f"💰 *تم قنص الأرباح!*\n🪙 {sym}\n📈 الربح النهائي: {pnl:.2f}%")
                        del ACTIVE_TRADES[sym]
                elif pnl <= -3.0:
                    send_telegram_msg(f"❌ *إغلاق وقائي (SL)*\n🪙 {sym}\n📉 الخسارة: {pnl:.2f}%")
                    del ACTIVE_TRADES[sym]

            # 2. البحث عن الـ 100/100
            markets = exchange.load_markets()
            symbols = [s for s in markets if '/USDT' in s and not any(ex in s for ex in EXCLUDE_LIST)][:60]
            
            for s in symbols:
                if s not in ACTIVE_TRADES and len(ACTIVE_TRADES) < 3: # بحد أقصى 3 صفقات للجودة
                    score, price = analyze_strict_100(s, exchange)
                    if score == 100:
                        ACTIVE_TRADES[s] = {'entry_price': price, 'highest_price': price}
                        send_telegram_msg(f"✅ *فرصة ذهبية (100/100)*\n🪙 العملة: {s}\n💵 السعر: {price}\n📊 الحالة: انفجار سعري مؤكد")

            await asyncio.sleep(60)
        except: await asyncio.sleep(30)

@app.route('/')
def home():
    return f"Bot v620 - 100/100 Strategy Active. Trades: {len(ACTIVE_TRADES)}"

if __name__ == "__main__":
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
