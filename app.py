import os
import threading
import asyncio
import ccxt.pro as ccxt
import psycopg2
from psycopg2 import extras
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

app = Flask(__name__)

# --- 1. إعدادات الاتصال الآمنة ---
# ملاحظة: تم استخدام الرابط الداخلي لضمان استقرار الاتصال بالمنفذ 5432
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a/trading_bot_db_wv1h"

VIRTUAL_CAPITAL = 1000.0
TARGET_RATE = 0.03  # 3%
STOP_RATE = 0.03    # 3%
ENTRY_SCORE = 0.5   # 0.5% ارتفاع للدخول

def get_db_connection():
    try:
        # التأكد من استخدام بروتوكول postgresql الصحيح
        url = DB_URL.replace("postgres://", "postgresql://", 1) if DB_URL.startswith("postgres://") else DB_URL
        # الاتصال عبر المنفذ الافتراضي 5432
        return psycopg2.connect(url, connect_timeout=10)
    except Exception as e:
        print(f"❌ Database Connection Error: {e}")
        return None

def init_db():
    """إنشاء الجداول إذا لم تكن موجودة عند بدء التشغيل"""
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
        print("✅ Database initialized successfully.")

# --- 2. محرك التداول (الرصد والتحليل) ---
async def trading_engine():
    init_db()
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            conn = get_db_connection()
            if not conn: 
                await asyncio.sleep(15); continue
            
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            # جلب الصفقات الحالية
            cur.execute("SELECT * FROM trades")
            active_trades = {r['symbol']: r for r in cur.fetchall()}
            
            # جلب بيانات السوق
            tickers = await exchange.fetch_tickers()
            symbols = sorted([s for s in tickers if '/USDT' in s and tickers[s]['last']], 
                            key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:500]
            
            # فحص الإغلاق (3% ربح أو خسارة)
            for sym, data in active_trades.items():
                if sym not in tickers: continue
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
            
            # البحث عن فرص جديدة
            count = len(active_trades)
            if count < 20:
                for s in symbols:
                    if s in active_trades: continue
                    price = float(tickers[s]['last'])
                    change = float(tickers[s].get('percentage', 0) or 0)
                    
                    if change > ENTRY_SCORE:
                        tp, sl = price * (1 + TARGET_RATE), price * (1 - STOP_RATE)
                        cur.execute("INSERT INTO trades VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                    (s, price, price, tp, sl, VIRTUAL_CAPITAL, datetime.now().strftime('%H:%M:%S')))
                        count += 1
                        if count >= 20: break
            
            conn.commit()
            cur.close(); conn.close()
            await asyncio.sleep(20)
        except Exception as e:
            print(f"Engine Error: {e}")
            await asyncio.sleep(20)

# --- 3. واجهة الويب (v320) ---
HTML_TEMPLATE = """
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="20">
<title>Radar v320 Final</title>
<style>
    body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; }
    .container { max-width: 1000px; margin: auto; }
    .card { background: #1e2329; padding: 20px; border-radius: 10px; border-bottom: 4px solid #f0b90b; margin: 10px; flex: 1; }
    table { width: 100%; border-collapse: collapse; background: #1e2329; margin-top: 20px; border-radius: 8px; overflow: hidden; }
    th { background: #2b3139; padding: 12px; color: #848e9c; font-size: 13px; }
    td { padding: 12px; border-bottom: 1px solid #2b3139; }
    .up { color: #0ecb81; font-weight: bold; } .down { color: #f6465d; font-weight: bold; }
    .btn { background: #f6465d; color: white; padding: 5px 10px; border-radius: 4px; text-decoration: none; font-size: 12px; }
</style></head><body>
    <div class="container">
        <h2 style="color:#f0b90b;">🛰️ رادار التداول v320</h2>
        <div style="display:flex;">
            <div class="card">الأرباح المحققة<br><b class="{{ 'up' if cp >= 0 else 'down' }}" style="font-size:22px;">${{ "%.2f"|format(cp) }}</b></div>
            <div class="card">الصفقات المفتوحة<br><b style="font-size:22px;">{{ ot|length }} / 20</b></div>
        </div>
        <table>
            <tr><th>العملة</th><th>الدخول</th><th>الحالي</th><th>الهدف</th><th>الوقف</th><th>الربح ($)</th><th>إجراء</th></tr>
            {% for t in ot %}
            {% set pnl = ((t.current_price - t.entry_price) / t.entry_price) * 1000 %}
            <tr>
                <td><b>{{ t.symbol }}</b></td>
                <td>${{ "%.4f"|format(t.entry_price) }}</td>
                <td style="color:#f0b90b;">${{ "%.4f"|format(t.current_price) }}</td>
                <td class="up">${{ "%.4f"|format(t.tp_price) }}</td>
                <td class="down">${{ "%.4f"|format(t.sl_price) }}</td>
                <td class="{{ 'up' if pnl >= 0 else 'down' }}">${{ "%.2f"|format(pnl) }}</td>
                <td><a href="/close/{{ t.symbol }}" class="btn">إغلاق</a></td>
            </tr>
            {% endfor %}
        </table>
    </div>
</body></html>
"""

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        ot = cur.fetchall()
        cur.execute("SELECT SUM(pnl) FROM closed_trades")
        res = cur.fetchone()
        cp = float(res[0]) if res and res[0] else 0.0
        cur.close(); conn.close()
        return render_template_string(HTML_TEMPLATE, ot=ot, cp=cp)
    except:
        return "<h1>جاري الاتصال بقاعدة البيانات... أعد التحميل</h1>", 500

@app.route('/close/<symbol>')
def manual_close(symbol):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (symbol,))
        t = cur.fetchone()
        if t:
            pnl = ((t['current_price'] - t['entry_price']) / t['entry_price']) * 1000
            cur.execute("INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s,%s,%s)",
                        (t['symbol'], t['entry_price'], t['current_price'], pnl, "يدوي", datetime.now().strftime('%m-%d %H:%M')))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
            conn.commit()
        cur.close(); conn.close()
    return redirect(url_for('index'))

if __name__ == "__main__":
    t = threading.Thread(target=lambda: asyncio.run(trading_engine()))
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
