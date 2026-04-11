import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime, timedelta

app = Flask(__name__)

# --- الإعدادات ---
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
TAKE_PROFIT = 5.0
STOP_LOSS = -5.0

status_indicators = {"db": "🔴", "exchange": "🔴", "server": "🟢"}

def get_db_connection():
    try:
        conn = psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=5)
        status_indicators["db"] = "🟢"
        return conn
    except:
        status_indicators["db"] = "🔴"
        return None

def execute_close_logic(symbol, exit_price, reason="Auto"):
    conn = get_db_connection()
    if not conn: return
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (symbol,))
        trade = cur.fetchone()
        if trade:
            inv = float(trade['investment'] or 0)
            ent = float(trade['entry_price'] or 1)
            pnl = ((float(exit_price) - ent) / ent) * inv
            # تخزين الوقت بنص ثابت لتجنب مشاكل التنسيق لاحقاً
            cur.execute("INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) VALUES (%s, %s, %s, %s, %s, %s)", 
                        (symbol, ent, float(exit_price), pnl, reason, datetime.now()))
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
            conn.commit()
        cur.close(); conn.close()
    except:
        if conn: conn.close()

@app.route('/close/<path:symbol>', methods=['POST'])
def manual_close(symbol):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute("SELECT current_price FROM trades WHERE symbol = %s", (symbol,))
            res = cur.fetchone()
            if res: execute_close_logic(symbol, res['current_price'], "Manual")
            cur.close(); conn.close()
        except:
            if conn: conn.close()
    return redirect(url_for('index'))

@app.route('/')
def index():
    conn = get_db_connection()
    active_trades, closed_history = [], []
    realized_24h, floating, balance = 0.0, 0.0, 0.0
    
    if conn:
        try:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
            active_trades = cur.fetchall()
            cur.execute("SELECT * FROM closed_trades ORDER BY close_time DESC LIMIT 10")
            closed_history = cur.fetchall()
            cur.execute("SELECT pnl FROM closed_trades WHERE close_time > %s", (datetime.now() - timedelta(hours=24),))
            realized_24h = sum(float(c[0]) for c in cur.fetchall())
            cur.execute("SELECT balance FROM wallet WHERE id = 1")
            row = cur.fetchone()
            balance = float(row[0]) if row else 0.0
            floating = sum(((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment']) for t in active_trades)
            cur.close(); conn.close()
        except:
            if conn: conn.close()

    return render_template_string("""
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 5px; margin: 0; }
        .status { background: #1e2329; padding: 5px; font-size: 10px; display: flex; justify-content: space-around; border-bottom: 1px solid #333; }
        .card { background: #1e2329; padding: 15px; border-radius: 15px; border: 1px solid #f0b90b; margin: 10px; }
        .main-val { font-size: 35px; font-weight: bold; color: #f0b90b; }
        .stat-box { background: #161a1e; padding: 10px; border-radius: 10px; width: 45%; display: inline-block; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th { color: #848e9c; font-size: 12px; padding: 10px; }
        td { padding: 15px 5px; border-bottom: 1px solid #2b3139; }
        .up { color: #0ecb81; font-weight: bold; } .down { color: #f6465d; font-weight: bold; }
        .btn-x { background: #f6465d; color: white; border: none; padding: 10px 15px; border-radius: 5px; font-weight: bold; }
    </style></head><body>
        <div class="status">
            <span>Server: {{ st.server }}</span> <span>DB: {{ st.db }}</span> <span>Gate: {{ st.exchange }}</span>
        </div>
        <div class="card">
            <div class="main-val">${{ "%.2f"|format(balance + 1000 + floating) }}</div>
            <div style="margin-top:10px;">
                <div class="stat-box"><small>محقق 24h</small><br><span class="{{ 'up' if realized >= 0 else 'down' }}">${{ "%.2f"|format(realized) }}</span></div>
                <div class="stat-box"><small>عائم الآن</small><br><span class="{{ 'up' if floating >= 0 else 'down' }}">${{ "%.2f"|format(floating) }}</span></div>
            </div>
        </div>
        <h3 style="text-align:right; margin-right:15px; color:#f0b90b;">📍 صفقات مفتوحة</h3>
        <table>
            <tr><th>العملة</th><th>الربح</th><th>Max/Min</th><th></th></tr>
            {% for t in active %}
            {% set p = ((t.current_price - t.entry_price) / t.entry_price) * 100 %}
            <tr>
                <td style="text-align:right;"><b>{{ t.symbol.split('/')[0] }}</b><br><small style="color:#848e9c">${{ "%.4f"|format(t.entry_price) }}</small></td>
                <td class="{{ 'up' if p >= 0 else 'down' }}" style="font-size:22px;">{{ "%.2f"|format(p) }}%</td>
                <td><small class="up">+{{ "%.1f"|format(t.max_asc or 0) }}</small><br><small class="down">{{ "%.1f"|format(t.max_desc or 0) }}</small></td>
                <td><form action="/close/{{ t.symbol }}" method="post"><button type="submit" class="btn-x">X</button></form></td>
            </tr>
            {% endfor %}
        </table>
        <h3 style="text-align:right; margin-right:15px; color:#848e9c;">📜 السجل</h3>
        <table style="background:#111417; font-size:11px;">
            {% for h in history %}
            <tr>
                <td style="text-align:right;">{{ h.symbol.split('/')[0] }}</td>
                <td class="{{ 'up' if h.pnl >= 0 else 'down' }}">${{ "%.2f"|format(h.pnl) }}</td>
                <td>
                    {# حل مشكلة strftime: عرض الوقت كما هو إذا كان نصاً #}
                    {% if h.close_time is string %} {{ h.close_time[:5] }} 
                    {% elif h.close_time %} {{ h.close_time.strftime('%H:%M') }} 
                    {% endif %}
                </td>
                <td>{{ h.exit_reason }}</td>
            </tr>
            {% endfor %}
        </table>
    </body></html>
    """, st=status_indicators, balance=balance, floating=floating, realized=realized_24h, active=active_trades, history=closed_history)

async def monitor_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            status_indicators["exchange"] = "🟢"
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute("SELECT * FROM trades")
                for t in cur.fetchall():
                    sym = t['symbol']
                    if sym in tickers:
                        curr_p = float(tickers[sym]['last'])
                        p = ((curr_p - float(t['entry_price'])) / float(t['entry_price'])) * 100
                        m_a = max(float(t['max_asc'] or 0), p)
                        m_d = min(float(t['max_desc'] or 0), p)
                        cur.execute("UPDATE trades SET current_price=%s, max_asc=%s, max_desc=%s WHERE symbol=%s", (curr_p, m_a, m_d, sym))
                        if p >= TAKE_PROFIT: execute_close_logic(sym, curr_p, "TP +5%")
                        elif p <= STOP_LOSS: execute_close_logic(sym, curr_p, "SL -5%")
                conn.commit(); cur.close(); conn.close()
            await asyncio.sleep(8)
        except:
            status_indicators["exchange"] = "🔴"
            await asyncio.sleep(10)

if __name__ == "__main__":
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
