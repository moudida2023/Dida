import asyncio
import ccxt.pro as ccxt
import pandas as pd
import sqlite3
import os
import threading
import requests
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات الخاصة بك ========================
app = Flask(__name__)
DB_PATH = "trading_stable_v115.db"

# تم إدراج التوكن والآيدي الخاص بك
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID, 
            "text": message, 
            "parse_mode": "Markdown"
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Error: {e}")

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
        # 1. Bollinger Band Squeeze (4.5% Compression)
        ma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        bw = ((ma20 + 2*std20) - (ma20 - 2*std20)) / (ma20 + 1e-9)
        if bw.iloc[-1] < 0.045: score += 50 
        
        # 2. RSI Condition (Safe Zone)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 40 < rsi.iloc[-1] < 70: score += 45 
        
        return int(score), close.iloc[-1]
    except: return 0, 0

# ======================== 3. المحرك الرئيسي ========================

async def main_engine():
    print("🚀 البوت متصل بالتلجرام وجاري فحص السوق...")
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and '3L' not in s and '3S' not in s]
            
            for sym in symbols[:120]:
                try:
                    price = tickers[sym]['last']
                    now_time = datetime.now().strftime('%H:%M:%S')
                    conn = get_db_connection()

                    # تحديث حي للأسعار
                    conn.execute("UPDATE radar SET current_price = ? WHERE symbol = ?", (price, sym))
                    conn.execute("UPDATE trades SET current_price = ? WHERE symbol = ? AND status = 'OPEN'", (price, sym))

                    score, _ = await perform_analysis(sym)

                    # رادار المراقبة (70+)
                    if score >= 70:
                        conn.execute('''INSERT OR IGNORE INTO radar (symbol, discovery_price, current_price, score, discovery_time) 
                                      VALUES (?, ?, ?, ?, ?)''', (sym, price, price, score, now_time))

                    # دخول صفقة (85+) وإرسال إشعار
                    open_count = conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'").fetchone()[0]
                    if score >= 85 and open_count < MAX_OPEN_TRADES:
                        cursor = conn.execute('''INSERT OR IGNORE INTO trades (symbol, entry_price, current_price, investment, status, score, open_time) 
                                              VALUES (?, ?, ?, 50.0, 'OPEN', score, now_time)''', (sym, price, price, score, now_time))
                        
                        if cursor.rowcount > 0:
                            msg = (f"🔔 *إشارة دخول قوية (Score: {score})*\n\n"
                                   f"🪙 العملة: `{sym}`\n"
                                   f"💰 السعر: `{price}`\n"
                                   f"💵 الاستثمار: `50.0 USDT`\n"
                                   f"⏰ الوقت: `{now_time}`")
                            send_telegram_msg(msg)

                    # إدارة الأهداف (6% ربح / 3% خسارة)
                    trade = conn.execute("SELECT entry_price FROM trades WHERE symbol = ? AND status = 'OPEN'", (sym,)).fetchone()
                    if trade:
                        entry_p = trade[0]
                        change = (price - entry_p) / entry_p
                        if change >= 0.06 or change <= -0.03:
                            status = 'PROFIT' if change >= 0.06 else 'LOSS'
                            conn.execute("UPDATE trades SET exit_price = ?, current_price = ?, status = ?, close_time = ? WHERE symbol = ?", 
                                         (price, price, status, now_time, sym))
                            
                            icon = "✅" if status == 'PROFIT' else "❌"
                            close_msg = (f"{icon} *إغلاق صفقة*\n\n"
                                         f"🪙 العملة: `{sym}`\n"
                                         f"📉 النتيجة: `{change*100:+.2f}%`\n"
                                         f"💵 السعر النهائي: `{price}`")
                            send_telegram_msg(close_msg)
                    
                    conn.commit()
                    conn.close()
                except: continue
                await asyncio.sleep(0.05)
            await asyncio.sleep(20)
        except: await asyncio.sleep(10)

# ======================== 4. واجهة العرض (Dashboard) ========================

@app.route('/')
def index():
    radar_rows = ""; open_rows = ""
    conn = get_db_connection()
    try:
        r_cur = conn.execute("SELECT * FROM radar ORDER BY discovery_time DESC LIMIT 10")
        for r in r_cur:
            change = ((r[2] - r[1]) / (r[1] + 1e-9)) * 100
            color = "#00ff00" if change >= 0 else "#ff4444"
            radar_rows += f"<tr><td>{r[4]}</td><td>{r[0]}</td><td>{r[1]:.4f}</td><td>{r[2]:.4f}</td><td style='color:{color}'>{change:+.2f}%</td></tr>"

        o_cur = conn.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY open_time DESC")
        for r in o_cur:
            ch_pct = ((r[2] - r[1]) / (r[1] + 1e-9)) * 100
            net = (50.0 * (ch_pct / 100))
            color = "#00ff00" if net >= 0 else "#ff4444"
            open_rows += f"<tr><td>{r[7]}</td><td><b>{r[0]}</b></td><td>{r[1]:.4f}</td><td style='color:{color}; font-weight:bold;'>{net:+.2f}$ ({ch_pct:+.2f}%)</td></tr>"
    finally: conn.close()

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
            <h4>📡 مراقبة السوق (Score 70+)</h4>
            <table>
                <thead><tr><th>الوقت</th><th>العملة</th><th>البداية</th><th>الحالي</th><th>تغير %</th></tr></thead>
                <tbody>{radar_rows if radar_rows else "<tr><td colspan='5'>🔎 جاري الفحص...</td></tr>"}</tbody>
            </table>
        </div>
        <div class="box" style="border-top-color: #00ff00;">
            <h4>🚀 الصفقات المفتوحة (Score 85+ | $50)</h4>
            <table>
                <thead><tr><th>الدخول</th><th>العملة</th><th>السعر</th><th>الصافي ($)</th></tr></thead>
                <tbody>{open_rows if open_rows else "<tr><td colspan='4'>لا توجد صفقات مفتوحة. الإشعارات مفعلة على التلجرام.</td></tr>"}</tbody>
            </table>
        </div>
    </body></html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_engine())
