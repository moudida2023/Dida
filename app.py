import os, threading, asyncio, psycopg2, requests, time
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

app = Flask(__name__)

# --- الإعدادات الثابتة ---
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
INITIAL_CAPITAL = 1000.0
INVESTMENT = 50.0

def get_db_connection():
    try:
        return psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=15)
    except Exception as e:
        print(f"DB Error: {e}")
        return None

def close_position(symbol, exit_price, reason):
    conn = get_db_connection()
    if not conn: return
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (str(symbol),))
        t = cur.fetchone()
        if t:
            pnl = ((float(exit_price) - float(t['entry_price'])) / float(t['entry_price'])) * INVESTMENT
            cur.execute("INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s,%s,%s)",
                        (str(symbol), float(t['entry_price']), float(exit_price), pnl, str(reason), datetime.now().strftime('%H:%M:%S')))
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (str(symbol),))
            conn.commit()
        cur.close(); conn.close()
    except: pass

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
                            cp = float(tickers[sym]['last'])
                            en = float(t['entry_price'])
                            if cp >= en * 1.04: close_position(sym, cp, "🎯 الربح 4%")
                            elif cp <= en * 0.98: close_position(sym, cp, "🛑 الخسارة 2%")
                            else: cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (cp, sym))
                conn.commit(); cur.close(); conn.close()
            await asyncio.sleep(20)
        except: await asyncio.sleep(30)

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        if not conn: return "Database Connection Error", 500
        cur = conn.cursor(extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        ot = cur.fetchall()
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        res = cur.fetchone()
        r_pnl = float(res[0]) if res else 0.0
        cur.close(); conn.close()
        
        f_pnl = sum(((float(t['current_price'])-float(t['entry_price']))/float(t['entry_price']))*INVESTMENT for t in ot)
        net = INITIAL_CAPITAL + r_pnl + f_pnl
        
        return render_template_string("""
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="20">
<style>
    body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; margin: 0; padding: 10px; }
    .card { background: #1e2329; padding: 15px; border-radius: 10px; border-bottom: 3px solid #f0b90b; margin-bottom: 10px; }
    .up { color: #0ecb81; } .down { color: #f6465d; }
    table { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 10px; }
    th, td { padding: 8px; border: 1px solid #2b3139; }
</style></head><body>
    <div class="card">
        <small>إجمالي قيمة المحفظة</small><br><b style="font-size:24px;">${{ "%.2f"|format(net) }}</b><br>
        <small>الصفقات المفتوحة: {{ count }} / 20</small>
    </div>
    <div style="display:flex; justify-content:space-around; font-size:12px; margin-bottom:10px;">
        <div>السيولة: ${{ "%.2f"|format(1000 + r - (count*50)) }}</div>
        <div class="{{ 'up' if f >= 0 else 'down' }}">أرباح عائمة: ${{ "%.2f"|format(f) }}</div>
    </div>
    <table>
        <tr><th>العملة</th><th>السعر</th><th>الربح ($)</th></tr>
        {% for t in ot %}
        {% set p = ((t.current_price - t.entry_price) / t.entry_price) * 50 %}
        <tr><td><b>{{ t.symbol }}</b></td><td style="color:#f0b90b;">{{ "%.5f"|format(t.current_price) }}</td><td class="{{ 'up' if p >= 0 else 'down' }}">${{ "%.2f"|format(p) }}</td></tr>
        {% endfor %}
    </table>
</body></html>""", net=net, count=len(ot), r=r_pnl, f=f_pnl, ot=ot)
    except Exception as e: return str(e), 500

def keep_alive():
    while True:
        try:
            u = os.environ.get('RENDER_EXTERNAL_URL')
            if u: requests.get(u, timeout=10)
        except: pass
        time.sleep(600)

if __name__ == "__main__":
    threading.Thread(target=keep_alive, daemon=True).start()
    threading.Thread(target=lambda: asyncio.run(trading_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
