import os
import threading
import asyncio
import ccxt.pro as ccxt
import psycopg2
from psycopg2 import extras
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

app = Flask(__name__)

# --- 1. إعدادات قاعدة البيانات (الرابط الداخلي والمنفذ 5432) ---
INTERNAL_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a/trading_bot_db_wv1h"
DB_URL = os.environ.get('DATABASE_URL', INTERNAL_URL)

def get_db_connection():
    try:
        # تصحيح الرابط تلقائياً ليتوافق مع مكتبة psycopg2
        url = DB_URL.replace("postgres://", "postgresql://", 1) if DB_URL.startswith("postgres://") else DB_URL
        # الاتصال عبر المنفذ 5432 داخلياً
        return psycopg2.connect(url, connect_timeout=5)
    except Exception as e:
        print(f"❌ خطأ في الاتصال بالقاعدة: {e}")
        return None

# --- 2. محرك الرصد والتداول (تحديث الأسعار والاستعادة) ---
async def trading_engine():
    # إنشاء الجداول إذا لم تكن موجودة
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS trades 
            (symbol TEXT PRIMARY KEY, entry_price DOUBLE PRECISION, current_price DOUBLE PRECISION, investment DOUBLE PRECISION, score INTEGER, open_time TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS closed_trades 
            (id SERIAL PRIMARY KEY, symbol TEXT, entry_price DOUBLE PRECISION, exit_price DOUBLE PRECISION, pnl DOUBLE PRECISION, close_time TEXT)''')
        conn.commit()
        cur.close(); conn.close()

    exchange = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            # استعادة الصفقات المفتوحة من قاعدة البيانات وجوباً
            conn = get_db_connection()
            active_db_trades = {}
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute("SELECT symbol, entry_price FROM trades")
                active_db_trades = {r['symbol']: r['entry_price'] for r in cur.fetchall()}
                cur.close(); conn.close()

            # جلب أسعار السوق الحية
            tickers = await exchange.fetch_tickers()
            symbols = sorted([s for s in tickers if '/USDT' in s], 
                            key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:500]
            
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                current_count = len(active_db_trades)
                for s in symbols:
                    price = float(tickers[s]['last'])
                    change = float(tickers[s].get('percentage', 0))
                    
                    if s in active_db_trades:
                        # تحديث السعر الحالي فقط (سعر الدخول يبقى ثابتاً في القاعدة)
                        cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (price, s))
                    else:
                        # شرط الدخول (تغير > 1.8% والحد الأقصى 20 صفقة)
                        if change > 1.8 and current_count < 20:
                            entry_t = datetime.now().strftime('%H:%M:%S')
                            cur.execute("""INSERT INTO trades (symbol, entry_price, current_price, investment, score, open_time) 
                                           VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""", 
                                        (s, price, price, 50.0, 85, entry_t))
                            conn.commit()
                            current_count += 1
                conn.commit()
                cur.close(); conn.close()
            await asyncio.sleep(20)
        except: await asyncio.sleep(20)

# --- 3. الواجهة الرسومية (v260) ---
HTML = """
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
<style>
    body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 20px; }
    .header { color: #f0b90b; margin-bottom: 20px; }
    .stats { display: flex; justify-content: center; gap: 15px; margin-bottom: 25px; }
    .card { background: #1e2329; padding: 15px; border-radius: 10px; border-bottom: 4px solid #f0b90b; min-width: 160px; }
    table { width: 100%; max-width: 900px; margin: auto; border-collapse: collapse; background: #1e2329; border-radius: 8px; overflow: hidden; }
    th { background: #2b3139; padding: 15px; color: #848e9c; }
    td { padding: 15px; border-bottom: 1px solid #2b3139; }
    .up { color: #0ecb81; } .down { color: #f6465d; }
    .btn { background: #f6465d; color: white; padding: 7px 15px; border-radius: 5px; text-decoration: none; font-weight: bold; }
</style></head><body>
    <h1 class="header">💎 رادار v260 النهائي</h1>
    <div class="stats">
        <div class="card">الصافي الكلي<br><b class="{{ 'up' if (cp + fp) >= 0 else 'down' }}" style="font-size:22px;">${{ "%.2f"|format(cp + fp) }}</b></div>
        <div class="card">المفتوحة<br><b style="font-size:22px;">{{ ot|length }} / 20</b></div>
    </div>
    <table>
        <tr><th>العملة</th><th>سعر الدخول</th><th>السعر الحالي</th><th>الربح اللحظي</th><th>تحكم</th></tr>
        {% for t in ot %}
        {% set pnl = ((t.current_price - t.entry_price) / t.entry_price) * t.investment %}
        <tr>
            <td><b style="font-size:16px;">{{ t.symbol }}</b></td>
            <td class="up">${{ "%.4f"|format(t.entry_price) }}<br><small style="color:#848e9c;">{{ t.open_time }}</small></td>
            <td style="color:#f0b90b; font-weight:bold;">${{ "%.4f"|format(t.current_price) }}</td>
            <td class="{{ 'up' if pnl >= 0 else 'down' }}" style="font-weight:bold;">${{ "%.2f"|format(pnl) }}</td>
            <td><a href="/close/{{ t.symbol }}" class="btn">إغلاق</a></td>
        </tr>
        {% endfor %}
    </table>
</body></html>
"""

@app.route('/')
def index():
    open_trades, closed_pnl, floating_pnl = [], 0.0, 0.0
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
            open_trades = cur.fetchall()
            cur.execute("SELECT SUM(pnl) FROM closed_trades")
            res = cur.fetchone()
            closed_pnl = float(res[0]) if res and res[0] else 0.0
            cur.close(); conn.close()
            for t in open_trades:
                floating_pnl += ((t['current_price'] - t['entry_price']) / t['entry_price']) * t['investment']
    except: pass
    return render_template_string(HTML, ot=open_trades, cp=closed_pnl, fp=floating_pnl)

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
