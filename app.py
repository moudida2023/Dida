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
DB_FILE = "/tmp/database.json" # المسار المسموح به في Render

EXCHANGE = ccxt.binance({'enableRateLimit': True})
MAX_OPEN_TRADES = 20
ENTRY_SCORE = 60 

data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        self.open_trades = [] # القائمة في الذاكرة (List)
        self.total_scanned = 0
        self.last_sync = "بدء..."
        self.last_db_fill = "لم يبدأ بعد"
        
        # تحميل البيانات السابقة إن وجدت
        self.load_initial_data()

    def load_initial_data(self):
        try:
            if os.path.exists(DB_FILE):
                with open(DB_FILE, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list): self.open_trades = data
        except: pass
        
        # إضافة TEST للتأكد من البداية
        if not any(t['sym'] == "TEST/USDT" for t in self.open_trades):
            self.open_trades.append({
                "sym": "TEST/USDT", "score": 99, "entry_price": 1.0, 
                "current_price": 1.05, "time": datetime.now().strftime('%H:%M:%S')
            })

    # دالة remplir_DB التي طلبتها: تنقل المعطيات من الذاكرة إلى الملف
    def remplir_DB(self):
        with data_lock:
            try:
                # تحويل القائمة الحالية إلى ملف JSON
                with open(DB_FILE, 'w') as f:
                    json.dump(self.open_trades, f, indent=4)
                self.last_db_fill = datetime.now().strftime('%H:%M:%S')
                print(f"✅ [remplir_DB] تم مزامنة {len(self.open_trades)} صفقة مع قاعدة البيانات.")
            except Exception as e:
                print(f"❌ خطأ في remplir_DB: {e}")

state = PersistentState()

# ======================== 2. الخيط المستقل لتشغيل الدالة ========================

def database_auto_filler():
    """هذه الدالة تعمل في الخلفية وتقوم باستدعاء remplir_DB كل 30 ثانية"""
    while True:
        state.remplir_DB()
        time.sleep(30) # تحديث قاعدة البيانات كل 30 ثانية

# ======================== 3. محرك البحث (البحث عن صفقات جديدة) ========================

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                with data_lock: state.total_scanned += 1
                
                # تحليل بسيط (كمثال)
                score = 65 if tickers[sym]['percentage'] > 2 else 0 
                price = tickers[sym]['last']

                with data_lock:
                    # تحديث الأسعار في الذاكرة (List)
                    for tr in state.open_trades:
                        if tr['sym'] in tickers:
                            tr['current_price'] = tickers[tr['sym']]['last']

                    # إضافة صفقة جديدة للذاكرة (List)
                    if score >= ENTRY_SCORE and len(state.open_trades) < MAX_OPEN_TRADES:
                        if not any(t['sym'] == sym for t in state.open_trades):
                            state.open_trades.append({
                                'sym': sym, 'score': score, 
                                'entry_price': price, 'current_price': price,
                                'time': datetime.now().strftime('%H:%M:%S')
                            })
                await asyncio.sleep(0.01)
            
            with data_lock: state.last_sync = datetime.now().strftime('%H:%M:%S')
            await asyncio.sleep(10)
        except: await asyncio.sleep(10)

# ======================== 4. واجهة الموقع ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        last_fill = state.last_db_fill
    
    rows = "".join([f"<tr><td>{t['time']}</td><td><b>{t['sym']}</b></td><td>{t['score']}</td><td>{t['current_price']:.4f}</td></tr>" for t in reversed(active)])

    return f"""<html><head><meta http-equiv="refresh" content="10"></head>
    <body style="background:#0b0e11; color:white; font-family:sans-serif; padding:20px;">
        <div style="max-width:800px; margin:auto; background:#1e2329; padding:20px; border-radius:10px; border-top:5px solid #00ff00;">
            <h2>📊 نظام الترحيل الآلي (v60)</h2>
            <div style="background:#2b3139; padding:10px; border-radius:5px; margin-bottom:15px;">
                <p style="margin:0; color:#00ff00;">🔄 آخر ترحيل للدالة <b>remplir_DB</b>: {last_fill}</p>
                <p style="font-size:0.8em; color:#848e9c;">المسار: {DB_FILE} | <a href="/database" style="color:#f0b90b;">رابط JSON</a></p>
            </div>
            <table border="1" style="width:100%; text-align:center; border-collapse:collapse;">
                <thead><tr style="color:#f0b90b;"><th>الوقت</th><th>الزوج</th><th>السكور</th><th>السعر</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div></body></html>"""

@app.route('/database')
def view_db():
    return send_file(DB_FILE, mimetype='application/json') if os.path.exists(DB_FILE) else "[]"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # تشغيل دالة الترحيل الدوري في الخلفية
    threading.Thread(target=database_auto_filler, daemon=True).start()
    # تشغيل الموقع
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    # تشغيل المحرك
    asyncio.get_event_loop().run_until_complete(main_engine())
