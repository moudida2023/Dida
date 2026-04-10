import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
import json
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. الإعدادات والربط ========================
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

# ======================== 2. محرك التحليل الفني الصارم ========================

async def get_strict_score(sym):
    """تحليل فني حقيقي لمنع الصفقات العشوائية"""
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=100)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        close = df['close']
        last_price = close.iloc[-1]
        score = 0
        
        # 1. انضغاط بولنجر (40 نقطة) - للبحث عن الانفجار السعري
        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        upper = ma20 + (2 * std20)
        lower = ma20 - (2 * std20)
        bandwidth = (upper - lower) / ma20
        if bandwidth.iloc[-1] < 0.04: # انضغاط قوي
            score += 40
            
        # 2. مؤشر RSI (20 نقطة) - قوة نسبية بدون تشبع
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        if 50 < rsi.iloc[-1] < 70:
            score += 20
            
        # 3. حجم التداول (20 نقطة) - تأكيد السيولة
        avg_vol = df['vol'].rolling(20).mean()
        if df['vol'].iloc[-1] > avg_vol.iloc[-1] * 1.5: # زيادة 50% في السيولة
            score += 20
            
        # 4. الاتجاه العام (20 نقطة)
        ma200 = close.rolling(100).mean()
        if last_price > ma200.iloc[-1]:
            score += 20

        return int(score), last_price
    except:
        return 0, 0

# ======================== 3. المحرك الرئيسي للسيرفر ========================

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                score, price = await get_strict_score(sym)
                now = datetime.now().strftime('%H:%M:%S')

                with data_lock:
                    state.last_sync = now
                    # تحديث أسعار الصفقات المفتوحة في الموقع
                    for tr in state.open_trades:
                        if tr['sym'] == sym:
                            tr['current_price'] = tickers[sym]['last']

                    # شروط الدخول الصارمة
                    if score >= 85:
                        exists = any(t['sym'] == sym for t in state.open_trades)
                        if not exists:
                            # 1. إرسال للتلغرام دائماً
                            send_telegram(f"🎯 *إشارة ذهبية مؤكدة*\nالعملة: `{sym}`\nالسكور: `{score}`\nالسعر: `{price:.6f}`")

                            # 2. الإضافة للموقع إذا توفر مساحة
                            if len(state.open_trades) < MAX_OPEN_TRADES:
                                state.open_trades.append({
                                    'sym': sym, 'score': score, 'entry_price': price, 
                                    'current_price': price, 'time': now
                                })
                                state.save_to_disk()

                await asyncio.sleep(0.01) # سرعة المسح
            await asyncio.sleep(60)
        except Exception as e:
            await asyncio.sleep(30)

# ======================== 4. واجهة الموقع ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        sync = state.last_sync
    
    rows = "".join([f"<tr><td>{t['time']}</td><td><b>{t['sym']}</b></td><td>{t['score']}</td><td>{t['entry_price']:.6f}</td><td>{t['current_price']:.6f}</td><td>{((t['current_price']-t['entry_price'])/t['entry_price']*100):+.2f}%</td></tr>" for t in reversed(active)])
    
    return f"""
    <html><head><meta http-equiv="refresh" content="10"><style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; padding: 20px; }}
        .card {{ background: #1e2329; border-radius: 10px; padding: 20px; border-top: 5px solid #f0b90b; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 12px; border: 1px solid #2b3139; text-align: center; }}
    </style></head><body>
        <div class="card">
            <h2>📈 لوحة تحكم السيرفر (v45)</h2>
            <p>آخر تحديث للسوق: {sync} | الصفقات المفتوحة: {len(active)}/10</p>
            <a href="/database" style="color:#f0b90b;">📂 فتح ملف الـ JSON</a>
            <table>
                <thead><tr><th>الوقت</th><th>الزوج</th><th>السكور</th><th>الدخول</th><th>الحالي</th><th>PNL%</th></tr></thead>
                <tbody>{rows if rows else "<tr><td colspan='6'>جاري البحث عن صفقات قوية...</td></tr>"}</tbody>
            </table>
        </div>
    </body></html>"""

@app.route('/database')
def view_db():
    if os.path.exists(DB_FILE): return send_file(DB_FILE, mimetype='application/json')
    return "[]"

def send_telegram(msg):
    for cid in DESTINATIONS:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"})
        except: pass

if __name__ == "__main__":
    # تشغيل على بورت 8080 لضمان الاستقرار على السيرفرات
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
