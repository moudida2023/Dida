import asyncio
import ccxt.pro as ccxt
import pandas as pd
import sqlite3
import os
import threading
from flask import Flask
from datetime import datetime

# ======================== 1. إعداد قاعدة البيانات ========================
app = Flask(__name__)
DB_PATH = "trading_system_v107.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        # جدول الرادار (للعملات سكور 85+)
        conn.execute('''CREATE TABLE IF NOT EXISTS radar 
            (symbol TEXT PRIMARY KEY, discovery_price REAL, current_price REAL, 
             score INTEGER, discovery_time TEXT)''')
        
        # جدول الصفقات (للتداول الافتراضي سكور 95+)
        conn.execute('''CREATE TABLE IF NOT EXISTS trades 
            (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, 
             exit_price REAL, investment REAL, status TEXT, score INTEGER, 
             open_time TEXT, close_time TEXT)''')
    print("✅ نظام الرادار والتبادل جاهز.")

init_db()
EXCHANGE = ccxt.gateio({'enableRateLimit': True})

# ======================== 2. محرك التحليل الفني ========================

async def perform_analysis(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=40)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']
        
        score = 0
        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bw = ((ma20 + 2*std20) - (ma20 - 2*std20)) / ma20
        if bw.iloc[-1] < 0.04: score += 50 # ضغط سعري
        
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 50 < rsi.iloc[-1] < 70: score += 45 # زخم إيجابي
        
        return int(score), close.iloc[-1]
    except: return 0, 0

# ======================== 3. المحرك الرئيسي ========================

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and '3L' not in s and '3S' not in s]
            
            for sym in symbols[:120]:
                price = tickers[sym]['last']
                now_time = datetime.now().strftime('%H:%M:%S')

                with sqlite3.connect(DB_PATH) as conn:
                    # تحديث الأسعار في كل الجداول
                    conn.execute("UPDATE radar SET current_price = ? WHERE symbol = ?", (price, sym))
                    conn.execute("UPDATE trades SET current_price = ? WHERE symbol = ? AND status = 'OPEN'", (price, sym))

                    # تحليل العملة
                    score, discovery_p = await perform_analysis(sym)

                    # أ. إضافة للرادار (سكور > 85)
                    if score >= 85:
                        conn.execute('''INSERT OR IGNORE INTO radar (symbol, discovery_price, current_price, score, discovery_time) 
                                      VALUES (?, ?, ?, ?, ?)''', (sym, price, price, score, now_time))

                    # ب. فتح صفقة افتراضية (سكور > 95)
                    if score >= 95:
                        conn.execute('''INSERT OR IGNORE INTO trades (symbol, entry_price, current_price, investment, status, score, open_time) 
                                      VALUES (?, ?, ?, 50.0, 'OPEN', score, now_time)''', (sym, price, price, score, now_time))

                    # ج. فحص إغلاق الصفقات (6% ربح أو 3% خسارة)
                    cursor = conn.execute("SELECT entry_price FROM trades WHERE symbol = ? AND status = 'OPEN'", (sym,))
                    trade = cursor.fetchone()
                    if trade:
                        entry_p = trade[0]
                        change = (price - entry_p) / entry_p
                        if change >= 0.06 or change <= -0.03:
                            status = 'PROFIT' if change >= 0.06 else 'LOSS'
                            conn.execute("UPDATE trades SET exit_price = ?, status = ?, close_time = ? WHERE symbol = ?", (price, status, now_time, sym))

                await asyncio.sleep(0.01)
            await asyncio.sleep(15)
        except: await asyncio.sleep(10)

# ======================== 4. واجهة العرض ========================

@app.route('/')
def dashboard():
    radar_rows = ""
    open_rows = ""
    closed_rows = ""
    
    with sqlite3.connect(DB_PATH) as conn:
        # 1. جدول الرادار (85+)
        cursor = conn.execute("SELECT * FROM radar ORDER BY discovery_time DESC LIMIT 10")
        for r in cursor:
            change = ((r[2] - r[1]) / r[1] * 100)
            color = "#00ff00" if change >= 0 else "#ff4444"
            radar_rows += f"<tr><td>{r[4]}</td><td><b>{r[0]}</b></td><td>{r[1]:.6f}</td><td>{r[2]:.6f}</td><td style='color:{color}'>{change:+.2f}%</td><td>{r[3]}</td></tr>"

        # 2. الصفقات المفتوحة
        cursor = conn.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY open_time DESC")
        for r in cursor:
            change = ((r[2] - r[1]) / r[1] * 100)
            color = "#00ff00" if change >= 0 else "#ff4444"
            open_rows += f"<tr><td>{r[7]}</td><td><b>{r[0]}</b></td><td>{r[1]:.6f}</td><td style='color:{color}'>{change:+.2f}%</td><td>{r[6]}</td></tr>"

        # 3. الصفقات المغلقة
        cursor = conn.execute("SELECT * FROM trades WHERE status != 'OPEN' ORDER BY close_time DESC LIMIT 5")
        for r in cursor:
            change = ((r[3] - r[1]) / r[1] * 100)
            color = "#00ff00" if change >= 0 else "#ff4444"
            closed_rows += f"<tr><td>{r[8]}</td><td>{r[0]}</td><td>{change:+.2f}%</td><td>{r[5]}</td></tr>"

    return f"""
    <html><head><meta http-equiv="refresh" content="10">
    <style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; padding: 10px; font-size: 0.9em; }}
        .section {{ max-width: 900px; margin: 15px auto; background: #1e2329; border-radius: 8px; padding: 15px; border-left: 4px solid #f0b90b; }}
        table {{ width: 100%; border-collapse: collapse; text-align: center; }}
        th {{ color: #848e9c; padding: 8px; border-bottom: 1px solid #2b3139; }}
        td {{ padding: 8px; border-bottom: 1px solid #2b3139; }}
        h4 {{ margin: 0 0 10px 0; color: #f0b90b; text-transform: uppercase; }}
    </style></head><body>
        <div class="section">
            <h4>📡 رادار الاكتشاف (Score > 85)</h4>
            <table>
                <thead><tr><th>وقت الاكتشاف</th><th>العملة</th><th>سعر الاكتشاف</th><th>الحالي</th><th>التغير %</th><th>السكور</th></tr></thead>
                <tbody>{radar_rows if radar_rows else "<tr><td colspan='6'>🔎 جاري الرصد...</td></tr>"}</tbody>
            </table>
        </div>
        <div class="section" style="border-left-color: #00ff00;">
            <h4>🚀 التداول الافتراضي القائم (Score > 95)</h4>
            <table>
                <thead><tr><th>الدخول</th><th>العملة</th><th>سعر الدخول</th><th>التغير %</th><th>السكور</th></tr></thead>
                <tbody>{open_rows if open_rows else "<tr><td colspan='5'>لا توجد صفقات مفتوحة حالياً.</td></tr>"}</tbody>
            </table>
        </div>
        <div class="section" style="border-left-color: #848e9c;">
            <h4>✅ آخر العمليات المغلقة</h4>
            <table>
                <thead><tr><th>الإغلاق</th><th>العملة</th><th>النتيجة %</th><th>الحالة</th></tr></thead>
                <tbody>{closed_rows if closed_rows else "<tr><td colspan='4'>بانتظار تحقيق الأهداف...</td></tr>"}</tbody>
            </table>
        </div>
    </body></html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_engine())
