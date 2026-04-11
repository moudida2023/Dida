import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for, request
from datetime import datetime
import requests
import time

app = Flask(__name__)

# --- الإعدادات ---
INITIAL_CAPITAL = 1000.0
INVESTMENT_PER_TRADE = 50.0
ENTRY_SCORE_THRESHOLD = 60   
MAX_TRADES = 20              
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"

last_scan_results = []

def get_db_connection():
    try: return psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=15)
    except: return None

# --- دالة إغلاق صفقة معينة ---
def close_single_trade(symbol, exit_price, reason="Manual"):
    conn = get_db_connection()
    if not conn: return
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (str(symbol),))
        t = cur.fetchone()
        if t:
            pnl = ((float(exit_price) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment'])
            cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (str(symbol), float(t['entry_price']), float(exit_price), pnl, str(reason), datetime.now().strftime('%Y-%m-%d %H:%M')))
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (str(symbol),))
            conn.commit()
        cur.close(); conn.close()
    except: pass

# --- المسارات (Routes) ---

@app.route('/close/<symbol>', methods=['POST'])
def close_trade_route(symbol):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT current_price FROM trades WHERE symbol = %s", (symbol,))
        res = cur.fetchone()
        if res:
            close_single_trade(symbol, res['current_price'], "Manual Exit")
        cur.close(); conn.close()
    return redirect(url_for('index'))

@app.route('/close_all', methods=['POST'])
def close_all_route():
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT symbol, current_price FROM trades")
        all_t = cur.fetchall()
        cur.close(); conn.close()
        for t in all_t:
            close_single_trade(t['symbol'], t['current_price'], "Panic Close All")
    return redirect(url_for('index'))

@app.route('/')
def index():
    conn = get_db_connection()
    active_trades = []
    net_val = INITIAL_CAPITAL
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        active_trades = cur.fetchall()
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        res_w = cur.fetchone()
        realized = float(res_w[0]) if res_w else 0.0
        floating = sum(((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment']) for t in active_trades)
        net_val = INITIAL_CAPITAL + realized + floating
        cur.close(); conn.close()

    return render_template_string("""
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="20">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; margin: 0; }
        .card { background: #1e2329; padding: 15px; border-radius: 12px; border: 1px solid #f0b90b; margin-bottom: 20px; }
        .btn-panic { background: #f6465d; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-weight: bold; width: 100%; margin-bottom: 20px; }
        .btn-close { background: #474d57; color: #f6465d; border: 1px solid #f6465d; padding: 2px 8px; border-radius: 4px; cursor: pointer; font-size: 10px; }
        .btn-close:hover { background: #f6465d; color: white; }
        table { width: 100%; border-collapse: collapse; font-size: 10px; }
        th, td { padding: 8px; border: 1px solid #2b3139; }
        .up { color: #0ecb81; } .down { color: #f6465d; }
    </style></head><body>
        <div class="card">
            <small>صافي المحفظة</small><h2>${{ "%.2f"|format(net) }}</h2>
            <form action="/close_all" method="post" onsubmit="return confirm('إغلاق كل الصفقات فوراً؟')">
                <button type="submit" class="btn-panic">🛑 إغلاق كلي فوري</button>
            </form>
        </div>

        <h4 style="color:#f0b90b; text-align:right;">📍 صفقات حية</h4>
        <table>
            <tr><th>العملة</th><th>الربح %</th><th>أعلى/أدنى</th><th>إجراء</th></tr>
            {% for t in active %}
            {% set p = ((t.current_price - t.entry_price) / t.entry_price) * 100 %}
            <tr>
                <td><b>{{ t.symbol.split('/')[0] }}</b></td>
                <td class="{{ 'up' if p >= 0 else 'down' }}">{{ "%.2f"|format(p) }}%</td>
                <td><small class="up">+{{ "%.1f"|format(t.max_asc or 0) }}</small> / <small class="down">{{ "%.1f"|format(t.max_desc or 0) }}</small></td>
                <td>
                    <form action="/close/{{ t.symbol }}" method="post" style="display:inline;">
                        <button type="submit" class="btn-close">X إغلاق</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>
    </body></html>
    """, net=net_val, active=active_trades)

# --- محرك التداول --- (نفس المحرك السابق مع الحفاظ على تحديث max_asc/max_desc)
async def trading_engine():
    global last_scan_results
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute("SELECT * FROM trades")
                active_t = cur.fetchall()
                for t in active_t:
                    if t['symbol'] in tickers:
                        curr_p = float(tickers[t['symbol']]['last'])
                        pnl = ((curr_p - float(t['entry_price'])) / float(t['entry_price'])) * 100
                        m_a = max(float(t['max_asc'] or 0), pnl)
                        m_d = min(float(t['max_desc'] or 0), pnl)
                        cur.execute("UPDATE trades SET current_price=%s, max_asc=%s, max_desc=%s WHERE symbol=%s", (curr_p, m_a, m_d, t['symbol']))
                conn.commit(); cur.close(); conn.close()
            await asyncio.sleep(15)
        except: await asyncio.sleep(15)

if __name__ == "__main__":
    threading.Thread(target=lambda: asyncio.run(trading_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
