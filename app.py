import asyncio
import ccxt.pro as ccxt
import pandas as pd
import psycopg2
from psycopg2 import extras
import os
import threading
import requests
from flask import Flask, render_template_string
from datetime import datetime

# ======================== 1. الإعدادات والربط ========================
app = Flask(__name__)

# جلب رابط قاعدة البيانات من إعدادات Render
DB_URL = os.environ.get('DATABASE_URL')

# تصحيح الرابط ليتوافق مع مكتبة بايثون
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# إعدادات الاستراتيجية
INITIAL_BALANCE = 500.0     # الرصيد الافتراضي حسب طلبك
TRADE_AMOUNT = 50.0        # حجم الصفقة الواحدة
MAX_OPEN_TRADES = 10       # أقصى عدد صفقات مفتوحة
STOP_LOSS_PCT = -0.05      # وقف خسارة 5%
MIN_PROFIT_FOR_EXIT = 0.05 # هدف ربح 5%
EXIT_SCORE_THRESHOLD = 95  # سكور الخروج
MIN_VOLUME_24H = 1000000   # الحد الأدنى للسيولة (1 مليون دولار)

EXCLUDED_COINS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=5)
    except: pass

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS trades 
            (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, 
             exit_price REAL, investment REAL, status TEXT, score INTEGER, 
             open_time TEXT, close_time TEXT)''')
        conn.commit()
        cur.close(); conn.close()
        print("✅ قاعدة البيانات جاهزة ومتصلة بنجاح.")
    except Exception as e:
        print(f"❌ فشل الاتصال بقاعدة البيانات: {e}")

# ======================== 2. محرك التحليل الفني ========================

async def perform_analysis(sym, exchange_instance):
    try:
        bars = await exchange_instance.fetch_ohlcv(sym, timeframe='1h', limit=40)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']
        
        score = 0
        # Bollinger Bands Width
        ma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        bw = ((ma20 + 2*std20) - (ma20 - 2*std20)) / (ma20 + 1e-9)
        if bw.iloc[-1] < 0.045: score += 50 
        
        # RSI Analysis
        delta = close.diff(); gain = (delta.where(delta > 0, 0)).rolling(14).mean(); loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 40 < rsi.iloc[-1] < 70: score += 45 
        
        return int(score), close.iloc[-1]
    except: return 0, 0

# ======================== 3. منطق التداول v131 ========================

async def main_engine():
    init_db()
    EXCHANGE = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            # فلترة السيولة والارتفاع
            valid_symbols = [s for s, t in tickers.items() if '/USDT' in s and s not in EXCLUDED_COINS and (t.get('quoteVolume', 0) or 0) >= MIN_VOLUME_24H and (t.get('percentage', 0) or 0) <= 5.0]
            
            scored_candidates = []
            for sym in sorted(valid_symbols, key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:60]:
                score, _ = await perform_analysis(sym, EXCHANGE)
                if score >= 85: 
                    scored_candidates.append({'symbol': sym, 'score': score, 'price': tickers[sym]['last']})
                await asyncio.sleep(0.02)

            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)

            # فتح صفقة جديدة
            if scored_candidates:
                best = sorted(scored_candidates, key=lambda x: x['score'], reverse=True)[0]
                cur.execute("SELECT COUNT(*) FROM trades WHERE symbol = %s AND status = 'OPEN'", (best['symbol'],))
                if cur.fetchone()[0] == 0:
                    cur.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
                    if cur.fetchone()[0] < MAX_OPEN_TRADES:
                        cur.execute("INSERT INTO trades (symbol, entry_price, current_price, investment, status, score, open_time) VALUES (%s, %s, %s, %s, 'OPEN', %s,
