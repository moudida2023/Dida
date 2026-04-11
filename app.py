import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

app = Flask(__name__)

# --- الإعدادات المالية ---
INITIAL_CAPITAL = 1000.0
INVESTMENT_PER_TRADE = 50.0
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"

def get_db_connection():
    try:
        return psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=15)
    except:
        return None

def close_position(symbol, exit_price, reason):
    conn = get_db_connection()
    if not conn: return False
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
        return True
    except:
        if conn: conn.close()
        return False

@app.route('/')
def index():
    conn = get_db_connection()
    if not conn: return "DB Connection Error", 500
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        ot = cur.fetchall()
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        res_w = cur.fetchone()
        realized_pnl = float(res_w[0]) if res_w else 0.0
        cur.close(); conn.close()

        invested = len(ot) * INVESTMENT_PER_TRADE
        unused = (INITIAL_CAPITAL + realized_pnl) - invested
        floating = sum(((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment']) for t in ot)
        net = INITIAL_CAPITAL + realized_pnl + floating

        return render_template_string("""
        <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; margin: 0; }
            .card { background: #1e2329; padding: 15px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #f0b90b; }
            .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 15px; }
            .s-card { background: #1e2329; padding: 10px; border-radius: 8px; font-size: 12px; }
            .up { color: #0ecb81; } .down { color: #f6465d; }
            .btn-all { background: #f6465d; color: white; padding: 12px; border-radius: 8px; text-decoration: none; display: block; margin: 15px 0; font-weight: bold; border: 1px solid white; }
            table { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 10px; }
            th, td { padding: 8px; border: 1px solid #2b3139; text-align: center; }
            th { color: #848e9c; background: #2b3139; }
        </style></head><body>
            <div class="card">
                <small style="color:#848e9c;">صافي قيمة المحفظة</small><br>
                <b style="font-size:26px;" class="{{ 'up' if net_val >= 1000 else 'down' }}">${{ "%.2f"|format(net_val) }}</b>
            </div>
            
            <div class="stats">
                <div class="s-card">السيولة المتاحة<br><b style="color:#92a2b1;">${{ "%.2f"|format(un) }}</b></div>
                <div class="s-card">الربح العائم<br><b class="{{ 'up' if f_pnl >= 0 else 'down' }}">${{ "%.2f"|format(f_pnl) }}</b></div>
            </div>

            {% if trades_list|length > 0 %}
            <a href="/close_all" class="btn-all" onclick="return confirm('إغلاق الكل؟')">⚠️ تصفية جميع الصفقات</a>
            {% endif %}

            <h4 style="text-align:right; margin: 10px 5px;">📍 الصفقات النشطة ({{ trades_list|length }})</h4>
            <table>
                <tr>
                    <th>العملة</th>
                    <th>الدخول</th>
                    <th>الحالي</th>
                    <th>التغير (%)</th>
                    <th>الربح ($)</th>
                </tr>
                {% for t in trades_list %}
                {% set change_pct = ((t.current_price - t.entry_price) / t.entry_price) * 100 %}
                {% set pnl_usd = (change_pct / 100) * 50 %}
                <tr>
                    <td><b>{{ t.symbol }}</b></td>
                    <td>{{ t.entry_price }}</td>
                    <td style="color:#f0b90b;">{{ t.current_price }}</td>
                    <td class="{{ 'up' if change_pct >= 0 else 'down' }}">
                        {{ "+" if change_pct > 0 }}{{ "%.2f"|format(change_pct) }}%
                    </td>
                    <td class="{{ 'up' if pnl_usd >= 0 else 'down' }}">${{ "%.2f"|format(pnl_usd) }}</td>
                </tr>
                {% endfor %}
            </table>
        </body></html>
        """, inv=invested, un=unused, net_val=net, trades_list=ot, f_pnl=floating)
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/close_all')
def close_all_route():
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor(extras.DictCursor)
            cur.execute("SELECT symbol FROM trades")
            trades = cur.fetchall()
            cur.close(); conn.close()
            if trades:
                import ccxt as ccxt_sync
                ex = ccxt_sync.gateio()
                tickers = ex.fetch_tickers([str(t['symbol']) for t in trades])
                for t in trades:
                    s = str(t['symbol'])
                    if s in tickers:
                        close_position(s, float(tickers[s]['last']), "👤 تصفية كلية")
    except: pass
    return redirect(url_for('index'))

async def trading_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            await exchange.load_markets()
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(extras.DictCursor)
                cur.execute("SELECT * FROM trades")
                active = cur.fetchall()
                if active:
                    tickers = await exchange.fetch_tickers()
                    for t in active:
                        sym = str(t['symbol'])
                        if sym in tickers:
                            cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (float(tickers[sym]['last']), sym))
                conn.commit(); cur.close(); conn.close()
            await asyncio.sleep(20)
        except:
            await asyncio.sleep(20)

if __name__ == "__main__":
    t = threading.Thread(target=lambda: asyncio.run(trading_engine()))
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
