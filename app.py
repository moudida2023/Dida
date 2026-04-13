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
# 🔑 إعدادات الاتصال (بياناتك الخاصة)
# ==========================================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# ==========================================
# ⚙️ إعدادات المحفظة وإدارة المخاطر
# ==========================================
TOTAL_POSITIONS = 20
DAILY_TARGET_PCT = 6.0     
BALANCE_FILE = "trading_state.json"

# تعريف منصة Gate.io
exchange = ccxt.gateio({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

# تصنيف القطاعات للدراسة اليومية
SECTORS = {
    'AI': ['FET', 'RNDR', 'NEAR', 'TAO', 'GRT', 'AKT'],
    'L1_L2': ['BTC', 'ETH', 'SOL', 'AVAX', 'MATIC', 'OP', 'ARB', 'SUI'],
    'MEME': ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF'],
    'DEFI': ['UNI', 'AAVE', 'LINK', 'CAKE', 'RUNE', 'PENDLE']
}

# ==========================================
# 📈 المعادلات الفنية اليدوية (بديل pandas-ta)
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
# 📂 إدارة الحالة (الحفظ التلقائي)
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
    except: pass

# ==========================================
# 📊 دراسة السوق والتدوير القطاعي
# ==========================================
def analyze_sectors():
    global sector_allocs
    scores = {}
    print("🔍 Analyzing sector performance...")
    for sec, coins in SECTORS.items():
        changes = []
        for c in coins[:3]:
            try: changes.append(exchange.fetch_ticker(f"{c}/USDT")['percentage'])
            except: continue
        scores[sec] = sum(changes)/len(changes) if changes else -99
    
    sorted_sec = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    mapping = [7, 5, 4, 2, 2] 
    sector_allocs = {s: (mapping[i] if i < len(mapping) else 1) for i, (s, v) in enumerate(sorted_sec)}
    send_msg(f"📊 *Sector Analysis:* {list(sector_allocs.keys())[0]} is leading the market.")

# ==========================================
# 🎯 محرك التحليل والتداول
# ==========================================
def process_symbol(symbol):
    global VIRTUAL_CASH
    if symbol in open_positions or len(open_positions) >= TOTAL_POSITIONS: return
    
    current_eq = VIRTUAL_CASH + (len(open_positions) * POS_SIZE)
    if ((current_eq - DAY_START_VAL) / DAY_START_VAL) * 100 >= DAILY_TARGET_PCT: return

    try:
        coin = symbol.split('/')[0]
        sec = next((s for s, coins in SECTORS.items() if coin in coins), 'OTHERS')
        if sum(1 for p in open_positions.values() if p['sec'] == sec) >= sector_allocs.get(sec, 1): return

        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        
        df['ema9'] = calculate_ema(df['c'], 9)
        df['ema21'] = calculate_ema(df['c'], 21)
        df['rsi'] = calculate_rsi(df['c'], 14)
        df['macd'], df['signal'] = calculate_macd(df['c'])
        
        last = df.iloc[-1]
        score = 0
        if last['ema9'] > last['ema21']: score += 20
        if last['v'] > (df['v'].tail(15).mean() * 1.5): score += 30
        if 50 < last['rsi'] < 70: score += 20
        if last['macd'] > last['signal']: score += 30
        
        if score >= 88:
            price = last['c']
            VIRTUAL_CASH -= POS_SIZE
            open_positions[symbol] = {
                'entry': price, 'stop': price*0.99, 'high': price, 
                'trailing': False, 'sec': sec, 'time': time.time()
            }
            send_msg(f"🚀 *BUY {symbol}*\n⭐ Score: {score}\n📂 Sector: {sec}")
    except: pass

def monitor_market():
    global VIRTUAL_CASH
    for s in list(open_positions.keys()):
        try:
            curr = exchange.fetch_ticker(s)['last']
            pos = open_positions[s]
            
            if curr >= pos['entry'] * 1.01:
                pos['trailing'] = True
                if curr > pos['high']:
                    pos['high'] = curr
                    pos['stop'] = max(pos['stop'], curr * 0.99)
            
            if curr <= pos['stop'] or (time.time() - pos['time'] > 21600 and not pos['trailing']):
                pnl = ((curr - pos['entry'])/pos['entry'])*100
                VIRTUAL_CASH += POS_SIZE * (1 + (pnl/100))
                with open(BALANCE_FILE, 'w') as f:
                    json.dump({"equity": VIRTUAL_CASH, "day_start": DAY_START_VAL, "date": str(LAST_DATE)}, f)
                send_msg(f"🚪 *CLOSE {s}*\n📈 PNL: {pnl:.2f}%\n💵 Balance: {VIRTUAL_CASH + (len(open_positions)*POS_SIZE):.2f}$")
                del open_positions[s]
        except: pass

# ==========================================
# 🔄 الحلقة الرئيسية
# ==========================================
if __name__ == "__main__":
    send_msg("🤖 *Apex Sentinel* is live and monitoring Gate.io.")
    analyze_sectors()
    while True:
        try:
            now = datetime.now()
            if now.date() > LAST_DATE:
                total = VIRTUAL_CASH + (len(open_positions) * POS_SIZE)
                VIRTUAL_CASH, DAY_START_VAL = total, total
                POS_SIZE = total / TOTAL_POSITIONS
                LAST_DATE = now.date()
                analyze_sectors()
                send_msg(f"♻️ *Daily Reset:* Equity {total:.2f}$ | Pos Size {POS_SIZE:.2f}$")

            monitor_market()
            
            tkrs = exchange.fetch_tickers()
            sorted_tkrs = sorted(tkrs.items(), key=lambda x: x[1]['quoteVolume'] or 0, reverse=True)
            symbols = [s for s, t in sorted_tkrs if '/USDT' in s and (t['quoteVolume'] or 0) > 100000][:800]
            
            with ThreadPoolExecutor(max_workers=15) as exe: exe.map(process_symbol, symbols)
            time.sleep(60)
        except Exception as e:
            time.sleep(30)
