import os
import threading
import time
import requests
import asyncio
import ccxt.pro as ccxt
import psycopg2
from psycopg2 import extras
from flask import Flask, render_template_string
from datetime import datetime

app = Flask(__name__)

# --- 1. الإعدادات ---
DB_URL = os.environ.get('DATABASE_URL')
APP_URL = os.environ.get('APP_URL')

def get_db_connection():
    try:
        url = DB_URL.replace("postgres://", "postgresql://", 1) if DB_URL and "postgres://" in DB_URL else DB_URL
        return psycopg2.connect(url, sslmode='require', connect_timeout=10)
    except: return None

# --- 2. محرك التداول (البحث عن الصفقات وحفظها) ---
async def trading_engine():
    """هذا هو المحرك الذي يملأ قاعدة البيانات بالبيانات لتظهر في الموقع"""
    print("🚀 بدء محرك البحث عن الصفقات...")
    
    # إنشاء الجدول إذا لم يكن موجوداً
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS trades 
            (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, open_time TEXT)''')
        conn.commit()
        cur.close(); conn.close()

    exchange = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            # جلب أسعار السوق
            tickers = await exchange.fetch_tickers()
            # اختيار أفضل 10 عملات من حيث حجم التداول (USDT)
            top_symbols = sorted([s for s in tickers if '/USDT' in s], 
                               key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:10]
            
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                for sym in top_symbols:
                    price = tickers[sym]['last']
                    # إدخال أو تحديث السعر الحالي
                    cur.execute("""INSERT INTO trades (symbol, entry_price, current_price, open_time) 
                                   VALUES (%s, %s, %s, %s) 
                                   ON CONFLICT (symbol) DO UPDATE SET current_price = EXCLUDED.current_price""", 
                                (sym, price, price, datetime.now().strftime('%H:%M:%S')))
                conn.commit()
                cur.close(); conn.close()
            
            await asyncio.sleep(30) # تحديث كل 30 ثانية
        except Exception as e:
            print(f"⚠️ خطأ المحرك: {e}")
            await asyncio.sleep(20)

# --- 3. برنامج النبض الذاتي (Keep-Alive) ---
def self_ping():
    time.sleep(60)
    while True:
        if APP_URL:
            try: requests.get(APP_URL, timeout=20)
            except: pass
        time.sleep(240)

# --- 4. واجهة العرض (Dashboard) ---
@app.route('/')
def index():
    trades = []
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
            trades = cur.fetchall()
            cur.close(); conn.close()
    except: pass

    return render_template_string("""
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; text-align: center; }
        .card { background: #1e2329; border: 1px solid #f0b90b; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; background: #1e2329; }
        th, td { padding: 12px; border-bottom: 1px solid #2b3139; text-align: center; }
        .price { color: #f0b90b; font-weight: bold; }
    </style></head><body>
        <div class="card">
            <h1>📊 مراقب الصفقات المباشر</h1>
            <p>عدد الصفقات المسجلة في القاعدة: <b>{{ trades|length }}</b></p>
        </div>
        <table>
            <tr><th>العملة</th><th>سعر الدخول</th><th>السعر الحالي</th><th>وقت التحديث</th></tr>
            {% for t in trades %}
            <tr>
                <td><b>{{ t.symbol }}</b></td>
                <td>{{ t.entry_price }}</td>
                <td class="price">{{ t.current_price }}</td>
                <td style="color:#848e9c;">{{ t.open_time }}</td>
            </tr>
            {% endfor %}
        </table>
        {% if not trades %}<p>⚠️ جاري البحث عن صفقات... انتظر 30 ثانية.</p>{% endif %}
    </body></html>
    """, trades=trades)

# --- 5. تشغيل كل شيء معاً ---
if __name__ == "__main__":
    # تشغيل النبض الذاتي
    threading.Thread(target=self_ping, daemon=True).start()
    
    # تشغيل محرك البحث عن الصفقات (عبر Asyncio في خيط منفصل)
    def start_engine():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(trading_engine())

    threading.Thread(target=start_engine, daemon=True).start()
    
    # تشغيل Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
