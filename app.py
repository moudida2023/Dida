import asyncio
import ccxt.pro as ccxt
import pandas as pd
import sqlite3
import os
import threading
import requests
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات والربط ========================
app = Flask(__name__)
DB_PATH = "trading_stats_v119.db"
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
INITIAL_BALANCE = 500.0  # الرصيد الافتراضي الذي حددته سابقاً

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=5)
    except: pass

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

# ======================== 2. الاستراتيجية الفنية ========================

async def perform_analysis(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=35)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']
        score = 0
        ma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        bw = ((ma20 + 2*std20) - (ma20 - 2*std20)) / (ma20 + 1e-9)
        if bw.iloc[-1] < 0.045: score += 50 
        delta = close.diff(); gain = (delta.where(delta > 0, 0)).rolling(14).mean(); loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 40 < rsi.iloc[-1] < 70: score += 45 
        return int(score), close.iloc[-1]
    except: return 0, 0

# ======================== 3. المحرك الرئيسي ========================

async def main_engine():
    print("🚀 النظام يعمل مع لوحة الإحصائيات المتطورة...")
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and '3L' not in s and '3S' not in s]
            for sym in symbols[:110]:
                try:
                    price = tickers[sym]['last']
                    score, _ = await perform_analysis(sym)
                    now_time = datetime.now().strftime('%H:%M:%S')
                    conn = get_db_connection()
                    conn.execute("UPDATE radar SET current_price = ? WHERE symbol = ?", (price, sym))
                    conn.execute("UPDATE trades SET current_price = ? WHERE symbol = ? AND status = 'OPEN'", (price, sym))
                    if score >= 70:
                        conn.execute("INSERT OR REPLACE INTO radar VALUES (?, ?, ?, ?, ?)", (sym, price, price, score, now_time))
                    open_count = conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'").fetchone()[0]
                    if score >= 85 and open_count < 10:
                        cursor = conn.execute("INSERT OR IGNORE INTO trades (symbol, entry_price, current_price, investment, status, score, open_time) VALUES (?, ?, ?, 50.0, 'OPEN', ?, ?)", (sym, price, price, score, now_time))
                        if cursor.rowcount > 0:
                            send_telegram_msg(f"🔔 *دخول صفقة:* {sym} (Score: {score})")
                    trade = conn.execute("SELECT entry_price FROM trades WHERE symbol = ? AND status = 'OPEN'", (sym,)).fetchone()
                    if trade:
                        entry_p = trade[0]; change = (price - entry_p) / entry_p
                        if change >= 0.06 or change <= -0.03:
                            status = 'PROFIT' if change >= 0.06 else 'LOSS'
                            conn.execute("UPDATE trades SET exit_price = ?, status = ?, close_time = ? WHERE symbol = ?", (price, status, now_time, sym))
                            send_telegram_msg(f"{'✅' if status == 'PROFIT' else '❌'} *إغلاق:* {sym} ({change*100:+.2f}%)")
                    conn.commit(); conn.close()
                except: continue
                await asyncio.sleep(0.05)
            await asyncio.sleep(15)
        except: await asyncio.sleep(10)

# ======================== 4. واجهة العرض (Dashboard) ========================

@app.route('/')
def dashboard():
    conn = get_db_connection()
    # حساب الإحصائيات
    open_trades = conn.execute("SELECT investment, entry_price, current_price FROM trades WHERE status = 'OPEN'").fetchall()
    closed_trades = conn.execute("SELECT investment, entry_price, exit_price FROM trades WHERE status != 'OPEN'").fetchall()
    
    used_capital = sum([t[0] for t in open_trades])
    
    # حساب الأرباح المحققة (المغلقة)
    realized_pnl = sum([ (t[0] * ((t[2]-t[1])/t[1])) for t in closed_trades ])
    # حساب الأرباح العائمة (المفتوحة حالياً)
    unrealized_pnl = sum([ (t[0] * ((t[2]-t[1])/t[1])) for t in open_trades ])
    
    total_pnl = realized_pnl + unrealized_pnl
    current_balance = INITIAL_BALANCE + realized_pnl
    
    radar = conn.execute("SELECT * FROM radar ORDER BY score DESC LIMIT 10").fetchall()
    trades_list = conn.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY open_time DESC").fetchall()
    conn.close()

    r_rows = "".join([f"<tr><td>{r[4]}</td><td><b>{r[0]}</b></td><td>{r[3]}</td><td>{r[2]:.4f}</td></tr>" for r in radar])
    t_rows = "".join([f"<tr><td>{t[7]}</td><td>{t[0]}</td><td>{t[1]:.4f}</td><td class='{'profit' if t[2]>=t[1] else 'loss'}'>{((t[2]-t[1])/t[1]*100):+.2f}%</td></tr>" for t in trades_list])

    return f"""
    <html><head><meta http-equiv="refresh" content="10">
    <style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; margin:0; padding: 20px; }}
        .stats-bar {{ display: flex; justify-content: space-around; background: #1e2329; padding: 20px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #333; }}
        .stat-item {{ text-align: center; }}
        .stat-value {{ font-size: 1.4em; font-weight: bold; color: #f0b90b; }}
        .stat-label {{ color: #848e9c; font-size: 0.9em; margin-top: 5px; }}
        .box {{ background: #1e2329; border-radius: 10px; padding: 15px; margin-bottom: 20px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px; text-align: center; border-bottom: 1px solid #2b3139; }}
        .profit {{ color: #00ff00; }} .loss {{ color: #ff4444; }}
    </style></head><body>
        <div class="stats-bar">
            <div class="stat-item"><div class="stat-value">${current_balance:.2f}</div><div class="stat-label">إجمالي المحفظة</div></div>
            <div class="stat-item"><div class="stat-item"><div class="stat-value">${used_capital:.2f}</div><div class="stat-label">المبلغ المستعمل</div></div></div>
            <div class="stat-item"><div class="stat-value {'profit' if total_pnl >=0 else 'loss'}">${total_pnl:+.2f}</div><div class="stat-label">النتيجة العامة</div></div>
        </div>
        <div class="box">
            <h4 style="color:#f0b90b">🚀 صفقات مفتوحة</h4>
            <table><tr><th>الوقت</th><th>العملة</th><th>الدخول</th><th>التغير %</th></tr>{t_rows if t_rows else "<tr><td colspan='4'>لا توجد صفقات حالياً</td></tr>"}</table>
        </div>
        <div class="box">
            <h4 style="color:#848e9c">📡 رادار السوق</h4>
            <table><tr><th>الوقت</th><th>العملة</th><th>السكور</th><th>السعر</th></tr>{r_rows}</table>
        </div>
    </body></html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_engine())
