import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

app = Flask(__name__)

# --- الإعدادات الثابتة ---
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
TAKE_PROFIT = 5.0
STOP_LOSS = -5.0
INITIAL_CAPITAL = 1000.0

def get_db_connection():
    try:
        return psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=15)
    except:
        return None

def execute_close_logic(symbol, exit_price, reason="Auto"):
    conn = get_db_connection()
    if not conn: return
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (symbol,))
        trade = cur.fetchone()
        if trade:
            investment = float(trade['investment'])
            entry_p = float(trade['entry_price'])
            pnl = ((float(exit_price) - entry_p) / entry_p) * investment
            cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                           VALUES (%s, %s, %s, %s, %s, %s)""", 
                        (symbol, entry_p, float(exit_price), pnl, reason, datetime.now().strftime('%H:%M')))
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
            conn.commit()
        cur.close(); conn.close()
    except: pass

@app.route('/close/<path:symbol>', methods=['POST'])
def manual_close(symbol):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT current_price FROM trades WHERE symbol = %s", (symbol,))
        res = cur.fetchone()
        if res: execute_close_logic(symbol, res['current_price'], "Manual")
        cur.close(); conn.close()
    return redirect(url_for('index'))

@app.route('/')
def index():
    conn = get_db_connection()
    active_trades = []
    balance = 0.0
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        active_trades = cur.fetchall()
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        row = cur.fetchone()
        balance = float(row[0]) if row else 0.0
        cur.close(); conn.close()

    return render_template_string("""
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; }
        .card { background: #1e2329; padding: 20px; border-radius: 15px; border: 2px solid #f0b90b; margin-bottom: 20px; }
        .val { font-size: 40px; font-weight: bold; color: #f0b90b; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { padding: 15px; border-bottom: 1px solid #2b3139; font-size: 20px; font-weight: bold; }
        .up { color: #0ecb81; } .down { color: #f6465d; }
    </style></head><body>
        <div class="card">
            <div style="color:#848e9c">الرصيد الكلي</div>
            <div class="val">${{ "%.2f"|format(balance + 1000) }}</div>
            <div style="margin-top:10px;"><span class="up">TP: +5%</span> | <span class="down">SL: -5%</span></div>
        </div>
        <h3 style="text-align:right; color:#f0b90b;">📍 الصفقات الحالية</h3>
        <table>
            <tr><th>العملة</th><th>الربح</th><th>أعلى/أدنى</th><th>تحكم</th></tr>
            {% for t in active_trades %}
            {% set p = ((t.current_price - t.entry_price) / t.entry_price) * 100 %}
            <tr>
                <td>{{ t.symbol.split('/')[0] }}</td>
                <td class="{{ 'up' if p >= 0 else 'down' }}">{{ "%.2f"|format(p) }}%</td>
                <td style="font-size:14px;">
                    <span class="up">+{{ "%.1f"|format(t.max_asc or 0) }}%</span><br>
                    <span class="down">{{ "%.1f"|format(t.max_desc or 0) }}%</span>
                </td>
                <td>
                    <form action="/close/{{ t.symbol }}" method="post">
                        <button type="submit" style="background:#f6465d; color:white; border:none; padding:10px; border-radius:5px; cursor:pointer;">إغلاق</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>
    </body></html>
    """, balance=balance, active_trades=active_trades)

async def monitor_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute("SELECT * FROM trades")
                for t in cur.fetchall():
                    sym = t['symbol']
                    if sym in tickers:
                        curr_p = float(tickers[sym]['last'])
                        pnl = ((curr_p - float(t['entry_price'])) / float(t['entry_price'])) * 100
                        m_a = max(float(t['max_asc'] or 0), pnl)
                        m_d = min(float(t['max_desc'] or 0), pnl)
                        cur.execute("UPDATE trades SET current_price=%s, max_asc=%s, max_desc=%s WHERE symbol=%s", (curr_p, m_a, m_d, sym))
                        if pnl >= TAKE_PROFIT: execute_close_logic(sym, curr_p, "TP +5%")
                        elif pnl <= STOP_LOSS: execute_close_logic(sym, curr_p, "SL -5%")
                conn.commit(); cur.close(); conn.close()
            await asyncio.sleep(10)
        except: await asyncio.sleep(10)

if __name__ == "__main__":
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
