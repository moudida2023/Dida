import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

app = Flask(__name__)

# --- إعدادات الاتصال ---
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
exchange_status = "🔴"

def get_db_connection():
    try:
        return psycopg2.connect(DB_URL, sslmode='require', connect_timeout=10)
    except:
        return None

# --- محرك التداول ---
async def trading_engine():
    global exchange_status
    exchange = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            await exchange.load_markets()
            exchange_status = "🟢"
            
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                # إنشاء الجداول إذا نقصت
                cur.execute('''CREATE TABLE IF NOT EXISTS trades 
                    (symbol TEXT PRIMARY KEY, entry_price DOUBLE PRECISION, current_price DOUBLE PRECISION, 
                     tp_price DOUBLE PRECISION, sl_price DOUBLE PRECISION, investment DOUBLE PRECISION, open_time TEXT)''')
                cur.execute('''CREATE TABLE IF NOT EXISTS closed_trades 
                    (id SERIAL PRIMARY KEY, symbol TEXT, pnl DOUBLE PRECISION, exit_reason TEXT, close_time TEXT)''')
                
                # تحديث الأسعار وفحص الأهداف
                cur.execute("SELECT * FROM trades")
                active_trades = cur.fetchall()
                tickers = await exchange.fetch_tickers()
                
                for t in active_trades:
                    sym = t['symbol']
                    if sym in tickers:
                        curr_p = float(tickers[sym]['last'])
                        # فحص جني الأرباح أو وقف الخسارة آلياً
                        reason = ""
                        if curr_p >= t['tp_price']: reason = "🎯 جني أرباح"
                        elif curr_p <= t['sl_price']: reason = "🛑 وقف خسارة"
                        
                        if reason:
                            pnl = ((curr_p - t['entry_price']) / t['entry_price']) * 1000
                            cur.execute("INSERT INTO closed_trades (symbol, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s)",
                                        (sym, pnl, reason, datetime.now().strftime('%H:%M:%S')))
                            cur.execute("DELETE FROM trades WHERE symbol = %s", (sym,))
                        else:
                            cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (curr_p, sym))
                
                conn.commit()
                cur.close(); conn.close()
            await asyncio.sleep(20)
        except:
            exchange_status = "🔴"
            await asyncio.sleep(20)

# --- الواجهة الرسومية ---
HTML_TEMPLATE = """
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
<style>
    body { background: #0b0e11; color: white; font-family: 'Segoe UI', sans-serif; text-align: center; margin: 0; padding: 20px; }
    .status-bar { display: flex; justify-content: center; gap: 20px; margin-bottom: 30px; }
    .status-item { background: #1e2329; padding: 10px 20px; border-radius: 50px; border: 1px solid #2b3139; font-size: 14px; }
    .card { background: #1e2329; border-radius: 12px; padding: 20px; margin-bottom: 20px; border-bottom: 4px solid #f0b90b; }
    table { width: 100%; border-collapse: collapse; margin-top: 10px; background: #1e2329; }
    th { background: #2b3139; color: #848e9c; padding: 12px; font-size: 12px; }
    td { padding: 12px; border-bottom: 1px solid #2b3139; font-size: 14px; }
    .up { color: #0ecb81; } .down { color: #f6465d; }
    .btn-close { background: #f6465d; color: white; padding: 5px 10px; border-radius: 4px; text-decoration: none; font-size: 11px; }
</style></head><body>

    <div class="status-bar">
        <div class="status-item">البورصة: {{ s_ex }}</div>
        <div class="status-item">القاعدة: {{ s_db }}</div>
        <div class="status-item">الموقع: 🟢 متصل</div>
    </div>

    <div class="card">
        <h3>📊 الصفقات المفتوحة</h3>
        <table>
            <tr><th>العملة</th><th>الدخول</th><th>الحالي</th><th>وقف الخسارة</th><th>جني الأرباح</th><th>النتيجة ($)</th><th>تحكم</th></tr>
            {% for t in ot %}
            {% set pnl = ((t.current_price - t.entry_price) / t.entry_price) * 1000 %}
            <tr>
                <td><b>{{ t.symbol }}</b><br><small>{{ t.open_time }}</small></td>
                <td>${{ t.entry_price }}</td>
                <td style="color:#f0b90b;">${{ t.current_price }}</td>
                <td class="down">${{ t.sl_price }}</td>
                <td class="up">${{ t.tp_price }}</td>
                <td class="{{ 'up' if pnl >= 0 else 'down' }}">${{ "%.2f"|format(pnl) }}</td>
                <td><a href="/manual_close/{{ t.symbol }}" class="btn-close">إغلاق يدوي</a></td>
            </tr>
            {% endfor %}
        </table>
    </div>

    <div class="card">
        <h3>📜 سجل الصفقات المغلقة</h3>
        <table>
            <tr><th>العملة</th><th>النتيجة النهائية</th><th>طريقة الإغلاق</th><th>التوقيت</th></tr>
            {% for c in ct %}
            <tr><td>{{ c.symbol }}</td><td class="{{ 'up' if c.pnl >= 0 else 'down' }}">${{ "%.2f"|format(c.pnl) }}</td><td>{{ c.exit_reason }}</td><td>{{ c.close_time }}</td></tr>
            {% endfor %}
        </table>
    </div>
</body></html>
"""

@app.route('/')
def index():
    conn = get_db_connection()
    db_ok = "🟢" if conn else "🔴"
    ot, ct = [], []
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades")
        ot = cur.fetchall()
        cur.execute("SELECT * FROM closed_trades ORDER BY id DESC LIMIT 10")
        ct = cur.fetchall()
        cur.close(); conn.close()
    return render_template_string(HTML_TEMPLATE, s_db=db_ok, s_ex=exchange_status, ot=ot, ct=ct)

@app.route('/manual_close/<symbol>')
def manual_close(symbol):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (symbol,))
        t = cur.fetchone()
        if t:
            pnl = ((t['current_price'] - t['entry_price']) / t['entry_price']) * 1000
            cur.execute("INSERT INTO closed_trades (symbol, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s)",
                        (symbol, pnl, "👤 يدوي", datetime.now().strftime('%H:%M:%S')))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
            conn.commit()
        cur.close(); conn.close()
    return redirect(url_for('index'))

if __name__ == "__main__":
    t = threading.Thread(target=lambda: asyncio.run(trading_engine()))
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
