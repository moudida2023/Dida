import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime, timedelta

app = Flask(__name__)

# --- الإعدادات الثابتة ---
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
TAKE_PROFIT = 5.0
STOP_LOSS = -5.0
INITIAL_CAPITAL = 1000.0

# مؤشرات الحالة
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
            inv = float(trade['investment'])
            ent = float(trade['entry_price'])
            pnl = ((float(exit_price) - ent) / ent) * inv
            cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                           VALUES (%s, %s, %s, %s, %s, %s)""", 
                        (symbol, ent, float(exit_price), pnl, reason, datetime.now()))
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
    active_trades, closed_24h = [], []
    realized_24h, floating, balance = 0.0, 0.0, 0.0
    
    if conn:
        try:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            # صفقات نشطة
            cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
            active_trades = cur.fetchall()
            # صفقات مغلقة آخر 24 ساعة
            cur.execute("SELECT * FROM closed_trades WHERE close_time > %s ORDER BY close_time DESC", (datetime.now() - timedelta(hours=24),))
            closed_24h = cur.fetchall()
            realized_24h = sum(float(c['pnl']) for c in closed_24h)
            # المحفظة والربح العائم
            cur.execute("SELECT balance FROM wallet WHERE id = 1")
            row = cur.fetchone()
            balance = float(row[0]) if row else 0.0
            floating = sum(((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment']) for t in active_trades)
            cur.close(); conn.close()
        except: pass

    # قالب HTML نظيف لتجنب SyntaxError
    html_template = """
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; margin: 0; }
        .status-bar { background: #1e2329; padding: 5px; font-size: 11px; border-bottom: 1px solid #2b3139; display: flex; justify-content: space-around; }
        .card { background: #1e2329; padding: 15px; border-radius: 12px; border: 1px solid #f0b90b; margin: 10px 0; }
        .stat-grid { display: flex; justify-content: space-around; margin-top: 15px; }
        .stat-box { background: #161a1e; padding: 8px; border-radius: 8px; width: 45%; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 12px 8px; border-bottom: 1px solid #2b3139; font-size: 14px; }
        .up { color: #0ecb81; font-weight: bold; } .down { color: #f6465d; font-weight: bold; }
        .section-title { text-align: right; color: #f0b90b; margin: 15px 5px 5px 0; border-right: 3px solid #f0b90b; padding-right: 10px; font-size: 16px; }
        .btn-close { background: #f6465d; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
    </style></head><body>
        <div class="status-bar">
            <span>سيرفر: {{ st.server }}</span> <span>قاعدة بيانات: {{ st.db }}</span> <span>Gate.io: {{ st.exchange }}</span>
        </div>
        <div class="card">
            <small style="color:#848e9c">رأس المال الكلي (الفعلي)</small>
            <div style="font-size: 30px; font-weight: bold; color: #f0b90b; margin: 5px 0;">${{ "%.2f"|format(balance + 1000 + floating) }}</div>
            <div class="stat-grid">
                <div class="stat-box"><small style="color:#848e9c">محقق 24h</small><br><span class="{{ 'up' if realized >= 0 else 'down' }}">${{ "%.2f"|format(realized) }}</span></div>
                <div class="stat-box"><small style="color:#848e9c">عائم الآن</small><br><span class="{{ 'up' if floating >= 0 else 'down' }}">${{ "%.2f"|format(floating) }}</span></div>
            </div>
        </div>
        <h4 class="section-title">📍 الصفقات المفتوحة ({{ active|length }})</h4>
        <table>
            {% for t in active %}
            {% set p = ((t.current_price - t.entry_price) / t.entry_price) * 100 %}
            <tr>
                <td style="text-align:right;"><b>{{ t.symbol.split('/')[0] }}</b><br><small style="color:#848e9c">{{ t.open_time }}</small></td>
                <td class="{{ 'up' if p >= 0 else 'down' }}" style="font-size:18px;">{{ "%.2f"|format(p) }}%</td>
                <td><form action="/close/{{ t.symbol }}" method="post"><button type="submit" class="btn-close">إغلاق</button></form></td>
            </tr>
            {% endfor %}
        </table>
        <h4 class="section-title">📜 أُغلقت مؤخراً (24h)</h4>
        <table>
            {% for c in closed %}
            <tr>
                <td style="text-align:right;">{{ c.symbol.split('/')[0] }}</td>
                <td class="{{ 'up' if c.pnl >= 0 else 'down' }}">${{ "%.2f"|format(c.pnl) }}</td>
                <td style="font-size:11px; color:#848e9c;">{{ c.exit_reason }}</td>
            </tr>
            {% endfor %}
        </table>
    </body></html>
    """
    return render_template_string(html_template, st=status_indicators, balance=balance, floating=floating, realized=realized_24h, active=active_trades, closed=closed_24h)

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
                        pnl = ((curr_p - float(t['entry_price'])) / float(t['entry_price'])) * 100
                        m_a = max(float(t['max_asc'] or 0), pnl)
                        m_d = min(float(t['max_desc'] or 0), pnl)
                        cur.execute("UPDATE trades SET current_price=%s, max_asc=%s, max_desc=%s WHERE symbol=%s", (curr_p, m_a, m_d, sym))
                        if pnl >= TAKE_PROFIT: execute_close_logic(sym, curr_p, "TP +5%")
                        elif pnl <= STOP_LOSS: execute_close_logic(sym, curr_p, "SL -5%")
