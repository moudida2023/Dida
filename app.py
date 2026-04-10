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
DB_PATH = "trading_system_v108.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS radar 
            (symbol TEXT PRIMARY KEY, discovery_price REAL, current_price REAL, 
             score INTEGER, discovery_time TEXT)''')
        
        conn.execute('''CREATE TABLE IF NOT EXISTS trades 
            (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, 
             exit_price REAL, investment REAL, status TEXT, score INTEGER, 
             open_time TEXT, close_time TEXT)''')
    print("✅ النظام جاهز: رادار (80) | تداول (90) | حد أقصى (20 صفقة).")

init_db()
EXCHANGE = ccxt.gateio({'enableRateLimit': True})
MAX_OPEN_TRADES = 20

# ======================== 2. محرك التحليل الفني ========================

async def perform_analysis(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=40)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']
        
        score = 0
        ma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        bw = ((ma20 + 2*std20) - (ma20 - 2*std20)) / ma20
        if bw.iloc[-1] < 0.045: score += 50 
        
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 45 < rsi.iloc[-1] < 70: score += 45 
        
        return int(score), close.iloc[-1]
    except: return 0, 0

# ======================== 3. المحرك الرئيسي ========================

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and '3L' not in s and '3S' not in s]
            
            for sym in symbols[:150]:
                price = tickers[sym]['last']
                now_time = datetime.now().strftime('%H:%M:%S')

                with sqlite3.connect(DB_PATH) as conn:
                    # تحديث الأسعار اللحظية
                    conn.execute("UPDATE radar SET current_price = ? WHERE symbol = ?", (price, sym))
                    conn.execute("UPDATE trades SET current_price = ? WHERE symbol = ? AND status = 'OPEN'", (price, sym))

                    score, current_p = await perform_analysis(sym)

                    # أ. الرادار (سكور > 80)
                    if score >= 80:
                        conn.execute('''INSERT OR IGNORE INTO radar (symbol, discovery_price, current_price, score, discovery_time) 
                                      VALUES (?, ?, ?, ?, ?)''', (sym, price, price, score, now_time))

                    # ب. التداول الافتراضي (سكور > 90)
                    cursor = conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
                    open_count = cursor.fetchone()[0]
                    
                    if score >= 90 and open_count < MAX_OPEN_TRADES:
                        conn.execute('''INSERT OR IGNORE INTO trades (symbol, entry_price, current_price, investment, status, score, open_time) 
                                      VALUES (?, ?, ?, 50.0, 'OPEN', score, now_time)''', (sym, price, price, score, now_time))

                    # ج. إدارة الأهداف (6% ربح / 3% خسارة)
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
    radar_rows = ""; open_rows = ""; closed_rows = ""
    
    with sqlite3.connect(DB_PATH) as conn:
        # 1. الرادار (80+)
        cursor = conn.execute("SELECT * FROM radar ORDER BY discovery_time DESC LIMIT 8")
        for r in cursor:
            change = ((r[2] - r[1]) / r[1] * 100)
            color = "#00ff00" if change >= 0 else "#ff4444"
            radar_rows += f"<tr><td>{r[4]}</td><td>{r[0]}</td><td>{r[1]:.4f}</td><td>{r[2]:.4f}</td><td style='color:{color}'>{change:+.2f}%</td></tr>"

        # 2. الصفقات المفتوحة (90+)
        cursor = conn.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY open_time DESC")
        for r in cursor:
            change_pct = ((r[2] - r[1]) / r[1] * 100)
            net_usd = (50.0 * (change_pct / 100))
            color = "#00ff00" if net_usd >= 0 else "#ff4444"
            open_rows += f"<tr><td>{r[7]}</td><td><b>{r[0]}</b></td><td>{r[1]:.4f}</td><td>{r[2]:.4f}</td><td style='color:{color}; font-weight:bold;'>{net_usd:+.2f}$ ({change_pct:+.2f}%)</td></tr>"

        # 3. الصفقات المغلقة
        cursor = conn.execute("SELECT * FROM trades WHERE status != 'OPEN' ORDER BY close_time DESC LIMIT 10")
        for r in closed_cursor:
            final_change = ((r[3] - r[1]) / r[1] * 100)
            final_usd = (50.0 * (final_change / 100))
            color = "#00ff00" if final_usd >= 0 else "#ff4444"
            closed_rows += f"<tr><td>{r[8]}</td><td>{r[0]}</td><td>{r[1]:.4f}</td><td>{r[3]:.4f}</td><td style='color:{color}; font-weight:bold;'>{final_usd:+.2f}$</td><td>{r[5]}</td></tr>"

    return f"""
    <html><head><meta http-equiv="refresh" content="10">
    <style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; padding: 10px; }}
        .section {{ max-width: 1000px; margin: 15px auto; background: #1e2329; border-radius: 8px; padding: 15px; border-top: 3px solid #f0b90b; }}
        table {{ width: 100%; border-collapse: collapse; text-align: center; font-size: 0.85em; }}
        th {{ color: #848e9c; padding: 8px; border-bottom: 1px solid #2b3139; }}
        td {{ padding: 10px; border-bottom: 1px solid #2b3139; }}
        h4 {{ margin: 0 0 10px 0; color: #f0b90b; }}
    </style></head><body>
        <div class="section">
            <h4>📡 رادار الاكتشاف (Score > 80)</h4>
            <table>
                <thead><tr><th>الوقت</th><th>العملة</th><th>سعر الاكتشاف</th><th>السعر الحالي</th><th>التغير %</th></tr></thead>
                <tbody>{radar_rows if radar_rows else "<tr><td colspan='5'>🔎 جاري المسح...</td></tr>"}</tbody>
            </table>
        </div>
        <div class="section" style="border-top-color: #00ff00;">
            <h4>🚀 الصفقات المفتوحة (Score > 90 | Max 20)</h4>
            <table>
                <thead><tr><th>الدخول</th><th>العملة</th><th>سعر الدخول</th><th>السعر الحالي</th><th>صافي الربح/الخسارة ($)</th></tr></thead>
                <tbody>{open_rows if open_rows else "<tr><td colspan='5'>لا توجد صفقات مفتوحة.</td></tr>"}</tbody>
            </table>
        </div>
        <div class="section" style="border-top-color: #848e9c;">
            <h4>✅ سجل الصفقات المغلقة (اليوم)</h4>
            <table>
                <thead><tr><th>الإغلاق</th><th>العملة</th><th>الدخول</th><th>الخروج</th><th>الصافي ($)</th><th>الحالة</th></tr></thead>
                <tbody>{closed_rows if closed_rows else "<tr><td colspan='6'>لا توجد عمليات منتهية.</td></tr>"}</tbody>
            </table>
        </div>
    </body></html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_engine())
