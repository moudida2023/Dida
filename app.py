import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
import json
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. الإعدادات وقاعدة البيانات ========================
app = Flask('')
EXCHANGE = ccxt.binance({'enableRateLimit': True})
DB_FILE = "database.json"

MAX_OPEN_TRADES = 10
INVESTMENT_PER_TRADE = 50.0  # الميزانية لكل صفقة
data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        self.open_trades = self.load_from_disk()
        self.last_sync = "انتظار المسحة الأولى..."

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

# ======================== 2. محرك التحليل الفني ========================

async def get_strict_score(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=100)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']
        last_price = close.iloc[-1]
        score = 0
        
        # 1. انضغاط بولنجر (40)
        ma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        bandwidth = ((ma20 + (2 * std20)) - (ma20 - (2 * std20))) / ma20
        if bandwidth.iloc[-1] < 0.04: score += 40
            
        # 2. RSI (20)
        delta = close.diff(); gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 50 < rsi.iloc[-1] < 70: score += 20
            
        # 3. حجم التداول (20)
        if df['vol'].iloc[-1] > df['vol'].rolling(20).mean().iloc[-1] * 1.5: score += 20
            
        # 4. الاتجاه (20)
        if last_price > close.rolling(100).mean().iloc[-1]: score += 20

        return int(score), last_price
    except: return 0, 0

# ======================== 3. المحرك الرئيسي (الاختيار الذكي) ========================

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            candidates = [] # قائمة مؤقتة لتخزين العملات القوية في هذه المسحة
            
            # المرحلة الأولى: مسح السوق وجمع المرشحين
            for sym in symbols:
                score, price = await get_strict_score(sym)
                if score >= 85:
                    # نتحقق إذا كانت العملة موجودة أصلاً في الجدول
                    with data_lock:
                        if not any(t['sym'] == sym for t in state.open_trades):
                            candidates.append({'sym': sym, 'score': score, 'price': price})
                
                # تحديث الأسعار اللحظية للصفقات المفتوحة حالياً
                with data_lock:
                    for tr in state.open_trades:
                        if tr['sym'] == sym: tr['current_price'] = tickers[sym]['last']
                
                await asyncio.sleep(0.01)

            # المرحلة الثانية: اختيار الأفضل (Sort by Score)
            if candidates:
                # ترتيب المرشحين من الأعلى سكوراً
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

# ======================== 4. واجهة الموقع المحدثة ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        sync = state.last_sync
    
    rows = ""
    for t in reversed(active):
        pnl_pct = ((t['current_price'] - t['entry_price']) / t['entry_price']) * 100
        pnl_usd = (pnl_pct / 100) * t['investment']
        color = "#00ff00" if pnl_pct >= 0 else "#ff4444"
        
        rows += f"""
        <tr>
            <td>{t['time']}</td>
            <td><b>{t['sym']}</b></td>
            <td style="color:#f0b90b;">{t['score']}</td>
            <td>{t['entry_price']:.6f}</td>
            <td>{t['current_price']:.6f}</td>
            <td style="color:{color}; font-weight:bold;">{pnl_pct:+.2f}% (${pnl_usd:+.2f})</td>
        </tr>"""
    
    return f"""
    <html><head><meta http-equiv="refresh" content="10"><style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; padding: 20px; }}
        .card {{ background: #1e2329; border-radius: 10px; padding: 20px; border-top: 5px solid #f0b90b; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 12px; border: 1px solid #2b3139; text-align: center; }}
        .stat-bar {{ display: flex; justify-content: space-between; margin-bottom: 15px; color: #848e9c; }}
    </style></head><body>
        <div class="card">
            <h2>🏆 رادار النخبة (أعلى سكور + ميزانية $50)</h2>
            <div class="stat-bar">
                <span>تحديث السوق: {sync}</span>
                <span>الميزانية لكل صفقة: ${INVESTMENT_PER_TRADE}</span>
                <span>الصفقات: {len(active)}/10</span>
            </div>
            <table>
                <thead><tr><th>الوقت</th><th>الزوج</th><th>السكور</th><th>الدخول</th><th>الحالي</th><th>الربح/الخسارة</th></tr></thead>
                <tbody>{rows if rows else "<tr><td colspan='6'>جاري البحث عن أقوى الفرص في السوق...</td></tr>"}</tbody>
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
