import asyncio
import ccxt.pro as ccxt
import pandas as pd
import sqlite3
import os
import threading
from flask import Flask
from datetime import datetime

# ======================== 1. إعداد قاعدة بيانات SQL ========================
app = Flask(__name__)
DB_PATH = "gateio_radar.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS signals 
            (symbol TEXT PRIMARY KEY, 
             entry_price REAL, 
             current_price REAL, 
             score INTEGER,
             time TEXT)''')
    print("✅ قاعدة بيانات SQL لـ Gate.io جاهزة.")

init_db()

# تغيير المنصة إلى Gate.io
EXCHANGE = ccxt.gateio({'enableRateLimit': True})
data_lock = threading.Lock()

# ======================== 2. محرك التحليل (الطرائق الجديدة) ========================

async def analyze_gate_market(sym):
    try:
        # جلب البيانات (Gate.io تستخدم OHLCV أيضاً)
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=40)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']
        
        score = 0
        # 1. Bollinger Squeeze
        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bw = ((ma20 + 2*std20) - (ma20 - 2*std20)) / ma20
        if bw.iloc[-1] < 0.05: score += 40
        
        # 2. RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 50 < rsi.iloc[-1] < 75: score += 30
        
        # 3. Volume Spike
        if df['vol'].iloc[-1] > df['vol'].rolling(20).mean().iloc[-1] * 1.5: score += 30
        
        return int(score), close.iloc[-1]
    except: return 0, 0

# ======================== 3. المحرك الرئيسي لتحديث البيانات ========================

async def main_engine():
    print("🚀 رادار Gate.io بدأ العمل الآن...")
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            # تصفية العملات المقابلة لـ USDT فقط
            symbols = [s for s in tickers.keys() if '/USDT' in s and '3L' not in s and '3S' not in s]
            
            for sym in symbols[:100]: # نفحص أول 100 عملة لسرعة النتائج
                current_price = tickers[sym]['last']
                
                # تحديث الأسعار الحالية في SQL
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("UPDATE signals SET current_price = ? WHERE symbol = ?", (current_price, sym))
                
                # تحليل العملة للبحث عن فرص
                score, entry_price = await analyze_gate_market(sym)
                
                if score >= 70:
                    now = datetime.now().strftime('%H:%M:%S')
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute('''INSERT OR IGNORE INTO signals (symbol, entry_price, current_price, score, time) 
                                      VALUES (?, ?, ?, ?, ?)''', (sym, entry_price, current_price, score, now))
                
                await asyncio.sleep(0.01)
            
            await asyncio.sleep(20)
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(10)

# ======================== 4. واجهة الموقع ========================

@app.route('/')
def dashboard():
    rows = ""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT * FROM signals ORDER BY time DESC LIMIT 20")
        for r in cursor:
            # تلوين السعر الحالي بناءً على الربح أو الخسارة
            pnl_color = "#00ff00" if r[2] >= r[1] else "#ff4444"
            rows += f"""
            <tr style="border-bottom: 1px solid #2b3139;">
                <td style="color:#f0b90b; font-weight:bold; padding:12px;">{r[0]}</td>
                <td>{r[1]:.6f}</td>
                <td style="color:{pnl_color}; font-weight:bold;">{r[2]:.6f}</td>
                <td><span style="background:#363a45; padding:2px 10px; border-radius:10px;">{r[3]}</span></td>
                <td style="font-size:0.8em; color:#848e9c;">{r[4]}</td>
            </tr>"""

    return f"""
    <html><head><meta http-equiv="refresh" content="10">
    <style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; text-align: center; padding: 20px; }}
        .card {{ max-width: 900px; margin: auto; background: #1e2329; border-radius: 12px; padding: 20px; border-top: 5px solid #f0b90b; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        th {{ color: #848e9c; padding: 12px; border-bottom: 2px solid #2b3139; }}
        td {{ padding: 12px; }}
    </style></head><body>
        <div class="card">
            <h2>📊 رادار تداول Gate.io (v104)</h2>
            <p style="color:#848e9c;">اسم العملة | سعر الدخول | السعر الحالي | السكور</p>
            <table>
                <thead>
                    <tr><th>العملة</th><th>سعر الدخول</th><th>السعر الحالي</th><th>السكور</th><th>التوقيت</th></tr>
                </thead>
                <tbody>
                    {rows if rows else "<tr><td colspan='5' style='padding:30px;'>🔎 جاري تحليل أزواج Gate.io...</td></tr>"}
                </tbody>
            </table>
        </div>
    </body></html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_engine())
