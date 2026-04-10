import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import json
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. إعدادات المسار والقاعدة ========================
app = Flask('')

# استخدام مسار /tmp لضمان صلاحيات الكتابة على سيرفر Render
DB_FILE = "/tmp/database.json"

EXCHANGE = ccxt.binance({'enableRateLimit': True})
MAX_OPEN_TRADES = 20
ENTRY_SCORE = 60 # سكور مرن للتأكد من عمل النظام
INVESTMENT = 10.0       

data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        # التأكد من وجود الملف عند التشغيل
        if not os.path.exists(DB_FILE):
            self.write_json([])
        
        self.open_trades = self.load_from_disk()
        self.total_scanned = 0
        self.last_sync = "بدء..."
        self.last_disk_save = datetime.now().strftime('%H:%M:%S')

        # إضافة صفحة اختبار فورية
        if not any(t['sym'] == "TEST/USDT" for t in self.open_trades):
            self.open_trades.append({
                "sym": "TEST/USDT", "score": 99, "entry_price": 1.0, 
                "current_price": 1.05, "investment": 10.0, 
                "time": datetime.now().strftime('%H:%M:%S')
            })
            self.save_to_disk()

    def load_from_disk(self):
        try:
            if os.path.exists(DB_FILE):
                with open(DB_FILE, 'r') as f: return json.load(f)
        except: return []
        return []

    def write_json(self, data):
        try:
            with open(DB_FILE, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"❌ Error writing: {e}")

    def save_to_disk(self):
        with data_lock:
            self.write_json(self.open_trades)
            self.last_disk_save = datetime.now().strftime('%H:%M:%S')

state = PersistentState()

# (محرك البحث والتحليل)
async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            for sym in symbols:
                with data_lock: state.total_scanned += 1
                # كود التحليل (مبسط للتجربة)
                score = 65 # افتراضي للتجربة
                price = tickers[sym]['last']
                
                with data_lock:
                    if score >= ENTRY_SCORE and len(state.open_trades) < MAX_OPEN_TRADES:
                        if not any(t['sym'] == sym for t in state.open_trades):
                            state.open_trades.append({
                                'sym': sym, 'score': score, 'entry_price': price, 
                                'current_price': price, 'investment': INVESTMENT,
                                'time': datetime.now().strftime('%H:%M:%S')
                            })
                            state.save_to_disk()
                await asyncio.sleep(0.01)
            with data_lock: state.last_sync = datetime.now().strftime('%H:%M:%S')
            await asyncio.sleep(30)
        except: await asyncio.sleep(10)

# ======================== 2. واجهة الموقع مع الروابط ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        disk_time = state.last_disk_save
    
    rows = "".join([f"<tr style='border-bottom:1px solid #2b3139;'><td>{t['time']}</td><td><b>{t['sym']}</b></td><td>{t['score']}</td><td>{t['current_price']:.4f}</td></tr>" for t in reversed(active)])

    # الرابط الكامل لموقعك (سيظهر أسفل الصفحة)
    app_url = "https://dida-fvym.onrender.com"

    return f"""<html><head><meta http-equiv="refresh" content="15"></head>
    <body style="background:#0b0e11; color:white; font-family:sans-serif; padding:20px;">
        <div style="max-width:800px; margin:auto; background:#1e2329; padding:25px; border-radius:12px; border:1px solid #363a45;">
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid #f0b90b; padding-bottom:15px;">
                <h2 style="margin:0; color:#f0b90b;">🚀 رادار الصفقات v59</h2>
                <a href="/database" target="_blank" style="background:#f0b90b; color:black; padding:10px 20px; border-radius:8px; text-decoration:none; font-weight:bold;">📄 عرض ملف JSON</a>
            </div>
            
            <div style="margin:20px 0; background:#2b3139; padding:15px; border-radius:8px;">
                <p style="margin:0; color:#848e9c; font-size:0.9em;">
                    🔗 <b>رابط قاعدة البيانات المباشر:</b><br>
                    <a href="{app_url}/database" style="color:#f0b90b; text-decoration:none;">{app_url}/database</a>
                </p>
                <p style="margin-top:10px; font-size:0.8em; color:#aab2bd;">آخر تحديث للملف: {disk_time}</p>
            </div>

            <table style="width:100%; text-align:center; border-collapse:collapse;">
                <thead style="color:#848e9c; font-size:0.9em;"><tr><th>الوقت</th><th>الزوج</th><th>السكور</th><th>السعر</th></tr></thead>
                <tbody>{rows if rows else "<tr><td colspan='4'>جاري البحث...</td></tr>"}</tbody>
            </table>
        </div>
    </body></html>"""

@app.route('/database')
def view_db():
    if os.path.exists(DB_FILE):
        return send_file(DB_FILE, mimetype='application/json')
    return "[]"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
