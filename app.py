import asyncio
import ccxt.pro as ccxt
import pandas as pd
import sqlite3
import os
import threading
from flask import Flask
from datetime import datetime

# ======================== 1. إعدادات قاعدة البيانات ========================
app = Flask(__name__)
DB_PATH = "trading_stable_v112.db"

def get_db_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with get_db_connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS radar 
            (symbol TEXT PRIMARY KEY, discovery_price REAL, current_price REAL, 
             score INTEGER, discovery_time TEXT)''')
        
        conn.execute('''CREATE TABLE IF NOT EXISTS trades 
            (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, 
             exit_price REAL, investment REAL, status TEXT, score INTEGER, 
             open_time TEXT, close_time TEXT)''')
        conn.commit()
    print("✅ Database Initialized.")

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
        bw = ((ma20 + 2*std20) - (ma20 - 2*std20)) / (ma20 + 1e-9)
        if bw.iloc[-1] < 0.04: score += 50 
        
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 45 < rsi.iloc[-1] < 70: score += 45 
        
        return int(score), close.iloc[-1]
    except:
        return 0, 0

# ======================== 3. المحرك الرئيسي (البوت) ========================

async def main_engine():
    print("🚀 Scanner is running...")
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and '3L' not in s and '3S' not in s]
            
            for sym in symbols[:100]:
                try:
                    price = tickers[sym]['last']
                    now_time = datetime.now().strftime('%H:%M:%S')

                    conn = get_db_connection()
                    conn.execute("UPDATE radar SET current_price = ? WHERE symbol = ?", (price, sym))
                    conn.execute("UPDATE trades SET current_price = ? WHERE symbol = ? AND status = 'OPEN'", (price, sym))

                    score, _ = await perform_analysis(sym)

                    # رادار 80+
                    if score >= 80:
                        conn.execute('''INSERT OR IGNORE INTO radar (symbol, discovery_price, current_price, score, discovery_time) 
                                      VALUES (?, ?, ?, ?, ?)''', (sym, price, price, score, now_time))

                    # تداول 90+
                    open_count = conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'").fetchone()[0]
                    if score >= 90 and open_count < MAX_OPEN_TRADES:
                        conn.execute('''INSERT OR IGNORE INTO trades (symbol, entry_price, current_price, investment, status, score, open_time) 
                                      VALUES (?, ?, ?, 50.0, 'OPEN', score, now_time)''', (sym, price, price, score, now_time))

                    # مراقبة الأهداف
                    trade_info = conn.execute("SELECT entry_price FROM trades WHERE symbol = ? AND status = 'OPEN'", (sym,)).fetchone()
                    if trade_info:
                        entry_p = trade_info[0]
                        change = (price - entry_p) / entry_p
                        if change >= 0.06 or change <= -0.03:
                            status = 'PROFIT' if change >= 0.06 else 'LOSS'
                            conn.execute("UPDATE trades SET exit_price = ?, current_price = ?, status = ?, close_time = ? WHERE symbol = ?", 
                                         (price, price, status, now_time, sym))
                    
                    conn.commit()
                    conn.close()
                except:
                    continue
                await asyncio.sleep(0.05)
            
            await asyncio.sleep(20)

        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(10)

# ======================== 4. واجهة الموقع ========================

@app.route('/')
def dashboard():
    radar_rows = ""; open_rows = ""; closed_rows = ""
    conn = get_db_connection()
    try:
        # 1. الرادار
        r_cur = conn.execute("SELECT * FROM radar ORDER BY discovery_time DESC LIMIT 10")
        for r in r_cur:
            change = ((r[2] - r[1]) / (r[1] + 1e-9)) * 100
            color = "#00ff00" if change >= 0 else "#ff4444"
            radar_rows += f"<tr><td>{r[4]}</td><td>{r[0]}</td><td>{r[1]:.4f}</td><td>{r[2]:.4f}</td><td style='color:{color}'>{change:+.2f}%</td></tr>"

        # 2. المفتوحة
        o_cur = conn.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY open_time DESC")
        for r in o_cur:
            ch_pct = ((r[2] - r[1]) / (r[1] + 1e-9)) * 100
            net = (50.0 * (ch_pct / 100))
            color = "#00ff00" if net >= 0 else "#ff4444"
            open_rows += f"<tr><td>{r[7]}</td><td><b>{r[0]}</b></td><td>{r[1]:.4f}</td><td style='color:{color}; font-weight:bold;'>{net:+.2f}$ ({ch_pct:+.2f}%)</td></tr>"

        # 3. المغلقة (تم تصحيح اسم المتغير هنا)
        c_cur = conn.execute("SELECT * FROM trades WHERE status != 'OPEN' ORDER BY close_time DESC LIMIT 10")
        for r in c_cur:
            f_ch = ((r[3] - r[1]) / (r[1] + 1e-9)) * 100
            f_net = (50.0 * (f_ch / 100))
            color = "#00ff00" if f_net >= 0 else "#ff4444"
            closed_rows += f"<tr><td>{r[8]}</td><td>{r[0]}</td><td>{f_net:+.2f}$</td><td>{r[5]}</td></tr>"
    finally:
        conn.close()

    return f"""
    <html><head><meta http-equiv="refresh" content="10">
    <style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; padding: 10px; }}
        .box {{ max-width: 950px; margin: 15px auto; background: #1e2329; border-radius: 8px; padding: 15px; border-top: 3px solid #f0b90b; }}
        table {{ width: 100%; border-collapse: collapse; text-align: center; font-size: 0.85em; }}
        th {{ color: #848e9c; padding: 8px; border-bottom: 1px solid #2b3139; }}
        td {{ padding: 10px; border-bottom: 1px solid #2b3139; }}
        h4 {{ margin: 0 0 10px 0; color: #f0b90b; }}
    </style></head><body>
        <div class="box">
            <h4>📡 Radar Discovery (80+)</h4>
            <table>
                <thead><tr><th>Time</th><th>Pair</th><th>Disc. Price</th><th>Live Price</th><th>Change %</th></tr></thead>
                <tbody>{radar_rows if radar_rows else "<tr><td colspan='5'>Scanning...</td></tr>"}</tbody>
            </table>
        </div>
        <div class="box" style="border-top-color: #00ff00;">
            <h4>🚀 Open Virtual Trades (90+ | $50)</h4>
            <table>
                <thead><tr><th>Open</th><th>Pair</th><th>Entry</th><th>Net Profit ($)</th></tr></thead>
                <tbody>{open_rows if open_rows else "<tr><td colspan='4'>No Open Trades.</td></tr>"}</tbody>
            </table>
        </div>
        <div class="box" style="border-top-color: #848e9c;">
            <h4>✅ Closed Trades History</h4>
            <table>
                <thead><tr><th>Close</th><th>Pair</th><th>Result ($)</th><th>Status</th></tr></thead>
                <tbody>{closed_rows if closed_rows else "<tr><td colspan='4'>Waiting for exits...</td></tr>"}</tbody>
            </table>
        </div>
    </body></html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # تشغيل الفلاسك
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    # تشغيل المحرك
    asyncio.run(main_engine())
