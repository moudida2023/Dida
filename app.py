import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime
import requests
import time

app = Flask(__name__)

# --- الإعدادات ---
INITIAL_CAPITAL = 1000.0
INVESTMENT_PER_TRADE = 50.0
# الرابط الخارجي الكامل مع SSL
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
RENDER_APP_URL = "https://dida-fvym.onrender.com"

def get_db_connection():
    try:
        # تحويل الرابط لنص صريح لضمان عدم حدوث خطأ النوع
        url = str(DB_URL).strip()
        return psycopg2.connect(url, sslmode='require', connect_timeout=15)
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return None

# وظيفة التنبيه الذاتي لمنع النوم
def keep_alive():
    while True:
        try:
            requests.get(RENDER_APP_URL, timeout=10)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔔 Self-Ping Sent: System Active")
        except:
            print("🔔 Self-Ping failed (No worries if server is rebooting)")
        time.sleep(600)

def close_position(symbol, exit_price, reason):
    conn = get_db_connection()
    if not conn: return False
    try:
        # تصحيح الخطأ: إضافة cursor_factory=
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
    except Exception as e:
        print(f"❌ Close Position Error: {e}")
        if conn: conn.close()
        return False

@app.route('/')
def index():
    conn = get_db_connection()
    if not conn: return "<h1>خطأ في الاتصال بقاعدة البيانات</h1>", 500
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
        <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="20">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; margin: 0; }
            .card { background: #1e2329; padding: 15px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #f0b90b; }
            .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 15px; }
            .s-card { background: #1e2329; padding: 10px; border-radius: 8px; font-size: 12px; }
            .up { color: #0ecb81; } .down { color: #f6465d; }
            .btn-all { background: #f6465d; color: white; padding: 12px; border-radius: 8px; text-decoration: none; display: block; margin: 15px 0; font-weight: bold; border: 1px solid white; }
            table { width: 100%; border-collapse: collapse; font-size: 11px; }
            th, td { padding: 8px; border: 1px solid #2b3139; }
        </style></head><body>
            <div class="card">
                <small>صافي القيمة الكلية (24/7 نشط)</small><br>
                <b style="font-size:26px;" class="{{ 'up' if net_val >= 1000 else 'down' }}">${{ "%.2f"|format(net_val) }}</b>
            </div>
            <div class="stats">
                <div class="s-card">المستعملة<br><b style="color:#f0b90b;">${{ "%.2f"|format(inv) }}</b></div>
                <div class="s-card">غير المستعملة<br><b style="color:#92a2b1;">${{ "%.2f"|format(un) }}</b></div>
            </div>
            {% if trades_list|length > 0 %}
            <a href="/close_all" class="btn-all" onclick="return confirm('إغلاق الكل؟')">⚠️ إغلاق كافة الصفقات</a>
            {% endif %}
            <h4>📍 صفقات مفتوحة ({{ trades_list|length }})</h4>
            <table>
                <tr><th>العملة</th><th>الحالي</th><th>الربح ($)</th></tr>
                {% for t in trades_list %}
                {% set p = ((t.current_price - t.entry_price) / t.entry_price) * 50 %}
                <tr><td>{{ t.symbol }}</td><td style="color:#f0b90b;">{{ t.current_price }}</td><td class="{{ 'up' if p >= 0 else 'down' }}">${{ "%.2f"|format(p) }}</td></tr>
                {% endfor %}
            </table>
        </body></html>
        """, inv=invested, un=unused, net_val=net, trades_list=ot)
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/close_all')
def close_all_route():
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
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
                        close_position(s, float(tickers[s]['last']), "👤 إغلاق كلي")
    except: pass
    return redirect(url_for('index'))

async def trading_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            await exchange.load_markets()
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
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
    # تشغيل نظام التنبيه الذاتي
    threading.Thread(target=keep_alive, daemon=True).start()
    # تشغيل محرك التداول
    threading.Thread(target=lambda: asyncio.run(trading_engine()), daemon=True).start()
    # تشغيل السيرفر
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
