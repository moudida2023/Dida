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
# إعدادات المستخدم (يجب تعبئتها)
# ==========================================
TELEGRAM_TOKEN = "YOUR_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"

# ==========================================
# الثوابت وإدارة المخاطر
# ==========================================
MAX_OPEN_POSITIONS = 20
DAILY_PROFIT_CAP = 6.0     # التوقف عند ربح 6%
CAUTION_SCORE_THRESHOLD = 92 # سكور أعلى عند اقتراب الهدف
NORMAL_SCORE_THRESHOLD = 88  # سكور الدخول العادي
BTC_CRASH_LIMIT = -2.0     # قاطع التيار إذا هبط البيتكوين 2%
BALANCE_FILE = "trading_state.json"

# إعدادات المنصة (Gate.io)
exchange = ccxt.gateio({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

# تصنيف القطاعات
SECTORS = {
    'AI': ['FET', 'RNDR', 'NEAR', 'TAO', 'GRT', 'AKT', 'OCEAN'],
    'L1_L2': ['BTC', 'ETH', 'SOL', 'AVAX', 'MATIC', 'OP', 'ARB', 'SUI', 'DOT'],
    'MEME': ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'LADYS'],
    'DEFI': ['UNI', 'AAVE', 'LINK', 'CAKE', 'RUNE', 'PENDLE', 'JOE'],
    'GAMING': ['GALA', 'IMX', 'BEAM', 'AXS', 'SAND', 'MANA', 'NAKA']
}

# متغيرات العمل (تُحدث تلقائياً)
open_positions = {}
sector_allocations = {}

# ==========================================
# وظائف إدارة البيانات والارباح المركبة
# ==========================================
def load_state():
    if os.path.exists(BALANCE_FILE):
        try:
            with open(BALANCE_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {"total_equity": 1000.0, "daily_start": 1000.0, "last_reset": str(datetime.now().date())}

def save_state():
    state = {
        "total_equity": get_current_equity(),
        "daily_start": DAILY_START_BALANCE,
        "last_reset": str(LAST_RESET_DATE)
    }
    with open(BALANCE_FILE, 'w') as f:
        json.dump(state, f)

# تحميل البيانات عند الإقلاع
state = load_state()
VIRTUAL_BALANCE = state["total_equity"]
DAILY_START_BALANCE = state["daily_start"]
LAST_RESET_DATE = datetime.strptime(state["last_reset"], '%Y-%m-%d').date()
POSITION_SIZE = VIRTUAL_BALANCE / MAX_OPEN_POSITIONS

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={msg}&parse_mode=Markdown"
    try: requests.get(url, timeout=5)
    except: print("Telegram error")

def get_current_equity():
    return VIRTUAL_BALANCE + (len(open_positions) * POSITION_SIZE)

def reset_daily_cycle():
    """إعادة حساب المحفظة لليوم الجديد (الفائدة المركبة)"""
    global VIRTUAL_BALANCE, POSITION_SIZE, DAILY_START_BALANCE, LAST_RESET_DATE
    current_eq = get_current_equity()
    VIRTUAL_BALANCE = current_eq
    DAILY_START_BALANCE = current_eq
    POSITION_SIZE = current_eq / MAX_OPEN_POSITIONS
    LAST_RESET_DATE = datetime.now().date()
    save_state()
    send_telegram(f"🔄 *بداية يوم جديد*\n💰 الرصيد الجديد: {current_eq:.2f}$\n📏 حجم الصفقة: {POSITION_SIZE:.2f}$")

# ==========================================
# دراسة السوق والتدوير القطاعي
# ==========================================
def update_market_sectors():
    global sector_allocations
    strengths = {}
    print("📊 دراسة حركة القطاعات...")
    for sector, coins in SECTORS.items():
        changes = []
        for coin in coins[:4]:
            try:
                t = exchange.fetch_ticker(f"{coin}/USDT")
                changes.append(t['percentage'])
            except: continue
        strengths[sector] = sum(changes)/len(changes) if changes else -99

    sorted_sec = sorted(strengths.items(), key=lambda x: x[1], reverse=True)
    # توزيع 20 صفقة ديناميكياً حسب قوة القطاع
    alloc_map = [7, 5, 3, 3, 2] 
    
    sector_allocations = {sec: (alloc_map[i] if i < len(alloc_map) else 1) for i, (sec, val) in enumerate(sorted_sec)}
    
    report = "📊 *ترتيب القطاعات اليوم:*\n" + "\n".join([f"🔹 {k}: {strengths[k]:+.2f}% (حصة: {v})" for k,v in sector_allocations.items()])
    send_telegram(report)

# ==========================================
# منطق التحليل الفني والدخول
# ==========================================
def analyze_and_trade(symbol):
    global VIRTUAL_BALANCE
    if len(open_positions) >= MAX_OPEN_POSITIONS or symbol in open_positions: return

    try:
        current_eq = get_current_equity()
        daily_pnl = ((current_eq - DAILY_START_BALANCE) / DAILY_START_BALANCE) * 100
        if daily_pnl >= DAILY_PROFIT_CAP: return

        # فحص حصة القطاع
        coin_base = symbol.split('/')[0]
        sector = 'OTHERS'
        for s, coins in SECTORS.items():
            if coin_base in coins: sector = s; break
        
        allowed = sector_allocations.get(sector, 1)
        current_in_sec = sum(1 for p in open_positions.values() if p['sector'] == sector)
        if current_in_sec >= allowed: return

        # التحليل الفني
        data = {}
        for tf in ['4h', '1h', '15m']:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=50)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df.ta.ema(length=9, append=True); df.ta.ema(length=21, append=True)
            df.ta.rsi(length=14, append=True); df.ta.macd(append=True)
            data[tf] = df

        # حساب السكور
        scores = {}
        for tf in ['4h', '1h', '15m']:
            df = data[tf]; last = df.iloc[-1]; s = 0
            if last['EMA_9'] > last['EMA_21']: s += 20
            if last['v'] > (df['v'].tail(10).mean() * 1.5): s += 25
            if 50 < last['RSI_14'] < 70: s += 15
            if last['MACD_12_26_9'] > last['MACDs_12_26_9']: s += 20
            if last['c'] > df['h'].iloc[-11:-1].max(): s += 20
            scores[tf] = s
        
        final_score = (scores['4h']*0.2) + (scores['1h']*0.3) + (scores['15m']*0.5)
        required_score = CAUTION_SCORE_THRESHOLD if daily_pnl >= 4.0 else NORMAL_SCORE_THRESHOLD
        
        if final_score >= required_score:
            entry_price = data['15m'].iloc[-1]['c']
            VIRTUAL_BALANCE -= POSITION_SIZE
            open_positions[symbol] = {
                'entry': entry_price, 'stop': entry_price * 0.99, 
                'high': entry_price, 'trailing': False, 'sector': sector, 'time': datetime.now()
            }
            send_telegram(f"🚀 *شراء {symbol}*\n💰 السعر: {entry_price}\n⭐ سكور: {final_score:.1f}\n📂 قطاع: {sector}")
    except: pass

# ==========================================
# مراقبة السوق والخروج
# ==========================================
def monitor_exit():
    global VIRTUAL_BALANCE
    try:
        btc = exchange.fetch_ticker('BTC/USDT')
        if btc['percentage'] <= BTC_CRASH_LIMIT:
            for s in list(open_positions.keys()): close_position(s, exchange.fetch_ticker(s)['last'], "🚨 انهيار BTC")
            return
    except: pass

    for s in list(open_positions.keys()):
        try:
            curr_price = exchange.fetch_ticker(s)['last']
            pos = open_positions[s]
            age = (datetime.now() - pos['time']).total_seconds() / 3600
            
            # تفعيل التتبع عند ربح 1%
            if curr_price >= pos['entry'] * 1.01:
                pos['trailing'] = True
                if curr_price > pos['high']:
                    pos['high'] = curr_price
                    pos['stop'] = max(pos['stop'], curr_price * 0.99)

            if curr_price <= pos['stop']:
                close_position(s, curr_price, "🛡️ تتبع" if pos['trailing'] else "❌ وقف")
            elif age > 6 and not pos['trailing']:
                close_position(s, curr_price, "⏳ زمن")
        except: pass

def close_position(symbol, price, reason):
    global VIRTUAL_BALANCE
    pos = open_positions[symbol]
    pnl = ((price - pos['entry']) / pos['entry']) * 100
    VIRTUAL_BALANCE += POSITION_SIZE * (1 + (pnl/100))
    save_state()
    send_telegram(f"🚪 *إغلاق {symbol}*\n📝 السبب: {reason}\n📈 الربح: {pnl:.2f}%\n💵 الرصيد: {get_current_equity():.2f}$")
    del open_positions[symbol]

# ==========================================
# الحلقة الرئيسية
# ==========================================
last_sec_upd = 0
last_hr_rep = datetime.now().hour

print("🤖 Apex Sentinel Bot is active...")

while True:
    try:
        now = datetime.now()
        
        if now.date() > LAST_RESET_DATE: reset_daily_cycle()

        if time.time() - last_sec_upd > 4 * 3600:
            update_market_sectors()
            last_sec_upd = time.time()

        if now.hour != last_hr_rep:
            eq = get_current_equity()
            send_telegram(f"📊 *تقرير الساعة*\n💰 المحفظة: {eq:.2f}$\n📈 نمو اليوم: {((eq-DAILY_START_BALANCE)/DAILY_START_BALANCE)*100:.2f}%")
            last_hr_rep = now.hour

        monitor_exit()
        
        # المسح (800 عملة حسب السيولة)
        if ((get_current_equity() - DAILY_START_BALANCE) / DAILY_START_BALANCE) * 100 < DAILY_PROFIT_CAP:
            tks = exchange.fetch_tickers()
            sorted_tks = sorted(tks.items(), key=lambda x: x[1]['quoteVolume'] if x[1]['quoteVolume'] else 0, reverse=True)
            symbols = [s for s, t in sorted_tks if '/USDT' in s and t['quoteVolume'] > 100000][:800]
            
            with ThreadPoolExecutor(max_workers=15) as exe: exe.map(analyze_and_trade, symbols)
        
        time.sleep(60)
    except Exception as e:
        print(f"Error: {e}"); time.sleep(30)
