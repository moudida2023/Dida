import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
import json
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. الإعدادات ========================
app = Flask('')
EXCHANGE = ccxt.binance({'enableRateLimit': True})
DB_FILE = "database.json"

MAX_OPEN_TRADES = 20         # تم التعديل لـ 20
ENTRY_SCORE = 70             # تم خفض السكور لـ 70
INVESTMENT_PER_TRADE = 50.0
data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        self.open_trades = self.load_from_disk()
        self.last_sync = "انتظار..."
        self.total_scanned = 0 # عداد العملات المفحوصة

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

# ======================== 2. محرك التحليل ========================

async def get_score(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=100)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']
        score = 0
        
        # بولنجر (40)
        ma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        bandwidth = ((ma20 + (2 * std20)) - (ma20 - (2 * std20))) / ma20
        if bandwidth.iloc[-1] < 0.05: score += 40 # تساهل بسيط في الانضغاط
            
        # RSI (20)
        delta = close.diff(); gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 45 < rsi.iloc[-1] < 75: score += 20 # توسيع نطاق RSI
            
        # حجم التداول (20)
        if df['vol'].iloc[-1] > df['vol'].rolling(20).mean().iloc[-1] * 1.2: score += 20
            
        # الاتجاه (20)
        if close.iloc[-1] > close.rolling(50).mean().iloc[-1]: score += 20

        return int(score), close.iloc[-1]
    except: return 0, 0

# ======================== 3. المحرك الرئيسي ========================

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            scanned_count = 0
            candidates = []

            for sym in symbols:
                scanned_count += 1
                with data_lock: state.total_scanned = scanned_count # تحديث العداد
                
                score, price = await get_score(sym)
                
                # تحديث الأسعار الحية
                with data_lock:
                    for tr in state.open_trades:
                        if tr['sym'] == sym: tr['current_price'] = tickers[sym]['last']

                if score >= ENTRY_SCORE:
                    with data_lock:
                        if not any(t['sym'] == sym for t in state.open_trades):
                            candidates.append({'sym': sym, 'score': score, 'price': price})
                
                await asyncio.sleep(0.01)

            # اختيار الأفضل وإضافته
            if candidates:
                candidates.sort(key=lambda x: x['score'], reverse=True)
                with data_lock:
                    for c in candidates:
                        if len(state.open_trades) < MAX_OPEN_TRADES:
                            state.open_trades.append({
                                'sym': c['sym'], 'score': c['score'], 
                                'entry_price': c['price'], 'current_price': c['price'],
                                'investment': INVESTMENT_PER_TRADE,
                                'time': datetime.now().strftime('%H:%M:%S')
                            })
                    state.save_to_disk()

            with data_lock: state.last_sync = datetime.now().strftime('%H:%M:%S')
            await asyncio.sleep(60)
        except: await asyncio.sleep(30)

# ======================== 4. واجهة الموقع ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        sync = state.last_sync
        scanned = state.total_scanned
    
    rows = "".join([f"<tr><td>{t['time']}</td><td><b>{t['sym']}</b></td><td style='color:#f0b90b;'>{t['score']}</td><td>{t['entry_price']:.6f}</td><td>{t['current_price']:.6f}</td><td style='color:{'#00ff00' if t['current_price']>=t['entry_price'] else '#ff4444'};'>{((t['current_price']-t['entry_price'])/t['entry_price']*100):+.2f}% (${((t['current_price']-t['entry_price'])/t['entry_price'])*t['investment']:+.2f})</td></tr>" for t in reversed(active)])
    
    return f"""
    <html><head><meta http-equiv="refresh" content="10"><style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; padding: 20px; }}
        .card {{ background: #1e2329; border-radius: 10px; padding: 20px; border-top: 5px solid #f0b90b; }}
        .progress {{ font-size: 0.85em; color: #00ff00; margin-bottom: 5px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        th, td {{ padding: 10px; border: 1px solid #2b3139; text-align: center; }}
    </style></head><body>
        <div class="card">
            <h2>🚀 رادار التداول السريع (v48)</h2>
            <div class="progress">⚙️ يتم الآن فحص العملة رقم: {scanned} | الحد الأقصى: 20 صفقة | سكور: {ENTRY_SCORE}+</div>
            <div style="font-size: 0.9em; color: #848e9c;">آخر تحديث: {sync} | الصفقات الحالية: {len(active)}/20</div>
            <table>
                <thead><tr><th>الوقت</th><th>الزوج</th><th>السكور</th><th>الدخول</th><th>الحالي</th><th>الربح/الخسارة</th></tr></thead>
                <tbody>{rows if rows else "<tr><td colspan='6'>جاري البحث في السوق... ستظهر العملات هنا فور تخطيها سكور 70.</td></tr>"}</tbody>
            </table>
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
