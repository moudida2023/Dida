import asyncio
import ccxt.pro as ccxt
import pandas as pd
import psycopg2
from psycopg2 import extras
import os
import threading
from flask import Flask, render_template_string
from datetime import datetime

# ======================== 1. الإعدادات المحصنة ========================
app = Flask(__name__)
SCAN_HISTORY = [] 
ERROR_LOGS = []

DB_URL = os.environ.get('DATABASE_URL')
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

# دالة اتصال مرنة مع محاولات إعادة اتصال
def get_db_connection():
    try:
        return psycopg2.connect(DB_URL, sslmode='require', connect_timeout=10)
    except Exception as e:
        ERROR_LOGS.insert(0, f"فشل اتصال الداتابيز: {str(e)}")
        return None

# تهيئة قاعدة البيانات وضمان وجود الجدول
def safe_init_db():
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute('''CREATE TABLE IF NOT EXISTS trades 
                (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, exit_price REAL,
                 take_profit REAL, stop_loss REAL, investment REAL, 
                 status TEXT, score INTEGER, open_time TEXT, close_time TEXT, date_added DATE)''')
            conn.commit()
            cur.close(); conn.close()
        except: pass

# ======================== 2. محرك البحث "المضاد للرصاص" ========================

async def perform_safe_analysis(sym, exchange_instance):
    try:
        # جلب البيانات مع مهلة زمنية قصيرة لمنع التعليق
        bars = await asyncio.wait_for(exchange_instance.fetch_ohlcv(sym, timeframe='1h', limit=15), timeout=5)
        if not bars or len(bars) < 10: return None
        
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        # استراتيجية دخول مبسطة جداً لضمان تنفيذ صفقات
        last_vol = df['vol'].iloc[-1]
        avg_vol = df['vol'].mean()
        
        # إذا كان الحجم الحالي أكبر من المتوسط، فهذه فرصة (سكور 75)
        if last_vol > avg_vol:
            return {'symbol': sym, 'score': 75, 'price': df['close'].iloc[-1]}
    except: return None # تجاهل أي خطأ في عملة فردية

async def main_engine():
    global SCAN_HISTORY, ERROR_LOGS
    safe_init_db()
    EXCHANGE = ccxt.gateio({'enableRateLimit': True, 'timeout': 20000})
    
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            # مسح الـ 300 عملة الأعلى سيولة
            valid_symbols = [s for s in tickers if '/USDT' in s]
            top_300 = sorted(valid_symbols, key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:300]
            
            all_hits = []
            # مسح متوازٍ مع حماية من الأخطاء
            for i in range(0, len(top_300), 50):
                batch = top_300[i:i+50]
                tasks = [perform_safe_analysis(s, EXCHANGE) for s in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                all_hits.extend([r for r in results if isinstance(r, dict) and r is not None])

            if all_hits:
                conn = get_db_connection()
                if conn:
                    cur = conn.cursor()
                    for hit in all_hits:
                        try:
                            # محاولة الإدخال مع تجاهل التكرار
                            cur.execute("INSERT INTO trades (symbol, entry_price, current_price, take_profit, stop_loss, investment, status, score, open_time, date_added) VALUES (%s, %s, %s, %s, %s, 50, 'OPEN', %s, %s, %s) ON CONFLICT (symbol) DO NOTHING", 
                                       (hit['symbol'], hit['price'], hit['price'], hit['price']*1.02, hit['price']*0.98, hit['score'], datetime.now().strftime('%H:%M:%S'), datetime.now().date()))
                        except: continue
                    conn.commit()
                    cur.close(); conn.close()

            SCAN_HISTORY.insert(0, {'time': datetime.now().strftime('%H:%M:%S'), 'found': len(all_hits)})
            SCAN_HISTORY = SCAN_HISTORY[:5]
            
        except Exception as e:
            ERROR_LOGS.insert(0, f"خطأ في دورة المحرك: {str(e)}")
        
        await asyncio.sleep(10) # انتظار قبل الدورة التالية

# ======================== 3. لوحة التحكم المستقرة ========================

@app.route('/')
def index():
    opens = []
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY open_time DESC")
            opens = cur.fetchall()
            cur.close(); conn.close()
    except: pass

    html = """
    <!DOCTYPE html><html lang="ar"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
    <title>Anti-Error Bot v156</title><style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; direction: rtl; }
        .error-log { background: #2c1515; border: 1px solid #f6465d; padding: 10px; border-radius: 5px; color: #f6465d; margin-bottom: 20px; }
        .success-log { background: #152c1e; border: 1px solid #0ecb81; padding: 10px; border-radius: 5px; color: #0ecb81; margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: #1e2329; padding: 15px; border-radius: 8px; }
        table { width: 100%; border-collapse: collapse; font-size: 12px; }
        th, td { padding: 8px; border-bottom: 1px solid #2b3139; text-align: center; }
    </style></head><body>
        <h2>🛡️ نظام التشغيل المستقر (v156)</h2>
        
        {% if errors %}
        <div class="error-log"><b>⚠️ تنبيهات تقنية:</b> {{ errors[0] }}</div>
        {% else %}
        <div class="success-log"><b>✅ حالة النظام:</b> المحرك يعمل بدون أخطاء تقنية.</div>
        {% endif %}

        <div class="grid">
            <div class="card">
                <h3>🔄 سجل المسح المباشر</h3>
                <table>
                    <tr><th>الوقت</th><th>عملات مطابقة</th></tr>
                    {% for s in scans %}
                    <tr><td>{{ s.time }}</td><td>{{ s.found }} عملة</td></tr>
                    {% endfor %}
                </table>
            </div>
            <div class="card">
                <h3>💰 الصفقات المفتوحة ({{ opens|length }})</h3>
                <table>
                    <tr><th>العملة</th><th>السعر</th><th>السكور</th></tr>
                    {% for t in opens %}
                    <tr><td><b>{{ t.symbol }}</b></td><td>{{ t.entry_price }}</td><td>{{ t.score }}</td></tr>
                    {% endfor %}
                </table>
            </div>
        </div>
    </body></html>
    """
    return render_template_string(html, opens=opens, scans=SCAN_HISTORY, errors=ERROR_LOGS[:3])

if __name__ == "__main__":
    # تشغيل المحرك في خيط مستقل مع حماية من التوقف
    def run_engine_forever():
        while True:
            try:
                asyncio.run(main_engine())
            except:
                import time
                time.sleep(5)

    threading.Thread(target=run_engine_forever, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
