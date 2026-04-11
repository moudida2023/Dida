import os
import threading
import asyncio
import ccxt.pro as ccxt
import psycopg2
from psycopg2 import extras
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

app = Flask(__name__)

# --- 1. الإعدادات الجوهرية ---
DB_URL = os.environ.get('DATABASE_URL', "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a/trading_bot_db_wv1h")

VIRTUAL_CAPITAL = 1000.0  # رأس مال الصفقة الواحدة
MAX_TRADES = 20
TARGET_RATE = 0.03       # 3% جني أرباح
STOP_RATE = 0.03         # 3% وقف خسارة

def get_db_connection():
    try:
        url = DB_URL.replace("postgres://", "postgresql://", 1) if DB_URL.startswith("postgres://") else DB_URL
        return psycopg2.connect(url, connect_timeout=5)
    except: return None

# --- 2. محرك التداول (نظام 3% / 3%) ---
async def trading_engine():
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS trades 
            (symbol TEXT PRIMARY KEY, entry_price DOUBLE PRECISION, current_price DOUBLE PRECISION, 
             tp_price DOUBLE PRECISION, sl_price DOUBLE PRECISION, investment DOUBLE PRECISION, open_time TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS closed_trades 
            (id SERIAL PRIMARY KEY, symbol TEXT, entry_price DOUBLE PRECISION, exit_price DOUBLE PRECISION, 
             pnl DOUBLE PRECISION, exit_reason TEXT, close_time TEXT)''')
        conn.commit()
        cur.close(); conn.close()

    exchange = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            conn = get_db_connection()
            active_trades = {}
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute("SELECT * FROM trades")
                active_trades = {r['symbol']: r for r in cur.fetchall()}
                cur.close(); conn.close()

            tickers = await exchange.fetch_tickers()
            symbols = sorted([s for s in tickers if '/USDT' in s], 
                            key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:500]
            
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                # فحص الأهداف (3% صعوداً أو هبوطاً)
                for sym, data in active_trades.items():
                    current_p = float(tickers[sym]['last'])
                    
                    reason = ""
                    if current_p >= data['tp_price']: reason = "🎯 جني أرباح (+3%)"
                    elif current_p <= data['sl_price']: reason = "🛑 وقف خسارة (-3%)"
                    
                    if reason:
                        pnl = ((current_p - data['entry_price']) / data['entry_price']) * VIRTUAL_CAPITAL
                        cur.execute("INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s,%s,%s)",
                                    (sym, data['entry_price'], current_p, pnl, reason, datetime.now().strftime('%m-%d %H:%M')))
                        cur.execute("DELETE FROM trades WHERE symbol = %s", (sym,))
                    else:
                        cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (current_p, sym))

                # فتح صفقات جديدة (استراتيجية السكور 85)
                count = len(active_trades)
                if count < MAX_TRADES:
                    for s in symbols:
                        price = float(tickers[s]['last'])
                        change = float(tickers[s].get('percentage', 0))
                        
                        if s not in active_trades and change > 1.8:
                            tp = price * (1 + TARGET_RATE)
                            sl = price * (1 - STOP_RATE)
                            cur.execute("""INSERT INTO trades (symbol, entry_price, current_price, tp_price, sl_price, investment, open_time) 
                                           VALUES (%s, %s, %s, %s, %s, %s, %s)""", 
                                        (s, price, price, tp, sl, VIRTUAL_CAPITAL, datetime.now().strftime('%H:%M:%S')))
                            conn.commit()
                            count += 1
                            if count >= MAX_TRADES: break
                
                conn.commit()
                cur.close(); conn.close()
            await asyncio.sleep(20)
        except: await asyncio.sleep(20)

# --- 3. واجهة العرض (v280) ---
HTML = """
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
<style>
    body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; }
    .stat-card { background: #1e2329; padding: 15px; border-radius: 12px; border-bottom: 4px solid #f0b90b; flex: 1; margin: 5px; }
    table { width: 100%; max-width: 1000px; margin: 20px auto; border-collapse: collapse; background: #1e2329; border-radius: 10px; overflow: hidden; }
    th { background: #2b3139; padding: 12px; color: #848e9c; font-size: 13px; }
    td { padding: 12px; border-bottom: 1px solid #2b3139; font-size: 14px; }
    .up { color: #0ecb81; } .down { color: #f6465d; }
    .btn { background: #f6465d; color: white; padding: 5px 12px; border-radius: 4px; text-decoration: none; font-size: 12px; }
</style></head><body>
    <h2 style="color:#f0b90b;">🛰️ رادار v280 | أهداف متساوية 3%</h2>
    <div style="display:flex; max-width:1000px; margin:auto;">
        <div class="stat-card">صافي المحفظة ($1000)<br><b class="{{ 'up' if (cp + fp) >= 0 else 'down' }}" style="font-size:24px;">${{ "%.2f"|format(cp + fp) }}</b></div>
        <div class="stat-card">الصفقات النشطة<br><b style="font-size:24px;">{{ ot|length }} / 20</b></div>
    </div>
    <table>
        <tr><th>العملة</th><th>الدخول</th><th>السعر الحالي</th><th>الهدف (+3%)</th><th>الوقف (-3%)</th><th>الربح/الخسارة</th><th>تحكم</th></tr>
        {% for t in ot %}
        {% set pnl = ((t.current_price - t.entry_price) / t.entry_price) * 1000 %}
        <tr>
            <td><b>{{ t.symbol }}</b><br><small style="color:#848e9c;">{{ t.open_time }}</small></td>
            <td>${{ "%.4f"|format(t.entry_price) }}</td>
            <td style="color:#f0b90b; font-weight:bold;">${{ "%.4f"|format(t.current_price) }}</td>
            <td class="up">${{ "%.4f"|format(t.tp_price) }}</td>
            <td class="down">${{ "%.4f"|format(t.sl_price) }}</td>
            <td class="{{ 'up' if pnl >= 0 else 'down' }}" style="font-weight:bold;">${{ "%.2f"|format(pnl) }}</td>
            <td><a href="/close/{{ t.symbol }}" class="btn">إغلاق</a></td>
        </tr>
        {% endfor %}
    </table>
    <h3 style="margin-top:25px; color:#848e9c;">السجل التاريخي (المحفظة الافتراضية)</h3>
    <table>
        <tr style="background:#161a1e;"><th>العملة</th><th>الربح المحقق</th><th>سبب الإغلاق</th><th>التوقيت</th></tr>
        {% for c in ct %}
        <tr>
            <td><b>{{ c.symbol }}</b></td>
            <td class="{{ 'up' if c.pnl >= 0 else 'down' }}">${{ "%.2f"|format(c.pnl) }}</td>
            <td>{{ c.exit_reason }}</td>
            <td>{{ c.close_time }}</td>
        </tr>
        {% endfor %}
    </table>
</body></html>
"""

@app.route('/')
def index():
    ot, ct, cp, fp = [], [], 0.0, 0.0
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
            ot = cur.fetchall()
            cur.execute("SELECT * FROM closed_trades ORDER BY close_time DESC LIMIT 10")
            ct = cur.fetchall()
            cur.execute("SELECT SUM(pnl) FROM closed_trades")
            res = cur.fetchone()
            cp = float(res[0]) if res and res[0] else 0.0
            cur.close(); conn.close()
            for t in ot:
                fp += ((t['current_price'] - t['entry_price']) / t['entry_price']) * 1000
    except: pass
    return render_template_string(HTML, ot=ot, ct=ct, cp=cp, fp=fp)

@app.route('/close/<symbol>')
def close_manual(symbol):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (symbol,))
        t = cur.fetchone()
        if t:
            pnl = ((t['current_price'] - t['entry_price']) / t['entry_price']) * 1000
            cur.execute("INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s,%s,%s)",
                        (t['symbol'], t['entry_price'], t['current_price'], pnl, "إغلاق يدوي", datetime.now().strftime('%m-%d %H:%M')))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
            conn.commit()
        cur.close(); conn.close()
    return redirect(url_for('index'))

if __name__ == "__main__":
    t = threading.Thread(target=lambda: asyncio.run(trading_engine()))
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
