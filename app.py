import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import json
import time
import requests
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. الإعدادات المحدثة ========================
app = Flask('')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.json")

# بيانات التلجرام (يرجى ملئها لتعمل)
TELEGRAM_TOKEN = "YOUR_BOT_TOKEN"
CHAT_IDS = ["YOUR_CHAT_ID"] 

EXCHANGE = ccxt.binance({'enableRateLimit': True})

# الإعدادات الجديدة حسب طلبك
MAX_OPEN_TRADES = 20    # الحد الأقصى 20 صفقة
ENTRY_SCORE = 85        # سكور مرتفع (سيولة قوية)
INVESTMENT = 10.0       # 10 دولار لكل صفقة

data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        self.open_trades = self.load_from_disk()
        self.total_scanned = 0
        self.last_sync = "بدء المسح..."
        self.last_disk_save = datetime.now().strftime('%H:%M:%S')

        # --- خطوة الاختبار: إضافة صفقة TEST فوراً إذا كانت القائمة فارغة ---
        if not self.open_trades:
            print("🛠️ حقن صفقة تجريبية (TEST) للتأكد من قاعدة البيانات...")
            test_trade = {
                "sym": "TEST/USDT",
                "score": 99,
                "entry_price": 1.0,
                "current_price": 1.05,
                "investment": 10.0,
                "time": datetime.now().strftime('%H:%M:%S')
            }
            self.open_trades.append(test_trade)
            self.save_to_disk() # حفظ فوري للتجربة

    def load_from_disk(self):
        try:
            if os.path.exists(DB_FILE):
                with open(DB_FILE, 'r') as f:
                    data = json.load(f)
                    return data if isinstance(data, list) else []
        except: pass
        return []

    def save_to_disk(self):
        with data_lock:
            try:
                with open(DB_FILE, 'w') as f:
                    json.dump(self.open_trades, f, indent=4)
                self.last_disk_save = datetime.now().strftime('%H:%M:%S')
                print(f"💾 [حفظ دوري] تم تحديث JSON بنجاح.")
            except Exception as e:
                print(f"❌ فشل الحفظ: {e}")

state = PersistentState()

# ======================== 2. محرك التحليل (سكور 85+) ========================

async def get_high_liquidity_score(sym):
    try:
        # جلب شمعات الساعة واليوم لتحليل السيولة
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=50)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        
        score = 0
        current_v = df['v'].iloc[-1]
        avg_v = df['v'].mean()

        # شرط السيولة القوي (حجم التداول الحالي ضعف المتوسط)
        if current_v > avg_v * 2: score += 50
        
        # شرط السعر (اتجاه صاعد قوي)
        if df['c'].iloc[-1] > df['c'].iloc[-5]: score += 40

        return score, df['c'].iloc[-1]
    except: return 0, 0

# ======================== 3. المحرك الرئيسي والتلجرام ========================

def send_telegram(msg):
    for cid in CHAT_IDS:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                          json={"chat_id": cid, "text": msg, "parse_mode": "HTML"})
        except: pass

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                with data_lock: state.total_scanned += 1
                
                score, price = await get_high_liquidity_score(sym)
                
                with data_lock:
                    # تحديث الأسعار الحية
                    for tr in state.open_trades:
                        if tr['sym'] in tickers:
                            tr['current_price'] = tickers[tr['sym']]['last']

                    # فحص دخول صفقة جديدة (سكور 85+)
                    if score >= ENTRY_SCORE and len(state.open_trades) < MAX_OPEN_TRADES:
                        if not any(t['sym'] == sym for t in state.open_trades):
                            new_t = {
                                'sym': sym, 'score': score, 'entry_price': price, 
                                'current_price': price, 'investment': INVESTMENT,
                                'time': datetime.now().strftime('%H:%M:%S')
                            }
                            state.open_trades.append(new_t)
                            
                            # إرسال تلجرام فوراً
                            msg = f"✅ <b>إشارة سيولة عالية (85+)</b>\nالعملة: {sym}\nالسعر: {price}\nالاستثمار: $10"
                            threading.Thread(target=send_telegram, args=(msg,)).start()
                
                await asyncio.sleep(0.01)
            
            with data_lock: state.last_sync = datetime.now().strftime('%H:%M:%S')
            await asyncio.sleep(60)
        except: await asyncio.sleep(30)

# ======================== 4. العرض والحفظ الدوري ========================

def database_scheduler():
    while True:
        time.sleep(900) # حفظ كل 15 دقيقة
        state.save_to_disk()

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        sync = state.last_sync
        disk = state.last_disk_save
    
    rows = ""
    for t in reversed(active):
        pnl = ((t['current_price'] - t['entry_price']) / t['entry_price']) * 100
        rows += f"<tr><td>{t['time']}</td><td><b>{t['sym']}</b></td><td>{t['score']}</td><td>{t['current_price']:.4f}</td><td>{pnl:+.2f}%</td></tr>"

    return f"""<html><head><meta http-equiv="refresh" content="10"></head>
    <body style="background:#0b0e11; color:white; font-family:sans-serif; padding:20px;">
        <h2>📊 نظام الرصد والسيولة (v55)</h2>
        <p>فحص: {state.total_scanned} | تحديث: {sync} | <b>آخر حفظ JSON: {disk}</b></p>
        <table border="1" style="width:100%; text-align:center; border-collapse:collapse;">
            <thead style="background:#2b3139;"><tr><th>الوقت</th><th>الزوج</th><th>السكور</th><th>السعر</th><th>الربح</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </body></html>"""

@app.route('/database')
def view_db():
    return send_file(DB_FILE) if os.path.exists(DB_FILE) else "[]"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=database_scheduler, daemon=True).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
