import ccxt
import pandas as pd
import time
import requests
import json
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# ⚙️ الإعدادات (بياناتك)
# ==========================================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
CHAT_ID = '5067771509'
MAX_OPEN_POSITIONS = 20
DAILY_CEILING = 6.0
BALANCE_FILE = "balance_data.json"

exchange = ccxt.gateio({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
open_positions = {}

# دالة حساب RSI يدوياً لتجنب pandas_ta
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def load_data():
    if os.path.exists(BALANCE_FILE):
        try:
            with open(BALANCE_FILE, 'r') as f: return json.load(f)
        except: pass
    return {"total_equity": 1000.0, "daily_start": 1000.0, "last_reset": str(datetime.now().date())}

db = load_data()
VIRTUAL_BALANCE = db["total_equity"]
DAILY_START_BALANCE = db["daily_start"]
POSITION_SIZE = VIRTUAL_BALANCE / MAX_OPEN_POSITIONS

def fetch_and_analyze(symbol):
    global VIRTUAL_BALANCE
    if len(open_positions) >= MAX_OPEN_POSITIONS or symbol in open_positions: return
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
        df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
        
        # حساب RSI بدون مكتبات خارجية
        df['rsi'] = calculate_rsi(df['c'])
        last_rsi = df['rsi'].iloc[-1]
        last_price = df['c'].iloc[-1]

        # شرط دخول بسيط: RSI بين 50 و 70 (اتجاه صاعد)
        if 50 < last_rsi < 70:
            VIRTUAL_BALANCE -= POSITION_SIZE
            open_positions[symbol] = {'entry': last_price, 'stop': last_price*0.99, 'time': datetime.now()}
            send_telegram(f"🚀 *دخول صفقة:*\n🪙 {symbol}\n💰 السعر: {last_price}\n📉 RSI: {last_rsi:.2f}")
    except: pass

# --- الحلقة الرئيسية ---
send_telegram("🦾 *Apex Sentinel (Lite)* بدأ العمل الآن!\nتم حذف pandas_ta لتسريع التشغيل.")

while True:
    try:
        # مسح السوق (أول 100 عملة سيولة لتجنب ضغط الذاكرة)
        tickers = exchange.fetch_tickers()
        sorted_t = sorted(tickers.items(), key=lambda x: x[1]['quoteVolume'] if x[1]['quoteVolume'] else 0, reverse=True)
        all_s = [s for s, t in sorted_t if '/USDT' in s][:100]
        
        with ThreadPoolExecutor(max_workers=5) as exe:
            exe.map(fetch_and_analyze, all_s)
            
        time.sleep(60)
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(30)
