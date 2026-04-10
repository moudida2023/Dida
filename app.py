import asyncio
import ccxt.pro as ccxt
import pandas as pd
import psycopg2
from psycopg2 import extras
import os
import threading
from flask import Flask, render_template_string
from datetime import datetime

# ======================== 1. الإعدادات ========================
app = Flask(__name__)
SCAN_HISTORY = [] 
DEBUG_LOGS = [] # قائمة لتخزين الأخطاء وتتبعها

DB_URL = os.environ.get('DATABASE_URL')
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

def get_db_connection():
    # إضافة timeout للاتصال بقاعدة البيانات لضمان عدم تعليق البوت
    return psycopg2.connect(DB_URL, sslmode='require', connect_timeout=5)

# ======================== 2. المحرك مع تتبع الأخطاء ========================

async def main_engine():
    global SCAN_HISTORY, DEBUG_LOGS
    # استخدام باينانس كمصدر بيانات إضافي للتأكد من جودة الاتصال
    EXCHANGE = ccxt.gateio({'enableRateLimit': True, 'timeout': 30000})
    
    while True:
        try:
            start_t = datetime.now()
            tickers = await EXCHANGE.fetch_tickers()
            
            # فلترة أولية بسيطة جداً لضمان الحصول على عملات
            valid_symbols = [s for s in tickers if '/USDT' in s and (tickers[s].get('quoteVolume', 0) or 0) >= 100000]
            top_200 = sorted(valid_symbols, key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:200]
            
            all_results = []
            for sym in top_200:
                try:
                    bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=20)
                    if not bars: continue
                    
                    df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                    # سكور مبسط جداً (فقط RSI وحجم التداول) للتأكد من أن النظام يعمل
                    avg_vol = df['vol'].iloc[-10:-1].mean()
                    vol_factor = df['vol'].iloc[-1] / (avg_vol + 1e-9)
                    
                    # إذا زاد الحجم عن المتوسط، نعتبره سكور 85 للتجربة
                    if vol_factor > 1.1:
                        all_results.append({'symbol': sym, 'score': 85, 'price': df['close'].iloc[-1]})
                except: continue

            if all_results:
                try:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    for hit in all_results:
                        # محاولة الدخول
                        cur.execute("SELECT COUNT(*) FROM trades WHERE symbol = %s AND status = 'OPEN'", (hit['symbol'],))
                        if cur.fetchone()[0] == 0:
                            cur.execute("INSERT INTO trades (symbol, entry_price, current_price, take_profit, stop_loss, investment, status, score, open_time, date_added) VALUES (%s, %s, %s, %s, %s, 50, 'OPEN', %s, %s, %s)", 
                                       (hit['symbol'], hit['price'], hit['price'], hit['price']*1.02, hit['price']*0.98, hit['score'], datetime.now().strftime('%H:%M:%S'), datetime.now().date()))
                    conn.commit()
                    cur.close(); conn.close()
                except Exception as e:
                    DEBUG_LOGS.insert(0, f"خطأ في قاعدة البيانات: {str(e)}")

            SCAN_HISTORY.insert(0, {'time': start_t.strftime('%H:%M:%S'), 'count': len(all_results)})
            SCAN_HISTORY = SCAN_HISTORY[:5]
            await asyncio.sleep(10)
            
        except Exception as e:
            DEBUG_LOGS.insert(0, f"خطأ عام في المحرك: {str(e)}")
            await asyncio.sleep(10)

# ======================== 3. واجهة الفحص الفني ========================

@app.route('/')
def index():
    # محاولة جلب الصفقات للتأكد من أن الجدول موجود
    try:
        conn = get_db_connection(); cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE status = 'OPEN'")
        opens = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        return f"خطأ حرج في قاعدة البيانات: {e}. تأكد من إعداد DATABASE_URL بشكل صحيح."

    html = """
    <!DOCTYPE html><html lang="ar"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="5">
    <title>Bot Diagnostics v155</title><style>
        body { background: #000; color: #0f0; font-family: monospace; padding: 20px; direction: rtl; }
        .log-box { background: #111; border: 1px solid #333; padding: 10px; margin-bottom: 20px; color: #ff4444; }
        .success { color: #0ecb81; }
        .panel { border: 1px solid #222; padding: 10px; margin-bottom: 10px; }
    </style></head><body>
        <h1>🛠️ وضع تشخيص الأخطاء (Diagnostics)</h1>
        
        <div class="log-box">
            <h3>⚠️ آخر سجلات الأخطاء:</h3>
            <ul>
                {% for log in logs %} <li>{{ log }}</li> {% endfor %}
                {% if not logs %} <li>لا توجد أخطاء تقنية حالياً. المحرك يعمل.</li> {% endif %}
            </ul>
        </div>

        <div class="panel">
            <h3>🔄 حالة المسح المستمر:</h3>
            {% for s in scans %}
            <p>[{{ s.time }}] تم العثور على <b class="success">{{ s.count }}</b> عملة مطابقة للشروط الفنية.</p>
            {% endfor %}
        </div>

        <div class="panel">
            <h3>💼 الصفقات المفتوحة في الداتابيز: ({{ opens|length }})</h3>
            {% for t in opens %}
            <p>- {{ t.symbol }} | سكور: {{ t.score }} | وقت: {{ t.open_time }}</p>
            {% endfor %}
        </div>
    </body></html>
    """
    return render_template_string(html, opens=opens, scans=SCAN_HISTORY, logs=DEBUG_LOGS[:5])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: asyncio.run(main_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=port)
