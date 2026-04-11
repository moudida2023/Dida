import os
import threading
import asyncio
import ccxt.pro as ccxt
import psycopg2
from psycopg2 import extras
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

app = Flask(__name__)

# --- الإعدادات ---
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a/trading_bot_db_wv1h"
VIRTUAL_CAPITAL = 1000.0
TARGET_RATE = 0.03 # 3%
STOP_RATE = 0.03   # 3%

def get_db_connection():
    try:
        url = DB_URL.replace("postgres://", "postgresql://", 1) if DB_URL.startswith("postgres://") else DB_URL
        return psycopg2.connect(url, connect_timeout=10)
    except: return None

# دالة ذكية لإعادة بناء قاعدة البيانات ومنع خطأ 500
def repair_database():
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        # حذف الجداول القديمة التي تسبب الخطأ
        cur.execute("DROP TABLE IF EXISTS trades CASCADE;")
        cur.execute("DROP TABLE IF EXISTS closed_trades CASCADE;")
        
        # إنشاء الجداول بالهيكل الجديد والمطلوب
        cur.execute('''CREATE TABLE trades 
            (symbol TEXT PRIMARY KEY, entry_price DOUBLE PRECISION, current_price DOUBLE PRECISION, 
             tp_price DOUBLE PRECISION, sl_price DOUBLE PRECISION, investment DOUBLE PRECISION, open_time TEXT)''')
        cur.execute('''CREATE TABLE closed_trades 
            (id SERIAL PRIMARY KEY, symbol TEXT, entry_price DOUBLE PRECISION, exit_price DOUBLE PRECISION, 
             pnl DOUBLE PRECISION, exit_reason TEXT, close_time TEXT)''')
        conn.commit()
        cur.close(); conn.close()
        print("✅ تم إصلاح قاعدة البيانات وتصفيرها بنجاح!")

# --- محرك التداول ---
async def trading_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            conn = get_db_connection()
            if not conn: await asyncio.sleep(10); continue
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            cur.execute("SELECT * FROM trades")
            active_trades = {r['symbol']: r for r in cur.fetchall()}
            
            tickers = await exchange.fetch_tickers()
            symbols = sorted([s for s in tickers if '/USDT' in s], 
                            key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:500]
            
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
            
            count = len(active_trades)
            for s in symbols:
                if count >= 20: break
                price = float(tickers[s]['last'])
                change = float(tickers[s].get('percentage', 0))
                if s not in active_trades and change > 1.8:
                    tp, sl = price * (1 + TARGET_RATE), price * (1 - STOP_RATE)
                    cur.execute("INSERT INTO trades VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                (s, price, price, tp, sl, VIRTUAL_CAPITAL, datetime.now().strftime('%H:%M:%S')))
                    count += 1
            
            conn.commit()
            cur.close(); conn.close()
            await asyncio.sleep(20)
        except: await asyncio.sleep(20)

# --- الواجهة ---
HTML_CODE = """
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
<style>
    body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; }
    .stat-card { background: #1e2329; padding: 15px; border-radius: 12px; border-bottom: 4px solid #f0b90b; flex: 1; margin: 5px; }
    table { width: 100%; max-width: 1000px; margin: 20px auto; border-collapse: collapse; background: #1e2329; border-radius: 10px; overflow: hidden; }
    th { background: #2b3139; padding: 12px; color: #848e9c; }
    td { padding: 12px; border-bottom: 1px solid #2b3139; }
    .up { color: #0ecb81; } .down { color: #f6465d; }
</style></head><body>
    <h2 style="color:#f0b90b;">🛰️ رادار v285 | تم الإصلاح والتصفير</h2>
    <div style="display:flex; max-width:1000px; margin:auto;">
        <div class="stat-card">صافي الأرباح<br><b class="{{ 'up' if (cp + fp) >= 0 else 'down' }}" style="font-size:24px;">${{ "%.2f"|format(cp + fp) }}</b></div>
        <div class="stat-card">الصفقات النشطة<br><b style="font-size:24px;">{{ ot|length }} / 20</b></div>
    </div>
    <table>
        <tr><th>العملة</th><th>الدخول</th><th>الحالي</th><th>الهدف (+3%)</th><th>الوقف (-3%)</th><th>الربح/الخسارة</th></tr>
        {% for t in ot %}
        {% set pnl = ((t.current_price - t.entry_price) / t.entry_price) * 1000 %}
        <tr><td><b>{{ t.symbol }}</b></td><td>${{ t.entry_price }}</td><td style="color:#f0b90b;">${{ t.current_price }}</td><td class="up">${{ "%.4f"|format(t.tp_price) }}</td><td class="down">${{ "%.4f"|format(t.sl_price) }}</td><td class="{{ 'up' if pnl >= 0 else 'down' }}">${{ "%.2f"|format(pnl) }}</td></tr>
        {% endfor %}
    </table>
</body></html>
"""

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades")
        ot = cur.fetchall()
        cur.execute("SELECT SUM(pnl) FROM closed_trades")
        cp = float(cur.fetchone()[0] or 0.0)
        cur.close(); conn.close()
        fp = sum([((t['current_price'] - t['entry_price']) / t['entry_price']) * 1000 for t in ot])
        return render_template_string(HTML_CODE, ot=ot, cp=cp, fp=fp)
    except: return "<h1>جاري تهيئة البيانات... أعد التحديث بعد ثوانٍ</h1>"

if __name__ == "__main__":
    # تشغيل أمر الإصلاح لمرة واحدة عند بدء التشغيل
    repair_database()
    t = threading.Thread(target=lambda: asyncio.run(trading_engine()))
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
