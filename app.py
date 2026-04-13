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
# ⚙️ إعدادات الاتصال (بياناتك الشخصية)
# ==========================================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
CHAT_ID = '-1003692815602'

# ==========================================
# 📊 إدارة المخاطر والمحفظة
# ==========================================
MAX_OPEN_POSITIONS = 20
DAILY_CEILING = 6.0        # سقف الربح اليومي %
CAUTION_ZONE = 4.0         # رفع السكور عند ربح 4%
BTC_CRASH_LIMIT = -2.0     # قاطع التيار للبيتكوين
BALANCE_FILE = "balance_data.json"

# تعريف المنصة (Gate.io)
exchange = ccxt.gateio({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

# متغيرات الحالة
open_positions = {}
sector_allocations = {}

# تصنيف القطاعات للدراسة اليومية
SECTORS = {
    'AI': ['FET', 'RNDR', 'NEAR', 'TAO', 'GRT', 'AKT', 'OCEAN'],
    'L1_L2': ['BTC', 'ETH', 'SOL', 'AVAX', 'MATIC', 'OP', 'ARB', 'SUI', 'DOT'],
    'MEME': ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'LADYS'],
    'DEFI': ['UNI', 'AAVE', 'LINK', 'CAKE', 'RUNE', 'PENDLE', 'JOE'],
    'GAMING': ['GALA', 'IMX', 'BEAM', 'AXS', 'SAND', 'MANA', 'NAKA']
}

# ==========================================
# 📂 نظام حفظ واسترجاع الرصيد
# ==========================================
def load_data():
    if os.path.exists(BALANCE_FILE):
        try:
            with open(BALANCE_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {"total_equity": 1000.0, "daily_start": 1000.0, "last_reset": str(datetime.now().date())}

def save_data(equity, daily_start, last_reset):
    with open(BALANCE_FILE, 'w') as f:
        json.dump({
            "total_equity": equity, 
            "daily_start": daily_start, 
            "last_reset": str(last_reset)
        }, f)

# تحميل البيانات
db = load_data()
VIRTUAL_BALANCE = db["total_equity"]
DAILY_START_BALANCE = db["daily_start"]
LAST_RESET_DATE = datetime.strptime(db["last_reset"], '%Y-%m-%d').date()
POSITION_SIZE = VIRTUAL_BALANCE / MAX_OPEN_POSITIONS

# ==========================================
# 📨 التواصل ودراسة السوق
# ==========================================
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={msg}&parse_mode=Markdown"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            print(f"⚠️ Telegram Error: {res.text}")
    except: pass

def update_sector_strength():
    global sector_allocations
    strengths = {}
    print("🔍 جاري تحليل القطاعات...")
    for sector, coins in SECTORS.items():
        changes = []
        for coin in coins[:4]:
            try:
                t = exchange.fetch_ticker(f"{coin}/USDT")
                changes.append(t['percentage'])
            except: continue
        strengths[sector] = sum(changes)/len(changes) if changes else -99

    sorted_sec = sorted(strengths.items(), key=lambda x: x[1], reverse=True)
    alloc_map = [7, 5, 3, 3, 2] # توزيع الـ 20 صفقة
    
    sector_allocations = {sec: (alloc_map[i] if i < len(alloc_map) else 1) for i, (sec, val) in enumerate(sorted_sec)}
    
    report = "📈 *دراسة السوق (قوة القطاعات):*\n" + "\n".join([f"🔹 {k}: {strengths[k]:+.2f}% | حصة: {v} صفقات" for k,v in sector_allocations.items()])
    send_telegram(report)

def get_current_equity():
    return VIRTUAL_BALANCE + (len(open_positions) * POSITION_SIZE)

def reset_daily_params():
    global VIRTUAL_BALANCE, POSITION_SIZE, DAILY_START_BALANCE, LAST_RESET_DATE
    current_equity = get_current_equity()
    DAILY_START_BALANCE = current_equity
    POSITION_SIZE = current_equity / MAX_OPEN_POSITIONS
    LAST_RESET_DATE = datetime.now().date()
    save_data(current_equity, DAILY_START_BALANCE, LAST_RESET_DATE)
    send_telegram(f"♻️ *يوم جديد - إعادة استثمار الأرباح:*\n💰 الرصيد الجديد: {current_equity:.2f}$\n📏 حجم الصفقة: {POSITION_SIZE:.2f}$")

def get_symbol_sector(symbol):
    coin = symbol.split('/')[0]
    for s, coins in SECTORS.items():
        if coin in coins: return s
    return 'OTHERS'

# ==========================================
# 🎯 التحليل الفني والدخول
# ==========================================
def fetch_and_analyze(symbol):
    global VIRTUAL_BALANCE
    if len(open_positions) >= MAX_OPEN_POSITIONS or symbol in open_positions: return

    try:
        current_eq = get_current_equity()
        daily_p = ((current_eq - DAILY_START_BALANCE) / DAILY_START_BALANCE) * 100
        if daily_p >= DAILY_CEILING: return
        
        sec = get_symbol_sector(symbol)
        allowed = sector_allocations.get(sec, 1)
        if sum(1 for s in open_positions if get_symbol_sector(s) == sec) >= allowed: return

        data = {}
        for tf in ['4h', '1h', '15m']:
            bars = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=80)
            df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df.ta.ema(length=9, append=True); df.ta.ema(length=21, append=True)
            df.ta.rsi(length=14, append=True); df.ta.macd(append=True)
            data[tf] = df

        scores = {}
        for tf in ['4h', '1h', '15m']:
            df = data[tf]; last = df.iloc[-1]; s = 0
            if last['EMA_9'] > last['EMA_21']: s += 20
            if last['v'] > (df['v'].tail(15).mean() * 1.3): s += 25
            if 50 < last['RSI_14'] < 70: s += 15
            if last['MACD_12_26_9'] > last['MACDs_12_26_9']: s += 20
            if last['c'] > df['h'].iloc[-11:-1].max(): s += 20
            scores[tf] = s
        
        total_score = (scores['4h']*0.2) + (scores['1h']*0.3) + (scores['15m']*0.5)
        required = 92 if daily_p >= CAUTION_ZONE else 88
        
        if total_score >= required:
            price = data['15m'].iloc[-1]['c']
            VIRTUAL_BALANCE -= POSITION_SIZE
            open_positions[symbol] = {
                'entry': price, 'stop': price * 0.99, 'target': price * 1.025,
                'time': datetime.now(), 'high': price, 'trailing': False, 'sector': sec
            }
            send_telegram(f"🚀 *دخول صفقة*\n🪙 {symbol}\n💰 السعر: {price}\n⭐ سكور: {total_score:.1f}\n📂 قطاع: {sec}")
    except: pass

# ==========================================
# 🛡️ إدارة الخروج والرقابة
# ==========================================
def monitor_and_exit():
    global VIRTUAL_BALANCE
    try:
        btc = exchange.fetch_ticker('BTC/USDT')
        if btc['percentage'] <= BTC_CRASH_LIMIT:
            for s in list(open_positions.keys()):
                close_trade(s, exchange.fetch_ticker(s)['last'], "🚨 طوارئ BTC")
            return
    except: pass

    for s in list(open_positions.keys()):
        try:
            curr = exchange.fetch_ticker(s)['last']
            pos = open_positions[s]
            elapsed = (datetime.now() - pos['time']).total_seconds() / 3600
            
            if curr >= pos['entry'] * 1.01:
                pos['trailing'] = True
                if curr > pos['high']:
                    pos['high'] = curr
                    pos['stop'] = max(pos['stop'], curr * 0.99)

            if curr <= pos['stop']:
                close_trade(s, curr, "🛡️ تتبع" if pos['trailing'] else "❌ وقف خسارة")
            elif elapsed > 6 and not pos['trailing']:
                close_trade(s, curr, "⏳ خروج زمني")
        except: pass

def close_trade(symbol, price, reason):
    global VIRTUAL_BALANCE
    pos = open_positions[symbol]
    profit = ((price - pos['entry']) / pos['entry']) * 100
    VIRTUAL_BALANCE += POSITION_SIZE * (1 + (profit/100))
    save_data(get_current_equity(), DAILY_START_BALANCE, LAST_RESET_DATE)
    send_telegram(f"🚪 *إغلاق صفقة*\n🪙 {symbol}\n📈 الربح: {profit:.2f}%\n📝 السبب: {reason}")
    del open_positions[symbol]

# ==========================================
# 🔄 حلقة العمل الرئيسية
# ==========================================
last_sector_update = 0
last_hourly_report = datetime.now().hour

send_telegram("🦾 *Apex Sentinel* مفعل الآن ببياناتك على Gate.io")

while True:
    try:
        now = datetime.now()
        
        if now.date() > LAST_RESET_DATE:
            reset_daily_params()

        if time.time() - last_sector_update > 4 * 3600:
            update_sector_strength()
            last_sector_update = time.time()

        if now.hour != last_hourly_report:
            eq = get_current_equity()
            daily_p = ((eq - DAILY_START_BALANCE) / DAILY_START_BALANCE) * 100
            send_telegram(f"📊 *ملخص الساعة*\n💰 رصيد إجمالي: {eq:.2f}$\n📈 نمو اليوم: {daily_p:.2f}%")
            last_hourly_report = now.hour

        monitor_and_exit()
        
        if ((get_current_equity() - DAILY_START_BALANCE) / DAILY_START_BALANCE) * 100 < DAILY_CEILING:
            tickers = exchange.fetch_tickers()
            sorted_t = sorted(tickers.items(), key=lambda x: x[1]['quoteVolume'] if x[1]['quoteVolume'] else 0, reverse=True)
            all_s = [s for s, t in sorted_t if '/USDT' in s and t['quoteVolume'] > 100000][:800]
            
            with ThreadPoolExecutor(max_workers=15) as exe:
                exe.map(fetch_and_analyze, all_s)
        
        time.sleep(60)
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(30)
