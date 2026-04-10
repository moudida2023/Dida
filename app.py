import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
import json
from flask import Flask, send_file
from datetime import datetime

app = Flask('')
EXCHANGE = ccxt.binance({'enableRateLimit': True})
DB_FILE = "database.json"

MAX_OPEN_TRADES = 20
ENTRY_SCORE = 50 
INVESTMENT = 50.0
data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        self.open_trades = self.load_from_disk()
        self.last_sync = "بدء الاختبار..."
        self.total_scanned = 0
        
        # --- نظام الحقن التجريبي (Test Injection) ---
        # إذا كان الملف فارغاً، سنضع صفقة وهمية فوراً للتأكد من الربط
        if not self.open_trades:
            print("🛠️ جاري حقن صفقة تجريبية للتأكد من عمل الموقع...")
            self.open_trades.append({
                "sym": "TEST/USDT",
                "score": 100,
                "entry_price": 10.0,
                "current_price": 10.5,
                "investment": 50.0,
                "time": datetime.now().strftime('%H:%M:%S')
            })
            self.save_to_disk()

    def load_from_disk(self):
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, 'r') as f: return json.load(f)
            except: return []
        return []

    def save_to_disk(self):
        with open(DB_FILE, 'w') as f:
            json.dump(self.open_trades, f, indent=4)

state = PersistentState()

# (بقية دوال التحليل الفني والمحرك تبقى كما هي لضمان استمرار البحث)

async def get_score_fast(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=30)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        return 60, df['c'].iloc[-1] # سكور وهمي سريع
    except: return 0, 0

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            scanned = 0
            for sym in symbols:
                scanned += 1
                with data_lock: state.total_scanned = scanned
                
                # تحديث الأسعار الحية بما فيها الصفقة التجريبية
                with data_lock:
                    for tr in state.open_trades:
                        if tr['sym'] == sym: tr['current_price'] = tickers[sym]['last']
                        # تحديث سعر العملة التجريبية للتأكد من الـ PNL
                        if tr['sym'] == "TEST/USDT": tr['current_price'] += 0.001

                score, price = await get_score_fast(sym)
                
                if score >= ENTRY_SCORE:
                    with data_lock:
                        if not any(t['sym'] == sym for t in state.open_trades):
                            if len(state.open_trades) < MAX_OPEN_TRADES:
                                state.open_trades.append({
                                    'sym': sym, 'score': score, 
                                    'entry_price': price, 'current_price': price,
                                    'investment': INVESTMENT,
                                    'time': datetime.now().strftime('%H:%M:%S')
                                })
                                state.save_to_disk()

                await asyncio.sleep(0.01)
            
            with data_lock: state.last_sync = datetime.now().strftime('%H:%M:%S')
            await asyncio.sleep(60)
        except: await asyncio.sleep(30)

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        sync = state.last_sync
        count = state.total_scanned
    
    # حساب الصفوف مع حساب الربح بالدولار والنسبة
    rows = ""
    for t in reversed(active):
        pnl_pct = ((t['current_price'] - t['entry_price']) / t['entry_price']) * 100
        pnl_usd = (pnl_pct / 100) * t['investment']
        color = "#00ff00" if pnl_pct >= 0 else "#ff4444"
        rows += f"""<tr style="border-bottom: 1px solid #2b3139;">
            <td style="padding:10px;">{t['time']}</td>
            <td><b>{t['sym']}</b></td>
            <td>{t['score']}</td>
            <td>{t['entry_price']:.4f}</td>
            <td>{t['current_price']:.4f}</td>
            <td style="color:{color}; font-weight:bold;">{pnl_pct:+.2f}% (${pnl_usd:+.2f})</td>
        </tr>"""
    
    return f"""<html><head><meta http-equiv="refresh" content="10"></head>
    <body style="background:#0b0e11; color:#eaecef; font-family:sans-serif; padding:20px;">
        <div style="background:#1e2329; border-radius:10px; padding:20px; border-top: 5px solid #f0b90b;">
            <h2>📊 اختبار الاتصال الذاتي (v50)</h2>
            <p style="color:#848e9c;">آخر تحديث: {sync} | تم فحص: {count} عملة</p>
            <table style="width:100%; border-collapse:collapse; text-align:center;">
                <thead style="background:#2b3139; color:#f0b90b;">
                    <tr><th>الوقت</th><th>الزوج</th><th>السكور</th><th>الدخول</th><th>الحالي</th><th>الربح/الخسارة</th></tr>
                </thead>
                <tbody>{rows if rows else "<tr><td colspan='6'>جاري تحميل البيانات...</td></tr>"}</tbody>
            </table>
            <p style="margin-top:20px;"><a href="/database" style="color:#f0b90b;">📂 فتح قاعدة البيانات الخام</a></p>
        </div>
    </body></html>"""

@app.route('/database')
def view_db():
    if os.path.exists(DB_FILE): return send_file(DB_FILE, mimetype='application/json')
    return "[]"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
