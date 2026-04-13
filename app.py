import ccxt
import pandas as pd
import pandas_ta as ta
import time
import requests
import json
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# ⚙️ إعدادات الاتصال (مفعلة ببياناتك)
# ==========================================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
CHAT_ID = '5067771509'

# ==========================================
# 📊 إدارة المخاطر والمحفظة
# ==========================================
MAX_OPEN_POSITIONS = 20
DAILY_CEILING = 6.0        
CAUTION_ZONE = 4.0         
BTC_CRASH_LIMIT = -2.0     
BALANCE_FILE = "balance_data.json"

exchange = ccxt.gateio({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

open_positions = {}
sector_allocations = {}

SECTORS = {
    'AI': ['FET', 'RNDR', 'NEAR', 'TAO', 'GRT', 'AKT', 'OCEAN'],
    'L1_L2': ['BTC', 'ETH', 'SOL', 'AVAX', 'MATIC', 'OP', 'ARB', 'SUI', 'DOT'],
    'MEME': ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'LADYS'],
    'DEFI': ['UNI', 'AAVE', 'LINK', 'CAKE', 'RUNE', 'PENDLE', 'JOE'],
    'GAMING': ['GALA', 'IMX', 'BEAM', 'AXS', 'SAND', 'MANA', 'NAKA']
}

# ==========================================
# 📂 وظائف النظام
# ==========================================
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            print(f"⚠️ Telegram Error: {res.text}")
    except Exception as e:
        print(f"⚠️ Connection Error: {e}")

def load_data():
    if os.path.exists(BALANCE_FILE):
        try:
            with open(BALANCE_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {"total_equity": 1000.0, "daily_start": 1000.0, "last_reset": str(datetime.now().date())}

def save_data(equity, daily_start, last_reset):
    with open(BALANCE_FILE, 'w') as f:
        json.dump({"total_equity": equity, "daily_start": daily_start, "last_reset": str(last_reset)}, f)

db = load_data()
VIRTUAL_BALANCE = db["total_equity"]
DAILY_START_BALANCE = db["daily_start"]
LAST_RESET_DATE = datetime.strptime(db["last_reset"], '%Y-%m-%d').date()
POSITION_SIZE = VIRTUAL_BALANCE / MAX_OPEN_POSITIONS

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
    report = "📈 *تحليل القطاعات:*\n" + "\n".join([f"🔹 {k}: {strengths[k]:+.2f}% | حصة: {v}" for k,v in sector_allocations.items()])
    send_telegram(report)

def get_current_equity():
    return VIRTUAL_BALANCE + (len(open_positions) * POSITION_SIZE)

def fetch_and_analyze(symbol):
    global VIRTUAL_BALANCE
    if len(open_positions) >= MAX_OPEN_POSITIONS or symbol in open_positions: return
    try:
        current_eq = get_current_equity()
        daily_p = ((current_eq - DAILY_START_BALANCE) / DAILY_START_BALANCE) * 100
        if daily_p >= DAILY_CEILING: return
        
        coin = symbol.split('/')[0]
        sec = 'OTHERS'
        for s, coins in SECTORS.items():
            if coin in coins: sec = s; break
        
        allowed = sector_allocations.get(sec, 1)
        if sum(1 for s in open_positions if s.startswith(coin)) >= allowed: return

        bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
        df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
        df.ta.rsi(length=14, append=True)
        
        last = df.iloc[-1]
        # شروط مبسطة وسريعة للدخول التجريبي
        if 50 < last['RSI_14'] < 70 and last['c'] > df['c'].iloc[-2]:
            VIRTUAL_BALANCE -= POSITION_SIZE
            open_positions[symbol] = {'entry': last['c'], 'stop': last['c']*0.99, 'time': datetime.now()}
            send_telegram(f"🚀 *دخول:* {symbol} بسعر {last['c']}")
    except: pass

# ==========================================
# 🔄 الحلقة الرئيسية
# ==========================================
last_sector_update = 0
last_hourly_report = datetime.now().hour

# رسالة ترحيبية فورية عند التشغيل
send_telegram("🦾 *Apex Sentinel* بدأ العمل بنجاح على Railway!\nجاري فحص السوق...")

while True:
    try:
        now = datetime.now()
        
        # دراسة القطاعات
        if time.time() - last_sector_update > 4 * 3600:
            update_sector_strength()
            last_sector_update = time.time()

        # مسح السوق
        tickers = exchange.fetch_tickers()
        all_s = [s for s, t in tickers.items() if '/USDT' in s and (t['quoteVolume'] or 0) > 100000][:800]
        
        with ThreadPoolExecutor(max_workers=10) as exe:
            exe.map(fetch_and_analyze, all_s)
        
        time.sleep(60)
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(30)
