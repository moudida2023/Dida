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

# --- 1. الإعدادات ---
# الرابط الذي زودتني به
DB_URL = os.environ.get('DATABASE_URL', "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h")
MAX_OPEN_TRADES = 20
INVESTMENT_PER_TRADE = 50.0

def get_db_connection():
    try:
        # تصحيح الرابط وجوباً ليتوافق مع Render و psycopg2
        fixed_url = DB_URL.replace("postgres://", "postgresql://", 1) if DB_URL.startswith("postgres://") else DB_URL
        conn = psycopg2.connect(fixed_url, sslmode='require')
        return conn
    except Exception as e:
        print(f"❌ DATABASE ERROR: {e}")
        return None

# --- 2. محرك التداول (الاستعادة والالتزام) ---
async def trading_engine():
    # التأكد من وجود الجداول
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute('''CREATE TABLE IF NOT EXISTS trades 
                (symbol TEXT PRIMARY KEY, entry_price DOUBLE PRECISION, current_price DOUBLE PRECISION, investment DOUBLE PRECISION, score INTEGER, open_time TEXT)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS closed_trades 
                (id SERIAL PRIMARY KEY, symbol TEXT, entry_price DOUBLE PRECISION, exit_price DOUBLE PRECISION, pnl DOUBLE PRECISION, close_time TEXT)''')
            conn.commit()
            cur.close(); conn.close()
        except: pass

    exchange = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            # 1. جلب البيانات من الداتابيز (الاستعادة)
            conn = get_db_connection()
            active_db_trades = {}
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute("SELECT symbol, entry_price FROM trades")
                active_db_trades = {r['symbol']: r['entry_price'] for r in cur.fetchall()}
                cur.close(); conn.close()

            # 2. جلب أسعار السوق
            tickers = await exchange.fetch_tickers()
            symbols = sorted([s for s in tickers if '/USDT' in s], 
                            key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:500]
            
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                count = len(active_db_trades)
                for s in symbols:
                    price = float(tickers[s]['last'])
                    change = float(tickers[s].get('percentage', 0))
                    
                    if s in active_db_trades:
                        cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (price, s))
                    else:
                        # شروط السكور (70 رصد / 85 دخول)
                        score = 85 if change > 1.8 else (70 if change > 0.8 else 0)
                        if score >= 85 and count < MAX_OPEN_TRADES:
                            entry_time = datetime.now().strftime('%H:%M:%S')
                            cur.execute("""INSERT INTO trades (symbol, entry_price, current_price, investment, score, open_time) 
                                           VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""", 
                                        (s, price, price, INVESTMENT_PER_TRADE, score, entry_time))
                            conn.commit()
                            count += 1
                conn.commit()
                cur.close(); conn.close()
            await asyncio.sleep(20)
        except: await asyncio.sleep(20)

# --- 3. الواجهة الرسومية ---
@app.route('/')
def index():
    try:
        conn = get_db_connection()
        if not conn: return "<h1>جاري الاتصال بقاعدة البيانات... انتظر ثواني</h1>", 500
        
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades")
        open_trades = cur.fetchall()
        
        cur.execute("SELECT SUM(pnl) FROM closed_trades")
        closed_pnl = cur.fetchone()[0] or 0.0
        cur.close(); conn.close()
        
        floating_pnl = sum([((t['current_price'] - t['entry_price']) / t['entry_price']) * t['investment'] for t in open_trades])
        
        html = """
        <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; }
            .stat { background: #1e2329; padding: 20px; border-radius: 10px; display: inline-block; margin: 10px; border-bottom: 3px solid #f0b90b; }
            table { width: 90%; margin: 20px auto; border-collapse: collapse; background: #1e2329; }
            th, td { padding: 12px; border-bottom: 1px solid #2b3139; }
            .up { color: #0ecb81; } .down { color: #f6465d; }
            .btn { background: #f6465d; color: white; padding: 5px 15px; border-radius: 5px; text-decoration: none; }
        </style></head><body>
            <h2>🛡️ نظام الاستعادة الصارم v245</h2>
            <div class="stat">الربح الصافي: <b class="up">${{ "%.2f"|format(closed_pnl + floating_pnl) }}</b></div>
            <div class="stat">مفتوح: <b>{{ ot|length }} / 20</b></div>
            <table>
                <tr><th>العملة</th><th>الدخول (من DB)</th><th>السعر الحالي</th><th>الربح</th><th>تحكم</th></tr>
                {% for t in ot %}
                {% set p = ((t.current_price - t.entry_price) / t.entry_price) * t.investment %}
                <tr>
                    <td><b>{{ t.symbol }}</b></td>
                    <td>${{ "%.4f"|format(t.entry_price) }}<br><small>{{ t.open_time }}</small></td>
                    <td style="color:#f0b90b;">${{ "%.4f"|format(t.current_price) }}</td>
                    <td class="{{ 'up' if p >= 0 else 'down' }}">${{ "%.2f"|format(p) }}</td>
                    <td><a href="/close/{{ t.symbol }}" class="btn">إغلاق</a></td>
                </tr>
                {% endfor %}
            </table>
        </body></html>
        """
        return render_template_string(html, ot=open_trades, total=(closed_pnl + floating_pnl))
    except Exception as e:
        return f"<h1>خطأ في العرض: {e}</h1>", 500

@app.route('/close/<symbol>')
def close_trade(symbol):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (symbol,))
        t = cur.fetchone()
        if t:
            pnl = ((t['current_price'] - t['entry_price']) / t['entry_price']) * t['investment']
            cur.execute("INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, close_time) VALUES (%s,%s,%s,%s,%s)",
                        (t['symbol'], t['entry_price'], t['current_price'], pnl, datetime.now().strftime('%Y-%m-%d %H:%M')))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
            conn.commit()
        cur.close(); conn.close()
    return redirect(url_for('index'))

if __name__ == "__main__":
    t = threading.Thread(target=lambda: asyncio.run(trading_engine()))
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
