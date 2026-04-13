import ccxt
import pandas as pd
import pandas_ta as ta
import time
import requests
import json
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- إعدادات الاتصال والهوية ---
TELEGRAM_TOKEN = "YOUR_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"

# --- إعدادات الإدارة الصارمة ---
MAX_OPEN_POSITIONS = 20
DAILY_CEILING = 6.0        # سقف الربح اليومي 6%
CAUTION_ZONE = 4.0         # منطقة رفع السكور (الجودة العالية)
BTC_CRASH_LIMIT = -2.0     # قاطع التيار للبيتكوين
BALANCE_FILE = "trading_state.json"

# --- تعريف المنصة (Gate.io) ---
exchange = ccxt.gateio({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

# --- متغيرات الحالة ---
open_positions = {}
sector_allocations = {}
closed_today = []  # قائمة العملات الممنوعة من التكرار اليوم

SECTORS = {
    'AI': ['FET', 'RNDR', 'NEAR', 'TAO', 'GRT', 'AKT', 'OCEAN', 'PHB'],
    'L1_L2': ['BTC', 'ETH', 'SOL', 'AVAX', 'MATIC', 'OP', 'ARB', 'SUI', 'DOT'],
    'MEME': ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'LADYS'],
    'DEFI': ['UNI', 'AAVE', 'LINK', 'CAKE', 'RUNE', 'PENDLE', 'JOE'],
    'GAMING': ['GALA', 'IMX', 'BEAM', 'AXS', 'SAND', 'MANA', 'NAKA']
}

# --- نظام حفظ وإدارة الرصيد ---
def load_state():
    if os.path.exists(BALANCE_FILE):
        try:
            with open(BALANCE_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {"total_equity": 1000.0, "daily_start": 1000.0, "last_reset": str(datetime.now().date())}

def save_state():
    current_equity = get_current_equity()
    state = {
        "total_equity": current_equity,
        "daily_start": DAILY_START_BALANCE,
        "last_reset": str(LAST_RESET_DATE)
    }
    with open(BALANCE_FILE, 'w') as f:
        json.dump(state, f)

# تهيئة البيانات
state_data = load_state()
VIRTUAL_BALANCE = state_data["total_equity"]
DAILY_START_BALANCE = state_data["daily_start"]
LAST_RESET_DATE = datetime.strptime(state_data["last_reset"], '%Y-%m-%d').date()
POSITION_SIZE = VIRTUAL_BALANCE / MAX_OPEN_POSITIONS

# --- وظائف المساعدة والتحليل ---
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={msg}&parse_mode=Markdown"
    try: requests.get(url, timeout=10)
    except: pass

def get_sector(symbol):
    coin = symbol.split('/')[0]
    for s, coins in SECTORS.items():
        if coin in coins: return s
    return 'OTHERS'

def get_current_equity():
    return VIRTUAL_BALANCE + (len(open_positions) * POSITION_SIZE)

def update_sector_strength():
    """تحليل أقوى القطاعات لتوزيع الـ 20 صفقة عليها"""
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
    alloc_map = [7, 5, 3, 3, 2] # توزيع الحصص من الـ 20 صفقة
    
    sector_allocations = {sec: (alloc_map[i] if i < len(alloc_map) else 1) for i, (sec, val) in enumerate(sorted_sec)}
    
    report = "📊 *التوزيع القطاعي الجديد:*\n" + "\n".join([f"🔸 {k}: {v} صفقات" for k,v in sector_allocations.items()])
    send_telegram(report)

def reset_daily_params():
    """إعادة استثمار الأرباح وتصفير قائمة الممنوعات كل صباح"""
    global VIRTUAL_BALANCE, POSITION_SIZE, DAILY_START_BALANCE, LAST_RESET_DATE, closed_today
    current_equity = get_current_equity()
    DAILY_START_BALANCE = current_equity
    POSITION_SIZE = current_equity / MAX_OPEN_POSITIONS
    LAST_RESET_DATE = datetime.now().date()
    closed_today = [] # تصفير قائمة العملات المتداولة لبدء يوم جديد
    save_state()
    send_telegram(f"🔄 *بداية يوم جديد*\n💰 الرصيد: {current_equity:.2f}$\n📏 حجم الصفقة الجديد: {POSITION_SIZE:.2f}$")

# --- محرك البحث والتحليل ---
def fetch_and_analyze(symbol):
    global VIRTUAL_BALANCE
    # منع التكرار: لا تدخل إذا كانت مفتوحة أو تم تداولها اليوم
    if symbol in open_positions or symbol in closed_today: return
    if len(open_positions) >= MAX_OPEN_POSITIONS: return

    try:
        current_eq = get_current_equity()
        daily_profit = ((current_eq - DAILY_START_BALANCE) / DAILY_START_BALANCE) * 100
        if daily_profit >= DAILY_CEILING: return
        
        sec = get_sector(symbol)
        allowed = sector_allocations.get(sec, 1)
        if sum(1 for s in open_positions if get_sector(s) == sec) >= allowed: return

        # جلب الشموع والتحليل
        data = {}
        for tf in ['4h', '1h', '15m']:
            bars = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=70)
            df = pd.DataFrame(bars, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df.ta.ema(length=9, append=True); df.ta.ema(length=21, append=True)
            df.ta.rsi(length=14, append=True); df.ta.macd(append=True)
            data[tf] = df

        # حساب سكور الجودة
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
        required = 92 if daily_profit >= CAUTION_ZONE else 88
        
        if total_score >= required:
            price = data['15m'].iloc[-1]['c']
            VIRTUAL_BALANCE -= POSITION_SIZE
            open_positions[symbol] = {
                'entry': price, 'stop': price * 0.99, 'high': price, 
                'time': datetime.now(), 'trailing': False, 'sector': sec
            }
            send_telegram(f"🚀 *دخول صفقة*\n🪙 {symbol}\n💰 السعر: {price}\n⭐ سكور: {total_score:.1f}")
    except: pass

# --- إدارة الخروج والرقابة ---
def monitor_market():
    global VIRTUAL_BALANCE, closed_today
    try:
        btc = exchange.fetch_ticker('BTC/USDT')
        if btc['percentage'] <= BTC_CRASH_LIMIT:
            for s in list(open_positions.keys()): close_trade(s, exchange.fetch_ticker(s)['last'], "🚨 طوارئ BTC")
            return
    except: pass

    for s in list(open_positions.keys()):
        try:
            curr = exchange.fetch_ticker(s)['last']
            pos = open_positions[s]
            elapsed = (datetime.now() - pos['time']).total_seconds() / 3600

            # التتبع السعري (Trailing)
            if curr >= pos['entry'] * 1.01:
                pos['trailing'] = True
                if curr > pos['high']:
                    pos['high'] = curr
                    pos['stop'] = max(pos['stop'], curr * 0.99)

            if curr <= pos['stop']:
                close_trade(s, curr, "🛡️ تتبع" if pos['trailing'] else "❌ وقف")
            elif elapsed > 6 and not pos['trailing']:
                close_trade(s, curr, "⏳ خروج زمني")
        except: pass

def close_trade(symbol, price, reason):
    global VIRTUAL_BALANCE, closed_today
    pos = open_positions[symbol]
    profit_pct = ((price - pos['entry']) / pos['entry']) * 100
    VIRTUAL_BALANCE += POSITION_SIZE * (1 + (profit_pct/100))
    
    # إضافة العملة للقائمة السوداء اليومية لمنع تكرارها
    closed_today.append(symbol)
    
    save_state()
    send_telegram(f"🚪 *إغلاق صفقة*\n🪙 {symbol}\n📝 {reason}\n📈 ربح: {profit_pct:.2f}%\n💰 الرصيد الإجمالي: {get_current_equity():.2f}$")
    del open_positions[symbol]

# --- الدورة الرئيسية ---
last_sector_update = 0
last_hourly_report = datetime.now().hour

send_telegram("🦾 *Apex Sentinel* مفعل وجاهز للعمل...")

while True:
    try:
        now = datetime.now()
        
        # فحص اليوم الجديد
        if now.date() > LAST_RESET_DATE:
            reset_daily_params()

        # تحديث قوة القطاعات كل 4 ساعات
        if time.time() - last_sector_update > 4 * 3600:
            update_sector_strength()
            last_sector_update = time.time()

        # تقرير الساعة
        if now.hour != last_hourly_report:
            eq = get_current_equity()
            send_telegram(f"📊 *تقرير الساعة*\n💰 رصيد: {eq:.2f}$\n📈 نمو اليوم: {((eq-DAILY_START_BALANCE)/DAILY_START_BALANCE)*100:.2f}%")
            last_hourly_report = now.hour

        monitor_market()
        
        # المسح إذا لم نصل للهدف
        eq_check = get_current_equity()
        if ((eq_check - DAILY_START_BALANCE) / DAILY_START_BALANCE) * 100 < DAILY_CEILING:
            tickers = exchange.fetch_tickers()
            # ترتيب حسب السيولة ومسح أفضل 800 عملة تزيد سيولتها عن 100 ألف دولار
            sorted_t = sorted(tickers.items(), key=lambda x: x[1]['quoteVolume'] if x[1]['quoteVolume'] else 0, reverse=True)
            targets = [s for s, t in sorted_t if '/USDT' in s and t['quoteVolume'] > 100000][:800]
            
            with ThreadPoolExecutor(max_workers=15) as exe:
                exe.map(fetch_and_analyze, targets)
        
        time.sleep(60)
    except Exception as e:
        time.sleep(30)
