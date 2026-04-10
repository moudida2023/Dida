import asyncio
import ccxt.pro as ccxt
import pandas as pd
import psycopg2
from psycopg2 import extras
import os
import threading
from flask import Flask, render_template_string
from datetime import datetime

app = Flask(__name__)

# إعدادات قاعدة البيانات
DB_URL = os.environ.get('DATABASE_URL')
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

INITIAL_BALANCE = 500.0  # الرصيد الابتدائي

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

# ======================== المحرك البرمجي ========================

async def main_engine():
    # تهيئة الجدول وتطهير البيانات القديمة لضمان الدقة
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS trades")
        cur.execute('''CREATE TABLE trades 
            (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, 
             tp REAL, sl REAL, investment REAL, open_time TEXT)''')
        conn.commit()
        cur.close(); conn.close()
    except: pass

    EXCHANGE = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            # جلب أفضل 40 عملة من حيث حجم التداول
            top_symbols = sorted([s for s in tickers if '/USDT' in s], 
                               key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:40]
            
            conn = get_db_connection()
            cur = conn.cursor()

            for sym in top_symbols:
                price = tickers[sym]['last']
                # حساب الأهداف تلقائياً
                cur.execute("""INSERT INTO trades (symbol, entry_price, current_price, tp, sl, investment, open_time) 
                               VALUES (%s, %s, %s, %s, %s, 50.0, %s) 
                               ON CONFLICT (symbol) DO UPDATE SET current_price = EXCLUDED.current_price""", 
                            (sym, price, price, price*1.02, price*0.97, datetime.now().strftime('%H:%M:%S')))
            
            conn.commit()
            cur.close(); conn.close()
            await asyncio.sleep(10) 
        except:
            await asyncio.sleep(10)

# ======================== الواجهة الرسومية ========================

@app.route('/')
def index():
    trades = []
    total_pnl = 0
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        trades = cur.fetchall()
        cur.close(); conn.close()
        
        for t in trades:
            total_pnl += ((t['current_price'] - t['entry_price']) / t['entry_price']) * t['investment']
    except: pass

    # تم إصلاح إغلاق النصوص هنا لتجنب SyntaxError
    html_template = """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="5">
        <title>Portfolio Dashboard</title>
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; }
            .header { display: flex; justify-content: space-around; background: #1e2329; padding: 20px; border-radius: 10px; margin-bottom: 20px; border-bottom: 4px solid #f0b90b; }
            .stat-box { text-align: center; }
            .stat-label { color: #848e9c; font-size: 14px; }
            .stat-value { font-size: 22px; font-weight: bold; margin-top: 5px; }
            table { width: 100%; border-collapse: collapse; background: #1e2329; border-radius: 10px; overflow: hidden; }
            th { background: #2b3139; padding: 15px; color: #848e9c; }
            td { padding: 15px; text-align: center; border-bottom: 1px solid #2b3139; }
            .up { color: #0ecb81; } .down { color: #f6465d; }
        </style>
    </head>
    <body>
        <div class="header">
            <div class="stat-box">
                <div class="stat-label">رصيد المحفظة الحي</div>
                <div class="stat-value">${{ "%.2f"|format(500 + total_pnl) }}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">إجمالي الربح/الخسارة</div>
                <div class="stat-value {{ 'up' if total_pnl >= 0 else 'down' }}">${{ "%.2f"|format(total_pnl) }}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">الصفقات المفتوحة</div>
                <div class="stat-value">{{ trades|length }}</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>العملة</th>
                    <th>سعر الدخول</th>
                    <th>السعر الحالي</th>
                    <th>الربح %</th>
                    <th>الاستثمار</th>
                    <th>الوقت</th>
                </tr>
            </thead>
            <tbody>
                {% for t in trades %}
                {% set pct = ((t.current_price - t.entry_price) / t.entry_price) * 100 %}
                <tr>
                    <td><b>{{ t.symbol }}</b></td>
                    <td>{{ "%.4f"|format(t.entry_price) }}</td>
                    <td style="color: #f0b90b;">{{ "%.4f"|format(t.current_price) }}</td>
                    <td class="{{ 'up' if pct >= 0 else 'down' }}">{{ "%+.2f"|format(pct) }}%</td>
                    <td>${{ t.investment }}</td>
                    <td style="color: #848e9c;">{{ t.open_time }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </body>
    </html>
    """
    return render_template_string(html_template, trades=trades, total_pnl=total_pnl)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: asyncio.run(main_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=port)
