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
# 🔑 الإعدادات الخاصة بك
# ==========================================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# ==========================================
# ⚙️ إعدادات الإدارة والمخاطر
# ==========================================
TOTAL_POSITIONS = 20
DAILY_TARGET_PCT = 6.0
BALANCE_FILE = "trading_state.json"
HISTORY_FILE = "trade_history.json"
exchange = ccxt.gateio({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

# قوائم القطاعات (عملات أساسية وقوية)
SECTORS = {
    'AI': ['FET', 'RNDR', 'NEAR', 'TAO', 'GRT', 'AKT'],
    'L1_L2': ['BTC', 'ETH', 'SOL', 'AVAX', 'MATIC', 'OP', 'ARB', 'SUI'],
    'MEME': ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF'],
    'DEFI': ['UNI', 'AAVE', 'LINK', 'CAKE', 'RUNE', 'PENDLE']
}

open_positions = {}
trade_history = []
sector_allocs = {}
last_update_id = 0

# --- المعادلات الفنية ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calculate_macd(series, slow=26, fast=12, signal=9):
    fast_ema = calculate_ema(series, fast)
    slow_ema = calculate_ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line

# --- إدارة الحالة ---
def load_state():
    global trade_history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: trade_history = json.load(f)
        except: trade_history = []
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

def send_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={TELEGRAM_CHAT_ID}&text={text}&parse_mode=Markdown"
    try: requests.get(url, timeout=5)
    except: pass

def save_current_state():
    with open(BALANCE_FILE, 'w') as f:
        json.dump({"equity": VIRTUAL_CASH, "day_start": DAY_START_VAL, "date": str(LAST_DATE)}, f)
    with open(HISTORY_FILE, 'w') as f:
        json.dump(trade_history[-20:], f)

# ==========================================
# 🎯 محرك التداول (مع فلتر الحماية)
# ==========================================
def process_symbol(symbol):
    global VIRTUAL_CASH
    if symbol in open_positions or len(open_positions) >= TOTAL_POSITIONS:
        return

    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        
        # حساب المؤشرات
        df['ema9'], df['ema21'] = calculate_ema(df['c'], 9), calculate_ema(df['c'], 21)
        df['rsi'], (df['m'], df['sig']) = calculate_rsi(df['c']), calculate_macd(df['c'])
        
        last = df.iloc[-1]
        score = (20 if last['ema9'] > last['ema21'] else 0) + \
                (30 if last['v'] > (df['v'].tail(15).mean() * 1.5) else 0) + \
                (20 if 50 < last['rsi'] < 70 else 0) + \
                (30 if last['m'] > last['sig'] else 0)
        
        if score >= 88:
            coin = symbol.split('/')[0]
            sec = next((s for s, cs in SECTORS.items() if coin in cs), 'OTHERS')
            if sum(1 for p in open_positions.values() if p['sec'] == sec) >= sector_allocs.get(sec, 1):
                return

            VIRTUAL_CASH -= POS_SIZE
            open_positions[symbol] = {
                'entry': last['c'], 'stop': last['c']*0.99, 'high': last['c'], 
                'trailing': False, 'sec': sec, 'time': time.time()
            }
            send_msg(f"🚀 *Buy {symbol}* (Score: {score})")
    except: pass

def monitor():
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
                close_logic(s, curr, "Exit Strategy")
        except: pass

def close_logic(symbol, price, reason):
    global VIRTUAL_CASH, trade_history
    pos = open_positions[symbol]
    pnl = ((price - pos['entry']) / pos['entry']) * 100
    VIRTUAL_CASH += POS_SIZE * (1 + (pnl/100))
    trade_history.append({"symbol": symbol, "pnl": round(pnl, 2), "reason": reason})
    save_current_state()
    send_msg(f"🚪 *Closed {symbol}* ({pnl:+.2f}%)")
    del open_positions[symbol]

def handle_telegram_commands():
    global last_update_id
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}"
    try:
        resp = requests.get(url, timeout=5).json()
        if not resp.get("result"): return
        for update in resp["result"]:
            last_update_id = update["update_id"]
            msg = update.get("message", {})
            text = msg.get("text", "")
            if str(msg.get("chat", {}).get("id", "")) != TELEGRAM_CHAT_ID: continue

            if text == "/liste_o":
                if not open_positions: send_msg("📭 لا توجد صفقات.")
                else:
                    lines = [f"🔹 `{s}`: {((exchange.fetch_ticker(s)['last']-p['entry'])/p['entry'])*100:+.2f}%" for s, p in open_positions.items()]
                    send_msg("📋 *المفتوحة:*\n" + "\n".join(lines))
            elif text == "/report":
                send_msg(f"💰 الرصيد التقديري: {VIRTUAL_CASH + (len(open_positions)*POS_SIZE):.2f}$")
    except: pass

# ==========================================
# 🔄 الحلقة الرئيسية (المسح المنظم)
# ==========================================
if __name__ == "__main__":
    send_msg("🤖 *Apex Sentinel* Live (Protection Filter Active)")
    while True:
        try:
            # 1. تحديث البيانات اليومية
            now = datetime.now()
            if now.date() > LAST_DATE:
                VIRTUAL_CASH += (len(open_positions) * POS_SIZE)
                DAY_START_VAL, LAST_DATE = VIRTUAL_CASH, now.date()
                POS_SIZE = VIRTUAL_CASH / TOTAL_POSITIONS
                save_current_state()

            # 2. أوامر تلغرام والمراقبة
            handle_telegram_commands()
            monitor()
            
            # 3. مسح السوق مع فلتر العملات الرافعة (3L, 3S, 5L, 5S)
            all_tkrs = exchange.fetch_tickers()
            symbols = [
                s for s, t in sorted(all_tkrs.items(), key=lambda x: x[1]['quoteVolume'] or 0, reverse=True) 
                if '/USDT' in s 
                and not any(bad in s for bad in ['3L', '3S', '5L', '5S', 'BEAR', 'BULL']) # الفلتر القوي
            ][:800]
            
            # توزيع الصفقات بناءً على أداء السوق اللحظي
            with ThreadPoolExecutor(max_workers=15) as exe:
                exe.map(process_symbol, symbols)
            
            time.sleep(30)
        except: time.sleep(10)
