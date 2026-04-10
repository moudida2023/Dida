import asyncio
import ccxt.pro as ccxt
import pandas as pd
import psycopg2
from psycopg2 import extras
import os
import threading
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

# ======================== 1. الإعدادات المحسنة للدخول المكثف ========================
app = Flask(__name__)
SCAN_HISTORY = [] 
CURRENT_STATUS = "نظام البحث المكثف نشط..."

DB_URL = os.environ.get('DATABASE_URL')
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

MAX_OPEN_TRADES = 30
ENTRY_SCORE_THRESHOLD = 70 # سكور سهل لتحفيز دخول الصفقات

# استبعاد العملات المستقرة فقط لفتح المجال لكل العملات الأخرى
STABLECOINS = ['USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'FDUSD', 'PYUSD']

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

# ======================== 2. خوارزمية البحث عن الفرص v154 ========================

async def perform_analysis(sym, exchange_instance):
    try:
        # استخدام limit=20 لسرعة جلب البيانات وتكرار المسح
        bars = await exchange_instance.fetch_ohlcv(sym, timeframe='1h', limit=20)
        if not bars or len(bars) < 15: return None
        
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']; volume = df['vol']; score = 0
        
        # 1. فلتر السيولة المرن (1.2 ضعف يكفي للدخول)
        avg_vol = volume.iloc[-11:-1].mean()
        if volume.iloc[-1] > (avg_vol * 1.2): score += 40
        
        # 2. فلتر البولينجر الواسع (لاقتناص التذبذب العالي)
        ma20 = close.rolling(15).mean(); std20 = close.rolling(15).std()
        bw = (((ma20 + 2*std20) - (ma20 - 2*std20)) / (ma20 + 1e-9)).iloc[-1]
        if bw < 0.08: score += 30
        
        # 3. فلتر RSI الهجومي (نطاق واسع جداً 25 - 80)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(10).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(10).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        current_rsi = rsi.iloc[-1]
        if 25 < current_rsi < 80: score += 30
        
        return {'symbol': sym, 'score': int(score), 'price': close.iloc[-1]}
    except: return None

async def main_engine():
    global SCAN_HISTORY, CURRENT_STATUS
    EXCHANGE = ccxt.gateio({'enableRateLimit': True, 'timeout': 20000})
    
    while True:
        try:
            start_t = datetime.now()
            tickers = await EXCHANGE.fetch_tickers()

            # تصفية أفضل 300 عملة حسب السيولة
            valid_symbols = [s for s in tickers if '/USDT' in s and s.split('/')[0] not in STABLECOINS]
            top_300 = sorted(valid_symbols, key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:300]
            
            CURRENT_STATUS = f"تم مسح {len(top_300)} عملة بنجاح..."
            all_results = []
            
            # مسح متوازي سريع جداً
            batch_size = 60
            for i in range(0, len(top_300), batch_size):
                batch = top_300[i:i + batch_size]
                tasks = [perform_analysis(sym, EXCHANGE) for sym in batch]
                batch_results = await asyncio.gather(*tasks)
                all_results.extend([r for r in batch_results if r is not None])
            
            found_this_turn = 0
            if all_results:
                conn = get_db_connection(); cur = conn.cursor()
                # الدخول في كل عملة سكورها >= 70
                for hit in sorted(all_results, key=lambda x: x['score'], reverse=True):
                    if hit['score'] >= ENTRY_SCORE_THRESHOLD:
                        cur.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
                        if cur.fetchone()[0] >= MAX_OPEN_TRADES: break
                        
                        cur.execute("SELECT COUNT(*) FROM trades WHERE symbol = %s AND status = 'OPEN'", (hit['symbol'],))
                        if cur.fetchone()[0] == 0:
                            cur.execute("INSERT INTO trades (symbol, entry_price, current_price, take_profit, stop_loss, investment, status, score, open_time, date_added) VALUES (%s, %s, %s, %s, %s, 50, 'OPEN', %s, %s, %s)", 
                                       (hit['symbol'], hit['price'], hit['price'], hit['price']*1.02, hit['price']*0.97, hit['score'], datetime.now().strftime('%H:%M:%S'), datetime.now().date()))
                            found_this_turn += 1
                conn.commit(); cur.close(); conn.close()

            SCAN_HISTORY.insert(0, {'time': start_t.strftime('%H:%M:%S'), 'found': found_this_turn})
            SCAN_HISTORY = SCAN_HISTORY[:10]
            await asyncio.sleep(5) # انتظار قصير جداً لتكرار المسح بسرعة
            
        except Exception as e:
            CURRENT_STATUS = f"خطأ مؤقت: {str(e)[:20]}"
            await asyncio.sleep(5)

# ======================== 3. واجهة المراقبة المكثفة ========================

@app.route('/')
def index():
    try:
        conn = get_db_connection(); cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY open_time DESC")
        opens = cur.fetchall()
        cur.close(); conn.close()
    except: opens = []

    html = """
    <!DOCTYPE html><html lang="ar"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="7">
    <title>High-Frequency Bot v154</title><style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; direction: rtl; }
        .status-header { background: #1e2329; padding: 10px; border-radius: 8px; border-bottom: 3px solid #0ecb81; margin-bottom: 20px; text-align: center; }
        .grid { display: grid; grid-template-columns: 1fr 2fr; gap: 20px; }
        .box { background: #1e2329; padding: 15px; border-radius: 8px; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { padding: 10px; text-align: center; border-bottom: 1px solid #2b3139; }
        .entry-count { background: #0ecb81; color: black; padding: 2px 10px; border-radius: 12px; font-weight: bold; }
    </style></head><body>
        <div class="status-header">
            <b>📡 الحالة:</b> {{ status }} | <b>المسح:</b> توب 300 عملة
        </div>
        <div class="grid">
            <div class="box">
                <h3>🔄 نشاط الرادار (كل 5 ثوانٍ)</h3>
                <table>
                    <tr><th>الوقت</th><th>صفقات مكتشفة</th></tr>
                    {% for s in scans %}
                    <tr><td>{{ s.time }}</td><td><span class="entry-count">+{{ s.found }}</span></td></tr>
                    {% endfor %}
                </table>
            </div>
            <div class="box">
                <h3>🔓 الصفقات النشطة ({{ opens|length }}/30)</h3>
                <table>
                    <tr><th>العملة</th><th>الربح %</th><th>السكور</th><th>وقت الدخول</th></tr>
                    {% for t in opens %}
                    <tr>
                        <td><b>{{ t.symbol }}</b></td>
                        <td style="color: {{ '#0ecb81' if t.current_price >= t.entry_price else '#f6465d' }}">
                            {{ "%+.2f"|format(((t.current_price-t.entry_price)/t.entry_price)*100) }}%
                        </td>
                        <td>{{ t.score }}</td><td>{{ t.open_time }}</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
    </body></html>
    """
    return render_template_string(html, opens=opens, scans=SCAN_HISTORY, status=CURRENT_STATUS)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: asyncio.run(main_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=port)
