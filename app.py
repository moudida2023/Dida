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
SCAN_HISTORY = [] 

DB_URL = os.environ.get('DATABASE_URL')
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

# ======================== 2. محرك الفتح الإجباري (Forced Entry) ========================

async def main_engine():
    global SCAN_HISTORY
    # --- خطوة حاسمة: تنظيف قاعدة البيانات عند التشغيل ---
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # حذف الجدول القديم لضمان توافق الهيكل الجديد 100%
        cur.execute("DROP TABLE IF EXISTS trades")
        cur.execute('''CREATE TABLE trades 
            (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, 
             investment REAL, status TEXT, score INTEGER, open_time TEXT)''')
        conn.commit()
        cur.close(); conn.close()
    except: pass

    EXCHANGE = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            valid_symbols = [s for s in tickers if '/USDT' in s][:200]
            
            all_hits = []
            for sym in valid_symbols:
                try:
                    # سكور سهل جداً (50) للتأكد من فتح صفقات فوراً
                    all_hits.append({'symbol': sym, 'score': 99, 'price': tickers[sym]['last']})
                except: continue
                if len(all_hits) > 10: break # نكتفي بـ 10 للتجربة

            if all_hits:
                conn = get_db_connection()
                cur = conn.cursor()
                for hit in all_hits:
                    # إدخال مبسط جداً بدون تعقيدات
                    cur.execute("""INSERT INTO trades (symbol, entry_price, current_price, investment, status, score, open_time) 
                                   VALUES (%s, %s, %s, 50, 'OPEN', %s, %s) 
                                   ON CONFLICT (symbol) DO NOTHING""", 
                                (hit['symbol'], hit['price'], hit['price'], hit['score'], datetime.now().strftime('%H:%M:%S')))
                conn.commit()
                cur.close(); conn.close()

            SCAN_HISTORY.insert(0, {'time': datetime.now().strftime('%H:%M:%S'), 'found': len(all_hits)})
            await asyncio.sleep(15)
        except: await asyncio.sleep(10)

# ======================== 3. لوحة التحكم ========================

@app.route('/')
def index():
    opens = []
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades")
        opens = cur.fetchall()
        cur.close(); conn.close()
    except: pass

    return render_template_string("""
    <body style="background:#000; color:#0f0; direction:rtl; font-family:sans-serif; padding:20px;">
        <h2>🚀 فحص نظام الإدخال v157</h2>
        <p>إذا كان الجدول أدناه فارغاً، المشكلة في رابط DATABASE_URL حصراً.</p>
        <table border="1" style="width:100%; border-collapse:collapse;">
            <tr><th>العملة</th><th>السعر</th><th>السكور</th><th>الحالة</th></tr>
            {% for t in opens %}
            <tr><td>{{ t.symbol }}</td><td>{{ t.entry_price }}</td><td>{{ t.score }}</td><td>{{ t.status }}</td></tr>
            {% endfor %}
        </table>
    </body>""", opens=opens)

if __name__ == "__main__":
    threading.Thread(target=lambda: asyncio.run(main_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
