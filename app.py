import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
import pandas as pd
import numpy as np
import requests
import time
from flask import Flask
from datetime import datetime, timedelta

app = Flask(__name__)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"

MAX_VIRTUAL_TRADES = 10
TRADE_INVESTMENT = 50.0
TP_VAL, SL_VAL = 3.0, -3.0
EXCLUDE_LIST = ['USDT', 'USDC', 'BUSD', 'DAI', 'BEAR', 'BULL', '3L', '3S']

# --- وظائف الحساب اليدوي للمؤشرات ---
def calculate_ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def calculate_adx(df, length=14):
    plus_dm = df['high'].diff()
    minus_dm = df['low'].diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0
    
    tr1 = pd.DataFrame(df['high'] - df['low'])
    tr2 = pd.DataFrame(abs(df['high'] - df['close'].shift(1)))
    tr3 = pd.DataFrame(abs(df['low'] - df['close'].shift(1)))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(length).mean()
    
    plus_di = 100 * (plus_dm.rolling(length).mean() / atr)
    minus_di = 100 * (abs(minus_dm).rolling(length).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(length).mean()
    return adx

def analyze_indicators(symbol, exchange):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # حساب EMA
        df['ema9'] = calculate_ema(df['close'], 9)
        df['ema21'] = calculate_ema(df['close'], 21)
        df['ema200'] = calculate_ema(df['close'], 200)
        
        # حساب Bollinger Bands
        sma20 = df['close'].rolling(window=20).mean()
        std20 = df['close'].rolling(window=20).std()
        df['bb_upper'] = sma20 + (std20 * 2)
        
        # حساب ADX
        df['adx'] = calculate_adx(df)
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # الشروط الفنية
        c1 = last['close'] > last['ema200']
        c2 = last['ema9'] > last['ema21'] and prev['ema9'] <= prev['ema21']
        c3 = last['close'] > last['bb_upper']
        c4 = last['adx'] > 25
        
        if c1 and c2 and c3 and c4:
            return True, last['close']
        return False, 0
    except: return False, 0

# --- الأوامر المساعدة ---
def send_telegram_msg(message):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                       json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})
    except: pass

# --- المحرك الرئيسي (Monitor Engine) ---
async def monitor_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    send_telegram_msg("🚀 *Bot Démarré (v598)*\nMode: Manuel (No pandas_ta)")

    while True:
        try:
            markets = exchange.load_markets()
            valid_symbols = [s for s in markets if '/USDT' in s and not any(ex in s for ex in EXCLUDE_LIST)]
            valid_symbols = valid_symbols[:150]
            
            conn = psycopg2.connect(DB_URL, sslmode='require')
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            # (منطق فتح وإغلاق الصفقات المذكور في v597...)
            # سأختصر الكود هنا ليركز على التعديل المطلوب
            
            conn.commit()
            cur.close(); conn.close()
            await asyncio.sleep(60)
        except: await asyncio.sleep(30)

@app.route('/')
def index(): return "Bot Active v598"

if __name__ == "__main__":
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
