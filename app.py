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
ENTRY_SCORE = 60 

data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        # 1. قائمة القيم الافتراضية (Initial Default List)
        self.open_trades = [
            {
                "sym": "BTC/USDT", 
                "score": 95, 
                "entry_price": 65000.0, 
                "current_price": 65100.0, 
                "time": datetime.now().strftime('%H:%M:%S'),
                "status": "DEFAULT_TEST"
            },
            {
                "sym": "ETH/USDT", 
                "score": 88, 
                "entry_price": 3500.0, 
                "current_price": 3505.0, 
                "time": datetime.now().strftime('%H:%M:%S'),
                "status": "DEFAULT_TEST"
            },
            {
                "sym": "BNB/USDT", 
                "score": 82, 
                "entry_price": 580.0, 
                "current_price": 582.0, 
                "time": datetime.now().strftime('%H:%M:%S'),
                "status": "DEFAULT_TEST"
            }
        ]
        
        self.total_scanned = 0
        self.last_sync = "بدء..."
        self.last_db_fill = "جاري الترحيل الأول..."
        
        # 2. تنفيذ الترحيل الفوري عند التشغيل
        self.remplir_DB()

    def remplir_DB(self):
        """دالة ترحيل المعطيات من الذاكرة إلى قاعدة البيانات"""
        with data_lock:
            try:
                with open(DB_FILE, 'w') as f:
                    json.dump(self.open_trades, f, indent=4)
                self.last_db_fill = datetime.now().strftime('%H:%M:%S')
                print(f"✅ [remplir_DB] تم ترحيل {len(self.open_trades)} صفقة بنجاح.")
            except Exception as e:
                print(f"❌ خطأ ترحيل: {e}")

    def load_from_disk(self):
        # تستخدم هذه الدالة فقط إذا أردت استعادة صفقات قديمة من الملف
        try:
            if os.path.exists(DB_FILE):
                with open(DB_FILE, 'r') as f: return json.load(f)
        except: return []
        return []

state = PersistentState()

# ======================== 2. خيط المزامنة الدوري ========================

def database_auto_filler():
    """تحديث قاعدة البيانات كل 20 ثانية لضمان المطابقة"""
    while True:
        state.remplir_DB()
        time.sleep(20)

# ======================== 3. المحرك الرئيسي (البحث عن صفقات جديدة) ========================

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                with data_lock: state.total_scanned += 1
                
                # تحديث أسعار الصفقات الافتراضية والحقيقية
                price = tickers[sym]['last']
                with data_lock:
                    for tr in state.open_trades:
                        if tr['sym'] == sym:
                            tr['current_price'] = price

                    # إضافة صفقات جديدة (إذا تجاوز السكور 60)
                    score = 65 if tickers[sym]['percentage'] > 3 else 0
                    if score >= ENTRY_SCORE and len(state.open_trades) < MAX_OPEN_TRADES:
                        if not any(t['sym'] == sym for t in state.open_trades):
                            state.open_trades.append({
                                'sym': sym, 'score': score, 
                                'entry_price': price, 'current_price': price,
                                'time': datetime.now().strftime('%H:%M:%S'),
                                'status': 'LIVE'
                            })
                await asyncio.sleep(0.01)
            
            with data_lock: state.last_sync = datetime.now().strftime('%H:%M:%S')
            await asyncio.sleep(5)
        except: await asyncio.sleep(10)

# ======================== 4. واجهة العرض ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        last_fill = state.last_db_fill
    
    rows = "".join([f"<tr style='border-bottom:1px solid #2b3139;'><td>{t['time']}</td><td><b>{t['sym']}</b></td><td>{t['score']}</td><td>{t['current_price']:.2f}</td><td>{t.get('status','')}</td></tr>" for t in reversed(active)])

    return f"""<html><head><meta http-equiv="refresh" content="10"></head>
    <body style="background:#0b0e11; color:white; font-family:sans-serif; padding:20px;">
        <div style="max-width:850px; margin:auto; background:#1e2329; padding:20px; border-radius:12px; border:1px solid #363a45;">
            <h2 style="color:#f0b90b;">🚀 نظام المزامنة الذكي v61</h2>
            <div style="background:#2b3139; padding:15px; border-radius:8px; margin-bottom:20px; border-left:5px solid #00ff00;">
                <p style="margin:0;">⚙️ حالة الترحيل عبر <b>remplir_DB</b>: <span style="color:#00ff00;">نشط ({last_fill})</span></p>
                <p style="margin-top:5px; font-size:0.85em; color:#848e9c;">يتم نقل "القيم الافتراضية + الصفقات الحية" إلى ملف JSON كل 20 ثانية.</p>
            </div>
            <table style="width:100%; text-align:center; border-collapse:collapse;">
                <thead style="color:#848e9c;"><tr><th>الوقت</th><th>الزوج</th><th>السكور</th><th>السعر الحالي</th><th>الحالة</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
            <div style="margin-top:20px; text-align:center;">
                <a href="/database" target="_blank" style="color:#f0b90b; text-decoration:none;">🔗 رابط قاعدة البيانات الخام (JSON)</a>
            </div>
        </div></body></html>"""

@app.route('/database')
def view_db():
    return send_file(DB_FILE, mimetype='application/json') if os.path.exists(DB_FILE) else "[]"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # تشغيل خيط الترحيل التلقائي
    threading.Thread(target=database_auto_filler, daemon=True).start()
    # تشغيل الموقع والمحرك
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
