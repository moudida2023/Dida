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
        url = str(DB_URL).strip()
        conn = psycopg2.connect(url, sslmode='require', connect_timeout=10)
        return conn
    except Exception as e:
        print(f"❌ DB connection failed: {e}")
        return None

def close_position(symbol, exit_price, reason):
    conn = get_db_connection()
    if conn is None: return False
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (str(symbol),))
        trade = cur.fetchone()
        if trade:
            pnl = ((float(exit_price) - trade['entry_price']) / trade['entry_price']) * trade['investment']
            cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (symbol, trade['entry_price'], float(exit_price), pnl, reason, datetime.now().strftime('%Y-%m-%d %H:%M')))
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
            conn.commit()
        cur.close(); conn.close()
        return True
    except Exception as e:
        print(f"❌ Close Error: {e}")
        return False

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
                cur.execute("SELECT * FROM trades")
                active_trades = cur.fetchall()
                tickers = await exchange.fetch_tickers()
                
                for t in active_trades:
                    sym = t['symbol']
                    if sym in tickers:
                        curr_p = float(tickers[sym]['last'])
                        if curr_p >= t['tp_price']: close_position(sym, curr_p, "🎯 جني أرباح")
                        elif curr_p <= t['sl_price']: close_position(sym, curr_p, "🛑 وقف خسارة")
                        else: cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (curr_p, sym))
                conn.commit()
                cur.close(); conn.close()
            await asyncio.sleep(15)
        except Exception as e:
            exchange_status = "🔴"
            await asyncio.sleep(20)

# --- واجهة الويب v500 ---
@app.route('/')
def index():
    conn = get_db_connection()
    if conn is None: return "<h3>⚠️ فشل الاتصال بالقاعدة</h3>", 500
    
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        ot = cur.fetchall()
        cur.execute("SELECT * FROM closed_trades ORDER BY id DESC LIMIT 10")
        ct = cur.fetchall()
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        res = cur.fetchone()
        balance = res[0] if res else 0.0
        cur.close(); conn.close()
        
        return render_template_string("""
        <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; }
            .card { background: #1e2329; padding: 15px; border-radius: 10px; margin-bottom: 20px; border-bottom: 4px solid #f0b90b; }
            table { width: 100%; border-collapse: collapse; background: #1e2329; margin-top: 10px; }
            th, td { padding: 8px; border: 1px solid #2b3139; font-size: 12px; }
            th { background: #2b3139; color: #848e9c; }
            .up { color: #0ecb81; } .down { color: #f6465d; }
            .btn { background: #f6465d; color: white; padding: 4px 8px; border-radius: 4px; text-decoration: none; }
        </style></head><body>
            <div class="card">
                <h2 style="margin:5px;">💰 المحفظة: ${{ "%.2f"|format(balance) }}</h2>
                <small>البورصة: {{ s_ex }} | القاعدة: 🟢</small>
            </div>

            <h3>📍 الصفقات المفتوحة</h3>
            <table>
                <tr>
                    <th>العملة</th>
                    <th>الدخول</th>
                    <th>الحالي</th>
                    <th style="color:#0ecb81;">جني الأرباح</th>
                    <th style="color:#f6465d;">وقف الخسارة</th>
                    <th>الربح ($)</th>
                    <th>إجراء</th>
                </tr>
                {% for t in ot %}
                {% set pnl = ((t.current_price - t.entry_price) / t.entry_price) * t.investment %}
                <tr>
                    <td><b>{{ t.symbol }}</b></td>
                    <td>{{ t.entry_price }}</td>
                    <td style="color:#f0b90b;">{{ t.current_price }}</td>
                    <td class="up">{{ t.tp_price }}</td>
                    <td class="down">{{ t.sl_price }}</td>
                    <td class="{{ 'up' if pnl >= 0 else 'down' }}">${{ "%.2f"|format(pnl) }}</td>
                    <td><a href="/manual_close/{{ t.symbol }}" class="btn">إغلاق</a></td>
                </tr>
                {% endfor %}
            </table>

            <h3>📜 السجل (آخر 10 صفقات)</h3>
            <table>
                <tr><th>العملة</th><th>النتيجة</th><th>السبب</th><th>التوقيت</th></tr>
                {% for c in ct %}
                <tr><td>{{ c.symbol }}</td><td class="{{ 'up' if c.pnl >= 0 else 'down' }}">${{ "%.2f"|format(c.pnl) }}</td><td>{{ c.exit_reason }}</td><td>{{ c.close_time }}</td></tr>
                {% endfor %}
            </table>
        </body></html>
        """, s_ex=exchange_status, ot=ot, ct=ct, balance=balance)
    except Exception as e:
        return f"<h3>⚠️ خطأ في العرض: {e}</h3>", 500

@app.route('/manual_close/<symbol>')
def manual_close_route(symbol):
    try:
        import ccxt
        price = ccxt.gateio().fetch_ticker(symbol)['last']
        close_position(symbol, price, "👤 يدوي")
    except: pass
    return redirect(url_for('index'))

if __name__ == "__main__":
    t = threading.Thread(target=lambda: asyncio.run(trading_engine()))
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
