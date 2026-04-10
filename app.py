import asyncio
import ccxt.pro as ccxt
import pandas as pd
import psycopg2
from psycopg2 import extras
import os
import threading
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

# ======================== 1. الإعدادات العامة ========================
app = Flask(__name__)
SCAN_HISTORY = [] 

DB_URL = os.environ.get('DATABASE_URL')
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

INITIAL_BALANCE = 1000.0
MAX_OPEN_TRADES = 30
# --- التعديل المطلوب: العودة لسكور 70 لزيادة الفرص ---
ENTRY_SCORE_THRESHOLD = 70 

# قائمة الكلمات الدلالية لاستبعاد عملات الذكاء الاصطناعي (AI)
AI_KEYWORDS = ['FET', 'AGIX', 'OCEAN', 'RNDR', 'NEAR', 'GRT', 'INJ', 'THETA', 'AKT', 'ROSE', 'ORAI', 'PHB', 'NMR', 'AIT', 'GLM', 'TAO']

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

# ======================== 2. المحرك الهجومي (v152) ========================

async def perform_analysis(sym, exchange_instance):
    base_symbol = sym.split('/')[0] if '/' in sym else sym
    if any(k in base_symbol for k in AI_KEYWORDS):
        return None
    try:
        bars = await exchange_instance.fetch_ohlcv(sym, timeframe='1h', limit=30)
        if not bars or len(bars) < 20: return None
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']; volume = df['vol']; score = 0
        
        # تحليل فني
        avg_vol = volume.iloc[-21:-1].mean()
        if volume.iloc[-1] > (avg_vol * 1.5): score += 40
        ma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        if (((ma20 + 2*std20) - (ma20 - 2*std20)) / (ma20 + 1e-9)).iloc[-1] < 0.06: score += 30
        delta = close.diff(); gain = (delta.where(delta > 0, 0)).rolling(14).mean(); loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 35 < rsi.iloc[-1] < 75: score += 30
        
        return {'symbol': sym, 'score': int(score), 'price': close.iloc[-1]}
    except: return None

async def main_engine():
    global SCAN_HISTORY
    EXCHANGE = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            start_t = datetime.now()
            tickers = await EXCHANGE.fetch_tickers()
            valid_symbols = [s for s in tickers if '/USDT' in s and (tickers[s].get('quoteVolume', 0) or 0) >= 700000]
            top_500 = sorted(valid_symbols, key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:500]
            
            all_results = []
            batch_size = 100
            for i in range(0, len(top_500), batch_size):
                batch = top_500[i:i + batch_size]
                tasks = [perform_analysis(sym, EXCHANGE) for sym in batch]
                batch_results = await asyncio.gather(*tasks)
                all_results.extend([r for r in batch_results if r is not None])
                await asyncio.sleep(0.1)

            found_this_turn = 0
            best_score_val = 0
            best_sym_val = "لا يوجد"

            if all_results:
                conn = get_db_connection(); cur = conn.cursor()
                # ترتيب حسب السكور الأعلى
                sorted_hits = sorted(all_results, key=lambda x: x['score'], reverse=True)
                if sorted_hits:
                    best_score_val = sorted_hits[0]['score']
                    best_sym_val = sorted_hits[0]['symbol']

                for hit in sorted_hits:
                    if hit['score'] >= ENTRY_SCORE_THRESHOLD:
                        cur.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
                        if cur.fetchone()[0] >= MAX_OPEN_TRADES: break
                        
                        cur.execute("SELECT COUNT(*) FROM trades WHERE symbol = %s AND status = 'OPEN'", (hit['symbol'],))
                        if cur.fetchone()[0] == 0:
                            # هدف 2% ووقف خسارة 3% لسرعة التداول
                            cur.execute("INSERT INTO trades (symbol, entry_price, current_price, take_profit, stop_loss, investment, status, score, open_time, date_added) VALUES (%s, %s, %s, %s, %s, 50, 'OPEN', %s, %s, %s)", 
                                       (hit['symbol'], hit['price'], hit['price'], hit['price']*1.02, hit['price']*0.97, hit['score'], datetime.now().strftime('%H:%M:%S'), datetime.now().date()))
                            found_this_turn += 1
                conn.commit(); cur.close(); conn.close()

            SCAN_HISTORY.insert(0, {'time': start_t.strftime('%H:%M:%S'), 'best': f"{best_sym_val} ({best_score_val})", 'found': found_this_turn})
            SCAN_HISTORY = SCAN_HISTORY[:10]
            await asyncio.sleep(15)
        except: await asyncio.sleep(10)

# ======================== 3. لوحة التحكم ========================

@app.route('/')
def index():
    try:
        conn = get_db_connection(); cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY open_time DESC")
        opens = cur.fetchall()
        cur.close(); conn.close()
    except: opens = []

    html = """
    <!DOCTYPE html><html lang="ar"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
    <title>Aggressive Bot v152</title><style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; direction: rtl; }
        .grid { display: grid; grid-template-columns: 1fr 2fr; gap: 20px; }
        .box { background: #1e2329; padding: 15px; border-radius: 8px; border-top: 3px solid #f0b90b; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px; }
        th, td { padding: 10px; text-align: center; border-bottom: 1px solid #2b3139; }
        .success { color: #0ecb81; font-weight: bold; }
        .warning { color: #f0b90b; }
    </style></head><body>
        <h1>🛰️ رادار المسح الهجومي (سكور 70)</h1>
        <div class="grid">
            <div class="box">
                <h3>📊 مراقبة المسح</h3>
                <table>
                    <tr><th>الوقت</th><th>أفضل سكور</th><th>تم الدخول</th></tr>
                    {% for s in scans %}
                    <tr>
                        <td>{{ s.time }}</td><td class="warning">{{ s.best }}</td>
                        <td class="success">+{{ s.found }}</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
            <div class="box">
                <h3>🔓 الصفقات المفتوحة ({{ opens|length }}/30)</h3>
                <table>
                    <tr><th>العملة</th><th>الربح %</th><th>السكور</th></tr>
                    {% for t in opens %}
                    <tr>
                        <td><b>{{ t.symbol }}</b></td>
                        <td style="color: {{ '#0ecb81' if t.current_price >= t.entry_price else '#f6465d' }}">
                            {{ "%+.2f"|format(((t.current_price-t.entry_price)/t.entry_price)*100) }}%
                        </td>
                        <td class="warning">{{ t.score }}</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
    </body></html>
    """
    return render_template_string(html, opens=opens, scans=SCAN_HISTORY)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: asyncio.run(main_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=port)
