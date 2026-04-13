import ccxt
import pandas as pd
import time
import requests
import json
import os
import numpy as np
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- إعدادات الاتصال ---
TELEGRAM_TOKEN = "YOUR_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"

# --- إعدادات الإدارة ---
MAX_OPEN_POSITIONS = 20
DAILY_CEILING = 6.0        
CAUTION_ZONE = 4.0         
BTC_CRASH_LIMIT = -2.0     
BALANCE_FILE = "trading_state.json"

exchange = ccxt.gateio({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

# --- متغيرات الحالة ---
open_positions = {}
sector_allocations = {}
closed_today = []

SECTORS = {
    'AI': ['FET', 'RNDR', 'NEAR', 'TAO', 'GRT', 'AKT', 'OCEAN', 'PHB'],
    'L1_L2': ['BTC', 'ETH', 'SOL', 'AVAX', 'MATIC', 'OP', 'ARB', 'SUI', 'DOT'],
    'MEME': ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'LADYS'],
    'DEFI': ['UNI', 'AAVE', 'LINK', 'CAKE', 'RUNE', 'PENDLE', 'JOE'],
    'GAMING': ['GALA', 'IMX', 'BEAM', 'AXS', 'SAND', 'MANA', 'NAKA']
}

# --- وظائف المؤشرات الفنية (بديلة لـ pandas_ta) ---
def calculate_ema(df, period):
    return df['c'].ewm(span=period, adjust=False).mean()

def calculate_rsi(df, period=14):
    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_macd(df):
    ema12 = calculate_ema(df, 12)
    ema26 = calculate_ema(df, 26)
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal

# --- إدارة الرصيد والبيانات ---
def load_state():
    if os.path.exists(BALANCE_FILE):
        try:
            with open(BALANCE_FILE, 'r') as f: return json.load(f)
        except: pass
    return {"total_equity": 1000.0, "daily_start": 1000.0, "last_reset": str(datetime.now().date())}

def save_state():
    current_equity = get_current_equity()
    state = {"total_equity": current_equity, "daily_start": DAILY_START_BALANCE, "last_reset": str(LAST_RESET_DATE)}
    with open(BALANCE_FILE, 'w') as f: json.dump(state, f)

state_data = load_state()
VIRTUAL_BALANCE = state_data["total_equity"]
DAILY_START_BALANCE = state_data["daily_start"]
LAST_RESET_DATE = datetime.strptime(state_data["last_reset"], '%Y-%m-%d').date()
POSITION_SIZE = VIRTUAL_BALANCE / MAX_OPEN_POSITIONS

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={msg}&parse_mode=Markdown"
    try: requests.get(url, timeout=10)
    except: pass

def get_current_equity():
    return VIRTUAL_BALANCE + (len(open_positions) * POSITION_SIZE)

def update_sector_strength():
    global sector_allocations
    strengths = {}
    for sector, coins in SECTORS.items():
        changes = []
        for coin in coins[:4]:
            try:
                t = exchange.fetch_ticker(f"{coin}/USDT")
                changes.append(t['percentage'])
            except: continue
        strengths[sector] = sum(changes)/len(changes) if changes else -99
    sorted_sec = sorted(strengths.items(), key=lambda x: x[1], reverse=True)
    alloc_map = [7, 5, 3, 3, 2]
    sector_allocations = {sec: (alloc_map[i] if i < len(alloc_map) else 1) for i, (sec, val) in enumerate(sorted_sec)}
    send_telegram("📊 *تحديث القطاعات:* " + " | ".join([f"{k}:{v}" for k,v in sector_allocations.items()]))

def reset_daily_params():
    global VIRTUAL_BALANCE, POSITION_SIZE, DAILY_START_BALANCE, LAST_RESET_DATE, closed_today
    current_equity = get_current_equity()
    DAILY_START_BALANCE = current_equity
    POSITION_SIZE = current_equity / MAX_OPEN_POSITIONS
    LAST_RESET_DATE = datetime.now().date()
    closed_today = []
    save_state()
    send_telegram(f"🔄 *يوم جديد:* الحجم {POSITION_SIZE:.2f}$ | الرصيد {current_equity:.2f}$")

# --- محرك التحليل ---
def fetch_and_analyze(symbol):
    global VIRTUAL_BALANCE
    if symbol in open_positions or symbol in closed_today or len(open_positions) >= MAX_OPEN_POSITIONS: return

    try:
        current_eq = get_current_equity()
        daily_profit = ((current_eq - DAILY_START_BALANCE) / DAILY_START_BALANCE) * 100
        if daily_profit >= DAILY_CEILING: return
        
        sec = "OTHERS"
        coin = symbol.split('/')[0]
        for s, coins in SECTORS.items():
            if coin in coins: sec = s; break
        
        if sum(1 for s in open_positions if open_positions[s]['sector'] == sec) >= sector_allocations.get(sec, 1): return

        # جلب وتحليل البيانات
        data = {}
        for tf in ['4h', '1h', '15m']:
            bars = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=80)
            df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df['ema9'] = calculate_ema(df, 9)
            df['ema21'] = calculate_ema(df, 21)
            df['rsi'] = calculate_rsi(df, 14)
            df['macd'], df['signal'] = calculate_macd(df)
            data[tf] = df

        scores = {}
        for tf in ['4h', '1h', '15m']:
            df = data[tf]; last = df.iloc[-1]; s = 0
            if last['ema9'] > last['ema21']: s += 20
            if last['v'] > (df['v'].tail(15).mean() * 1.3): s += 25
            if 50 < last['rsi'] < 70: s += 15
            if last['macd'] > last['signal']: s += 20
            if last['c'] > df['h'].iloc[-11:-1].max(): s += 20
            scores[tf] = s
        
        total_score = (scores['4h']*0.2) + (scores['1h']*0.3) + (scores['15m']*0.5)
        required = 92 if daily_profit >= CAUTION_ZONE else 88
        
        if total_score >= required:
            price = data['15m'].iloc[-1]['c']
            VIRTUAL_BALANCE -= POSITION_SIZE
            open_positions[symbol] = {'entry': price, 'stop': price * 0.99, 'high': price, 'time': datetime.now(), 'trailing': False, 'sector': sec}
            send_telegram(f"🚀 *دخول:* {symbol} | السعر: {price} | سكور: {total_score:.1f}")
    except: pass

# --- إدارة الخروج ---
def monitor_market():
    global VIRTUAL_BALANCE, closed_today
    try:
        btc = exchange.fetch_ticker('BTC/USDT')
        if btc['percentage'] <= BTC_CRASH_LIMIT:
            for s in list(open_positions.keys()): close_trade(s, exchange.fetch_ticker(s)['last'], "🚨 طوارئ")
            return
    except: pass

    for s in list(open_positions.keys()):
        try:
            curr = exchange.fetch_ticker(s)['last']
            pos = open_positions[s]
            if curr >= pos['entry'] * 1.01:
                pos['trailing'] = True
                if curr > pos['high']:
                    pos['high'] = curr
                    pos['stop'] = max(pos['stop'], curr * 0.99)
            if curr <= pos['stop']: close_trade(s, curr, "🛡️ تتبع" if pos['trailing'] else "❌ وقف")
            elif (datetime.now() - pos['time']).total_seconds() / 3600 > 6 and not pos['trailing']:
                close_trade(s, curr, "⏳ زمن")
        except: pass

def close_trade(symbol, price, reason):
    global VIRTUAL_BALANCE, closed_today
    pos = open_positions[symbol]
    profit_pct = ((price - pos['entry']) / pos['entry']) * 100
    VIRTUAL_BALANCE += POSITION_SIZE * (1 + (profit_pct/100))
    closed_today.append(symbol)
    save_state()
    send_telegram(f"🚪 *إغلاق:* {symbol} | {reason} | ربح: {profit_pct:.2f}% | رصيد: {get_current_equity():.2f}$")
    del open_positions[symbol]

# --- الحلقة الرئيسية ---
last_sector_update = 0
last_hourly_report = datetime.now().hour
send_telegram("🤖 *Apex Sentinel (No-PandasTA)* يعمل الآن...")

while True:
    try:
        now = datetime.now()
        if now.date() > LAST_RESET_DATE: reset_daily_params()
        if time.time() - last_sector_update > 4 * 3600:
            update_sector_strength()
            last_sector_update = time.time()
        if now.hour != last_hourly_report:
            eq = get_current_equity()
            send_telegram(f"📊 *تقرير:* {eq:.2f}$ | يومي: {((eq-DAILY_START_BALANCE)/DAILY_START_BALANCE)*100:.2f}%")
            last_hourly_report = now.hour
        monitor_market()
        if ((get_current_equity() - DAILY_START_BALANCE) / DAILY_START_BALANCE) * 100 < DAILY_CEILING:
            tickers = exchange.fetch_tickers()
            sorted_t = sorted(tickers.items(), key=lambda x: x[1]['quoteVolume
