import os
import threading
import time
import asyncio
import ccxt.pro as ccxt
import psycopg2
from psycopg2 import extras
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime
import requests

app = Flask(__name__)

# --- 1. الإعدادات والربط الذكي ---
# تأكد من إضافة DATABASE_URL في Environment Variables على Render
DB_URL = os.environ.get('DATABASE_URL')
MAX_OPEN_TRADES = 20
INVESTMENT_AMOUNT = 50.0

def get_db_connection():
    if not DB_URL:
        print("❌ خطأ: لم يتم العثور على DATABASE_URL في الإعدادات!")
        return None
    try:
        # تصحيح رابط Postgres من منصة Render (تغيير postgres إلى postgresql)
        url = DB_URL.replace("postgres://", "postgresql://", 1) if "postgres://" in DB_URL else DB_URL
        return psycopg2.connect(url, sslmode='require', connect_timeout=15)
    except Exception as e:
        print(f"❌ فشل الاتصال بقاعدة البيانات: {e}")
        return None

# --- 2. المحرك (استعادة البيانات وجوباً قبل أي حركة) ---
async def trading_engine():
    # إنشاء الجداول فور التشغيل لضمان عدم حدوث خطأ 500
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute('''CREATE TABLE IF NOT EXISTS trades 
                (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, investment REAL, score INTEGER, open_time TEXT)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS closed_trades 
                (id SERIAL PRIMARY KEY, symbol TEXT, entry_price REAL, exit_price REAL, pnl REAL, close_time TEXT)''')
            conn.commit()
            cur.close()
            print("✅ قاعدة البيانات جاهزة ومستقرة.")
        finally:
            conn.close()

    exchange = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            # الخطوة 1: استرجاع الصفقات المفتوحة (الالتزام بالبيانات التاريخية)
            conn = get_db_connection()
            db_trades = {}
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute("SELECT symbol, entry_price, open_time FROM trades")
                rows = cur.fetchall()
                db_trades = {r['symbol']: {'entry_price': r['entry_price'], 'open_time': r['open_time']} for r in rows}
                cur.close(); conn.close()

            current_count = len(db_trades)
            
            # الخطوة 2: تحديث الأسعار والبحث عن فرص
            tickers = await exchange.fetch_tickers()
            all_symbols = sorted([s for s in tickers if '/USDT' in s], 
                               key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:500]
            
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                for sym in all_symbols:
                    price = tickers[sym]['last']
                    change = tickers[sym].get('percentage', 0)
                    
                    if sym in db_trades:
                        # تحديث السعر الحالي فقط (سعر الدخول يبقى ثابتاً من DB)
                        cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (price, sym))
                    else:
                        score = 85 if change > 1.8 else (80 if change > 0.8 and tickers[sym].get('quoteVolume', 0) > 5000000 else 0)
                        if score >= 80 and current_count < MAX_OPEN_TRADES:
                            entry_t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            cur.execute("""INSERT INTO trades (symbol, entry_price, current_price, investment, score, open_time) 
                                           VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""", 
                                        (sym, price, price, INVESTMENT_AMOUNT, score, entry_t))
                            conn.commit()
                            current_count += 1
                
                conn.commit()
                cur.close(); conn.close()
            
            await asyncio.sleep(20)
        except Exception as e:
            print(f"⚠️ خطأ في دورة المحرك: {e}")
            await asyncio.sleep(20)

# --- 3. الواجهة (v235) ---
@app.route('/close/<symbol>')
def close_trade(symbol):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute("SELECT * FROM trades WHERE symbol = %s", (symbol,))
            trade = cur.fetchone()
            if trade:
                pnl = ((trade['current_price'] - trade['entry_price']) / trade['entry_price']) * trade['investment']
                cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, close_time) 
                               VALUES (%s, %s, %s, %s, %s)""",
                            (trade['symbol'], trade['entry_price'], trade['current_price'], pnl, datetime.now().strftime('%Y-%m-%d %H:%M')))
                cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
                conn.commit()
        finally:
            cur.close(); conn.close()
    return redirect(url_for('index'))

@app.route('/')
def index():
    open_trades = []
    closed_pnl, floating_pnl = 0, 0
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
            open_trades = cur.fetchall()
            for t in open_trades:
                floating_pnl += ((t['current_price'] - t['entry_price']) / t['entry_price']) * t['investment']
            
            cur.execute("SELECT SUM(pnl) FROM closed_trades")
            closed_pnl = cur.fetchone()[0] or 0
            cur.close(); conn.close()
    except: pass

    html = """
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; }
        .card { background: #1e2329; padding: 15px; border-radius: 10px; text-align: center; border-bottom: 3px solid #f0b90b; }
        .up { color: #0ecb81; } .down { color: #f6465d; }
        table { width: 100%; border-collapse: collapse; background: #1e2329; margin-top: 20px; }
        th, td { padding: 10px; border-bottom: 1px solid #2b3139; text-align: center; }
        .btn { background: #f6465d; color: white; text-decoration: none; padding: 5px 12px; border-radius: 4px; }
    </style></head><body>
        <h2 style="text-align:center; color:#f0b90b;">🛰️ رادار الاستقرار v235</h2>
        <div style="display: flex; gap: 10px;">
            <div class="card" style="flex:1;">الصافي: <b class="up">${{ "%.2f"|format(closed_pnl + floating_pnl) }}</b></div>
            <div class="card" style="flex:1;">مفتوح: <b>{{ open_trades|length }} / 20</b></div>
        </div>
        <table>
            <tr style="background:#2b3139;"><th>العملة</th><th>الدخول المسجل</th><th>الحالي</th><th>الربح</th><th>تحكم</th></tr>
            {% for t in open_trades %}
            <tr>
                <td><b>{{ t.symbol }}</b></td>
                <td><span style="color:#0ecb81;">${{ "%.4f"|format(t.entry_price) }}</span><br><small>{{ t.open_time }}</small></td>
                <td style="color:#f0b90b;">${{ "%.4f"|format(t.current_price) }}</td>
                <td class="{{ 'up' if t.current_price >= t.entry_price else 'down' }}">
                    {{ "%+.2f"|format(((t.current_price - t.entry_price) / t.entry_price) * t.investment) }} USDT
                </td>
                <td><a href="/close/{{ t.symbol }}" class="btn">إغلاق</a></td>
            </tr>
            {% endfor %}
        </table>
    </body></html>
    """
    return render_template_string(html, ot=open_trades, cp=closed_pnl, fp=floating_pnl)

if __name__ == "__main__":
    def run_engine():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(trading_engine())
    threading.Thread(target=run_engine, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
