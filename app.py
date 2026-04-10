import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
import json
from flask import Flask, jsonify, send_file
from datetime import datetime

# ======================== 1. الإعدادات وقاعدة البيانات ========================
app = Flask('')
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})
DB_FILE = "database.json"

MAX_OPEN_TRADES = 10
data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        self.open_trades = self.load_from_disk()
        self.last_sync = "بدء..."

    def load_from_disk(self):
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, 'r') as f:
                    return json.load(f)
            except: return []
        return []

    def save_to_disk(self):
        with open(DB_FILE, 'w') as f:
            json.dump(self.open_trades, f, indent=4) # indent لجعل الملف سهل القراءة يدوياً

state = PersistentState()

# ======================== 2. واجهة الموقع والرابط النصي ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        sync = state.last_sync
        count = len(active)

    # (نفس كود الجدول السابق مع إضافة رابط في الأعلى)
    rows = ""
    for tr in reversed(active):
        pnl = ((tr['current_price'] - tr['entry_price']) / tr['entry_price']) * 100
        color = "#00ff00" if pnl >= 0 else "#ff4444"
        rows += f"<tr><td>{tr['time']}</td><td><b>{tr['sym']}</b></td><td>{tr['score']}</td><td>{tr['entry_price']:.6f}</td><td>{tr['current_price']:.6f}</td><td style='color:{color}; font-weight:bold;'>{pnl:+.2f}%</td></tr>"

    return f"""
    <html><head><meta http-equiv="refresh" content="10"><style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; padding: 20px; }}
        .box {{ background: #1e2329; border-radius: 12px; padding: 20px; border-top: 5px solid #f0b90b; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 12px; border-bottom: 1px solid #2b3139; text-align: center; }}
        .btn {{ display: inline-block; padding: 8px 15px; background: #f0b90b; color: #000; text-decoration: none; border-radius: 5px; font-weight: bold; margin-bottom: 10px; }}
    </style></head><body>
        <div class="box">
            <a href="/database" class="btn" target="_blank">📂 فتح سجل البيانات (JSON)</a>
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h2>💾 لوحة التحكم النشطة</h2>
                <span>تحديث: {sync} | العدد: {count}/{MAX_OPEN_TRADES}</span>
            </div>
            <table>
                <thead><tr><th>الوقت</th><th>الزوج</th><th>السكور</th><th>الدخول</th><th>الحالي</th><th>PNL %</th></tr></thead>
                <tbody>{rows if rows else "<tr><td colspan='6'>بانتظار الصفقات...</td></tr>"}</tbody>
            </table>
        </div>
    </body></html>"""

# --- الرابط الجديد لفتح الملف النصي ---
@app.route('/database')
def view_database():
    """هذا المسار يفتح لك الملف النصي مباشرة في المتصفح"""
    if os.path.exists(DB_FILE):
        return send_file(DB_FILE, mimetype='application/json')
    return "سجل البيانات فارغ حالياً."

# ======================== 3. المحرك التقني ========================

async def core_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            now_time = datetime.now().strftime('%H:%M:%S')

            for sym in symbols:
                # محاكاة سكور عشوائي لأغراض الفحص (استبدلها بمعادلاتك الحقيقية)
                score, price = 88, 0.0 # مثال
                
                with data_lock:
                    state.last_sync = now_time
                    # تحديث السعر اللحظي
                    for tr in state.open_trades:
                        if tr['sym'] == sym:
                            # جلب السعر الحقيقي للعملات المفتوحة فقط لتحديث PNL
                            tr['current_price'] = tickers[sym]['last']

                    if score >= 85:
                        exists = any(t['sym'] == sym for t in state.open_trades)
                        if not exists and len(state.open_trades) < MAX_OPEN_TRADES:
                            price_now = tickers[sym]['last']
                            state.open_trades.append({
                                'sym': sym, 'score': score, 'entry_price': price_now, 
                                'current_price': price_now, 'time': now_time
                            })
                            state.save_to_disk() # الحفظ في الملف
                            send_telegram(f"🆕 دخول: {sym} | سكور: {score}")

                await asyncio.sleep(0.01)
            await asyncio.sleep(60)
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(30)

def send_telegram(msg):
    for cid in DESTINATIONS:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": cid, "text": msg})
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(core_engine())
