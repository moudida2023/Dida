import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import json
import time
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. الإعدادات والمسارات ========================
app = Flask('')
DB_FILE = "/tmp/database.json"

EXCHANGE = ccxt.binance({'enableRateLimit': True})
MAX_OPEN_TRADES = 20
ENTRY_SCORE = 60       # تم التعديل لـ 60 للتجربة
INVESTMENT = 10.0      

data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        self.high_score_list = [] 
        self.total_scanned = 0
        self.last_sync = "بدء..."
        self.last_db_fill = "جاري الانتظار..."
        
        # محاولة تحميل البيانات الموجودة مسبقاً
        self.load_from_disk()

    def load_from_disk(self):
        try:
            if os.path.exists(DB_FILE):
                with open(DB_FILE, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list): self.high_score_list = data
        except: pass

    # دالة ترحيل البيانات إلى ملف JSON
    def remplir_DB(self):
        with data_lock:
            try:
                with open(DB_FILE, 'w') as f:
                    json.dump(self.high_score_list, f, indent=4)
                self.last_db_fill = datetime.now().strftime('%H:%M:%S')
                print(f"💾 [remplir_DB] تم الترحيل في التوقيت: {self.last_db_fill}")
            except Exception as e:
                print(f"❌ خطأ ترحيل: {e}")

state = PersistentState()

# ======================== 2. خيط الترحيل الدوري (كل دقيقة) ========================

def scheduled_filler():
    """دالة تقوم بالترحيل الإجباري كل 60 ثانية"""
    while True:
        time.sleep(60)
        state.remplir_DB()

# ======================== 3. محرك الصيد السريع (100 عملة) ========================

async def get_score(sym):
    try:
        # فحص سريع لآخر 10 شمعات فقط
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=10)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        score = 0
        if df['c'].iloc[-1] > df['o'].iloc[-1]: score += 30 # شمعة خضراء
        if df['v'].iloc[-1] > df['v'].mean(): score += 30   # حجم جيد
        return score, df['c'].iloc[-1]
    except: return 0, 0

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            # جلب أول 100 عملة USDT فقط للتجربة السريعة
            all_symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            symbols = all_symbols[:100] 
            
            for sym in symbols:
                with data_lock: state.total_scanned += 1
                score, price = await get_score(sym)
                
                with data_lock:
                    # تحديث أسعار الصفقات الحالية
                    for tr in state.high_score_list:
                        if tr['sym'] == sym: tr['current_price'] = price

                    # الصيد بسكور 60+
                    if score >= ENTRY_SCORE and len(state.high_score_list) < MAX_OPEN_TRADES:
                        if not any(t['sym'] == sym for t in state.high_score_list):
                            state.high_score_list.append({
                                'sym': sym, 'score': score, 
                                'entry_price': price, 'current_price': price,
                                'time': datetime.now().strftime('%H:%M:%S')
                            })
                            # حفظ فوري عند الصيد لضمان المزامنة
                            state.remplir_DB()
                
                await asyncio.sleep(0.01)
            
            with data_lock: 
                state.last_sync = datetime.now().strftime('%H:%M:%S')
                state.total_scanned = 0 # تصفير العداد لبدء دورة جديدة
            await asyncio.sleep(5)
        except: await asyncio.sleep(10)

# ======================== 4. واجهة العرض ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.high_score_list)
        last_fill = state.last_db_fill
    
    rows = "".join([f"<tr style='border-bottom:1px solid #2b3139;'><td>{t['time']}</td><td><b>{t['sym']}</b></td><td style='color:#00ff00;'>{t['score']}</td><td>{t['current_price']:.4f}</td></tr>" for t in reversed(active)])

    return f"""<html><head><meta http-equiv="refresh" content="10"></head>
    <body style="background:#0b0e11; color:white; font-family:sans-serif; padding:20px;">
        <div style="max-width:800px; margin:auto; background:#1e2329; padding:20px; border-radius:12px;">
            <h2 style="color:#f0b90b;">🧪 نسخة التجربة السريعة (v64)</h2>
            <div style="background:#2b3139; padding:10px; border-radius:5px; margin-bottom:15px; border-left:5px solid #f0b90b;">
                <p style="margin:0;">📉 السكور المطلوب: <b>60</b> | 🎯 العملات المفحوصة: <b>أول 100</b></p>
                <p style="margin-top:5px; color:#00ff00;">🔄 توقيت آخر ترحيل آلي (كل دقيقة): <b>{last_fill}</b></p>
            </div>
            <table style="width:100%; text-align:center; border-collapse:collapse;">
                <thead><tr style="color:#848e9c;"><th>الوقت</th><th>العملة</th><th>السكور</th><th>السعر</th></tr></thead>
                <tbody>{rows if rows else "<tr><td colspan='4'>جاري فحص الـ 100 عملة...</td></tr>"}</tbody>
            </table>
            <div style="margin-top:20px; text-align:center;">
                <a href="/database" target="_blank" style="color:#f0b90b;">📂 فتح قاعدة البيانات الخام</a>
            </div>
        </div></body></html>"""

@app.route('/database')
def view_db():
    return send_file(DB_FILE, mimetype='application/json') if os.path.exists(DB_FILE) else "[]"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # تشغيل خيط الترحيل الدوري
    threading.Thread(target=scheduled_filler, daemon=True).start()
    # تشغيل الموقع والمحرك
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
