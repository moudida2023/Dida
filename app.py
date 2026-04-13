import ccxt
import pandas as pd
import numpy as np
import time
import requests
import json
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 🔑 إعدادات الاتصال (تم التحديث ببياناتك)
# ==========================================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# ==========================================
# ⚙️ إعدادات المحفظة وإدارة المخاطر
# ==========================================
TOTAL_POSITIONS = 20
DAILY_TARGET = 6.0         # الهدف اليومي 6%
BALANCE_FILE = "trading_state.json"

# تعريف المنصة (Gate.io)
exchange = ccxt.gateio({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

# تصنيف القطاعات للدراسة اليومية
SECTORS = {
    'AI': ['FET', 'RNDR', 'NEAR', 'TAO', 'GRT', 'AKT'],
    'L1_L2': ['BTC', 'ETH', 'SOL', 'AVAX', 'MATIC', 'OP', 'ARB', 'SUI'],
    'MEME': ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF'],
    'DEFI': ['UNI', 'AAVE', 'LINK', 'CAKE', 'RUNE', 'PENDLE']
}

# ==========================================
# 📈 المعادلات الفنية (RSI, EMA, MACD)
# ==========================================
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_macd(series, slow=26, fast=12, signal=9):
    fast_ema = calculate_ema(series, fast)
    slow_ema = calculate_ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line

# ==========================================
# 📂 إدارة الحالة والرصيد التراكمي
# ==========================================
def load_state():
    if os.path.exists(BALANCE_FILE):
        try:
            with open(BALANCE_FILE, 'r') as f: return json.load(f)
        except: pass
    return {"equity": 1000.0, "day_start": 1000.0, "date": str(datetime.now().date())}

state = load_state()
VIRTUAL_CASH = state["equity"]
DAY_START_VAL = state["day_start"]
LAST_DATE = datetime.strptime(state["date"], '%Y-%m-%d').date()
POS_SIZE = VIRTUAL_CASH / TOTAL_POSITIONS
open_positions = {}
sector_allocs = {}

def send_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={TELEGRAM_CHAT_ID}&text={text}&parse_mode=Markdown"
    try: requests.get(url, timeout=5)
    except: print(f"Telegram Error: {text}")

# ==========================================
# 📊 دراسة السوق والتدوير القطاعي
# ==========================================
def analyze_sectors():
    global sector_allocs
    scores = {}
    print("🔍 دراسة أداء القطاعات...")
    for sec, coins in SECTORS.items():
        changes = []
        for c in coins[:3]:
            try: changes.append(exchange.fetch_ticker(f"{c}/USDT")['percentage'])
            except: continue
        scores[sec] = sum(changes)/len(changes) if changes else -99
    
    sorted_sec = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    mapping = [7, 5, 4, 2, 2] 
    sector_allocs = {s: (mapping[i] if i < len(mapping) else 1) for i, (s, v) in enumerate(sorted_sec)}
