import os
import threading
import time
import asyncio
import ccxt.pro as ccxt
import psycopg2
from psycopg2 import extras
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime
import requests

app = Flask(__name__)

# --- 1. الإعدادات وقاعدة البيانات ---
DB_URL = os.environ.get('DATABASE_URL')
APP_URL = os.environ.get('APP_URL')

def get_db_connection():
    try:
        url = DB_URL.replace("postgres://", "postgresql://", 1) if DB_URL and "postgres://" in DB_URL else DB_URL
        return psycopg2.connect(url, sslmode='require', connect_timeout=10)
    except: return None

# --- 2. محرك التداول (سكور 80+) واستعادة البيانات ---
async def trading_engine():
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS trades 
            (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, investment REAL, score INTEGER, open_time TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS closed_trades 
            (id SERIAL PRIMARY KEY, symbol TEXT, pnl REAL, close_time TEXT)''')
        conn.commit()
        cur.close(); conn.close()

    exchange = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            symbols = [s for s in tickers if '/USDT' in s]
            
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                cur.execute("SELECT symbol FROM trades")
                active_on_db = [r[0] for r in cur.fetchall()]
                
                for sym in symbols[:60]:
                    price = tickers[sym]['last']
                    change = tickers[sym].get('percentage', 0)
                    current_score = 85 if change > 1.5 else 40
                    
                    if sym in active_on_db:
                        cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (price, sym))
                    elif current_score >= 80:
                        cur.execute("""INSERT INTO trades (symbol, entry_price, current_price, investment, score, open_time) 
                                       VALUES (%s, %s, %s, 50.0, %s, %s) 
                                       ON CONFLICT (symbol) DO NOTHING""", 
                                    (sym, price, price, current_score, datetime.now().strftime('%H:%M:%S')))
                conn.commit()
                cur.close(); conn.close()
            await asyncio.sleep(20)
        except: await asyncio.sleep(20)

# --- 3. نظام النبض الذاتي (Keep-Alive) ---
def keep_alive():
    time.sleep(30)
    while True:
        if APP_URL:
            try: requests.get(APP_URL, timeout=20)
            except: pass
        time.sleep(240)

# --- 4. التحكم في الصفقات (إغلاق يدوي) ---
@app.route('/close/<symbol>')
def close_trade(symbol):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (symbol,))
        trade = cur.fetchone()
        if trade:
            pnl = ((trade['current_price'] - trade['entry_price']) / trade['entry_price']) * trade['investment']
            cur.execute("INSERT INTO closed_trades (symbol, pnl, close_time) VALUES (%s, %s, %s)",
                        (trade['symbol'], pnl, datetime.now().strftime('%Y-%m-%d %H:%M')))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
        conn.commit()
        cur.close(); conn.close()
    return redirect(url_for('index'))

# --- 5. الواجهة الرسومية (تم إصلاح هيكل النص هنا) ---
@app.route('/')
def index():
    open_trades = []
    closed_pnl, floating_pnl = 0, 0
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades")
        open_trades = cur.fetchall()
        for t in open_trades:
            floating_pnl += ((t['current_price'] - t['entry_price']) / t['entry_price']) * t['investment']
        cur.execute("SELECT SUM(pnl) FROM closed_trades")
        closed_pnl = cur.fetchone()[0] or 0
        cur.close(); conn.close()
    except: pass

    total_net = closed_pnl + floating_pnl

    html = """
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; }
        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }
        .card { background: #1e2329; padding: 20px; border-radius: 12px; text-align: center; border-bottom: 4px solid #f0b90b; }
        .up { color: #0ecb81; } .down { color: #f6465d; }
        table { width: 100%; border-collapse: collapse; background: #1e2329; border-radius: 10px; }
        th, td { padding: 15px; border-bottom: 1px solid #2b3139; text-align: center; }
        .btn { background: #f6465d; color: white; text-decoration: none; padding: 6px 12px; border-radius: 4px; }
    </style></head><body>
        <h2 style="color:#f0b90b; text-align:center;">🚀 نظام المراقبة v175</h2>
        <div class="summary">
            <div class="card"><div>النتيجة الكلية</div><h2 class="{{ 'up' if tn >= 0 else 'down' }}">${{ "%.2f"|format(tn) }}</h2></div>
            <div class="card"><div>أرباح مغلقة</div><h2 class="up">${{ "%.2f"|format(cp) }}</h2></div>
            <div class="card"><div>ربح عائم</div><h2 class="{{ 'up' if fp >= 0 else 'down' }}">${{ "%.2f"|format(fp) }}</h2></div>
        </div>
        <table>
            <tr style="background:#2b3139;"><th>العملة</th><th>الدخول</th><th>الحالي</th><th>الربح $</th><th>تحكم</th></tr>
            {% for t in ot %}
            {% set val = ((t.current_price - t.entry_price) / t.entry_price) * t.investment %}
            <tr>
                <td><b>{{ t.symbol }}</b></td>
                <td>{{ "%.4f"|format(t.entry_price) }}</td>
                <td style="color:#f0b90b;">{{ "%.4f"|format(t.current_price) }}</td>
                <td class="{{ 'up' if val >= 0 else 'down' }}">{{ "%+.2f"|format(val) }} USDT</td>
                <td><a href="/close/{{ t.symbol }}" class="btn">إغلاق</a></td>
            </tr>
            {% endfor %}
        </table>
    </body></html>
    """
    return render_template_string(html, ot=open_trades, tn=total_net, cp=closed_pnl, fp=floating_pnl)

if __name__ == "__main__":
    threading.Thread(target=keep_alive, daemon=True).start()
    def run_engine():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(trading_engine())
    threading.Thread(target=run_engine, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
