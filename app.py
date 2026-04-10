import asyncio
import ccxt.pro as ccxt
import pandas as pd
import psycopg2
from psycopg2 import extras
import os
import threading
import requests
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

# ======================== 1. الإعدادات والربط ========================
app = Flask(__name__)

DB_URL = os.environ.get('DATABASE_URL')
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

INITIAL_BALANCE = 1000.0
MAX_OPEN_TRADES = 30
# --- إعدادات الهجوم والسرعة v147 ---
ENTRY_SCORE_THRESHOLD = 70     # سكور أسهل للدخول
TAKE_PROFIT_PCT = 0.02         # هدف قريب لضمان الأرباح (2%)
STOP_LOSS_PCT = -0.03          # وقف خسارة (3%)
# -------------------------------

MIN_VOLUME_24H = 700000        # سيولة مقبولة لفتح خيارات أكثر
STABLECOINS = ['USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'UST', 'FDUSD', 'PYUSD', 'USDP', 'EUR', 'GBP']
EXCLUDED_COINS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=5)
    except: pass

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS trades 
            (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, exit_price REAL,
             take_profit REAL, stop_loss REAL, investment REAL, 
             status TEXT, score INTEGER, open_time TEXT, close_time TEXT, date_added DATE)''')
        conn.commit()
        cur.close(); conn.close()
    except Exception as e: print(f"DB Init Error: {e}")

# ======================== 2. محرك التحليل المطور (السرعة القصوى) ========================

async def perform_analysis(sym, exchange_instance):
    try:
        bars = await exchange_instance.fetch_ohlcv(sym, timeframe='1h', limit=30)
        if not bars or len(bars) < 20: return None
        
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']; volume = df['vol']; score = 0
        
        # 1. فلتر الحجم (أصبح أسهل: 1.5 ضعف)
        avg_vol = volume.iloc[-21:-1].mean()
        if volume.iloc[-1] > (avg_vol * 1.5): score += 40
        
        # 2. فلتر البولينجر (توسيع طفيف للقبول)
        ma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        if (((ma20 + 2*std20) - (ma20 - 2*std20)) / (ma20 + 1e-9)).iloc[-1] < 0.06: score += 30
        
        # 3. فلتر RSI (نطاق واسع: 35-75)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 35 < rsi.iloc[-1] < 75: score += 30
            
        if score >= ENTRY_SCORE_THRESHOLD:
            return {'symbol': sym, 'score': int(score), 'price': close.iloc[-1]}
    except: pass
    return None

async def scan_batch(batch, exchange_instance):
    tasks = [perform_analysis(sym, exchange_instance) for sym in batch]
    return await asyncio.gather(*tasks)

async def main_engine():
    init_db()
    EXCHANGE = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            valid_symbols = [s for s, t in tickers.items() if '/USDT' in s and 
                             s.split('/')[0] not in STABLECOINS and 
                             s not in EXCLUDED_COINS and 
                             (t.get('quoteVolume', 0) or 0) >= MIN_VOLUME_24H]

            top_500 = sorted(valid_symbols, key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:500]
            
            # مسح المجموعات (100 عملة في المرة)
            batch_size = 100
            for i in range(0, len(top_500), batch_size):
                batch = top_500[i:i + batch_size]
                results = await scan_batch(batch, EXCHANGE)
                
                valid_hits = [r for r in results if r is not None]
                if valid_hits:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    for hit in valid_hits:
                        cur.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
                        if cur.fetchone()[0] >= MAX_OPEN_TRADES: break
                        
                        cur.execute("SELECT COUNT(*) FROM trades WHERE symbol = %s AND status = 'OPEN'", (hit['symbol'],))
                        if cur.fetchone()[0] == 0:
                            tp = hit['price'] * (1 + TAKE_PROFIT_PCT)
                            sl = hit['price'] * (1 + STOP_LOSS_PCT)
                            cur.execute("INSERT INTO trades (symbol, entry_price, current_price, take_profit, stop_loss, investment, status, score, open_time, date_added) VALUES (%s, %s, %s, %s, %s, %s, 'OPEN', %s, %s, %s)", 
                                       (hit['symbol'], hit['price'], hit['price'], tp, sl, 50.0, hit['score'], datetime.now().strftime('%H:%M:%S'), datetime.now().date()))
                    conn.commit(); cur.close(); conn.close()
                await asyncio.sleep(0.3)

            # تحديث الصفقات الجارية
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute("SELECT * FROM trades WHERE status = 'OPEN'")
            for ot in cur.fetchall():
                sym = ot['symbol']
                if sym in tickers:
                    cp = tickers[sym]['last']
                    if cp <= ot['stop_loss'] or cp >= ot['take_profit']:
                        cur.execute("UPDATE trades SET current_price=%s, exit_price=%s, status='CLOSED', close_time=%s WHERE symbol=%s", (cp, cp, datetime.now().strftime('%H:%M:%S'), sym))
                        send_telegram_msg(f"✅ *تم الإغلاق:* {sym} | السعر: {cp}")
                    else:
                        cur.execute("UPDATE trades SET current_price=%s WHERE symbol=%s", (cp, sym))
            conn.commit(); cur.close(); conn.close()
            
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Loop Error: {e}")
            await asyncio.sleep(5)

# ======================== 3. لوحة التحكم ========================

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY open_time DESC")
        opens = cur.fetchall()
        cur.execute("SELECT * FROM trades WHERE status = 'CLOSED' ORDER BY close_time DESC LIMIT 15")
        closed = cur.fetchall()
        realized = sum([ (t['investment'] * ((t['exit_price']-t['entry_price'])/t['entry_price'])) for t in closed ])
        floating = sum([ (t['investment'] * ((t['current_price']-t['entry_price'])/t['entry_price'])) for t in opens ])
        total = INITIAL_BALANCE + realized + floating
        cur.close(); conn.close()
    except: return "Database Error"

    html = """
    <!DOCTYPE html><html lang="ar"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
    <title>Super Turbo Bot v147</title><style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; direction: rtl; }
        .stats { display: flex; gap: 10px; margin-bottom: 20px; }
        .card { background: #1e2329; padding: 12px; border-radius: 8px; flex: 1; text-align: center; border-bottom: 4px solid #f0b90b; }
        table { width: 100%; border-collapse: collapse; background: #1e2329; margin-bottom: 20px; border-radius: 8px; overflow: hidden; }
        th { background: #2b3139; padding: 10px; color: #848e9c; font-size: 13px; }
        td { padding: 10px; text-align: center; border-bottom: 1px solid #2b3139; font-size: 13px; }
        .profit { color: #0ecb81; } .loss { color: #f6465d; }
        .btn-close { background: #f6465d; color: white; border: none; padding: 3px 6px; border-radius: 4px; text-decoration: none; font-size: 10px; }
        .badge { background: #f0b90b; color: black; padding: 2px 5px; border-radius: 4px; font-size: 11px; font-weight: bold; }
    </style></head><body>
        <h1>🚀 الرادار الهجومي (v147)</h1>
        <div class="stats">
            <div class="card"><h3>الرصيد الكلي</h3><p>${{ "%.2f"|format(total) }}</p></div>
            <div class="card"><h3>أرباح محققة</h3><p class="profit">${{ "%+.2f"|format(realized) }}</p></div>
            <div class="card"><h3>نشط</h3><p>{{ opens|length }}/30</p></div>
        </div>
        <table>
            <tr><th>العملة</th><th>وقت الدخول</th><th>الدخول</th><th>الحالي</th><th>الربح %</th><th>تحكم</th></tr>
            {% for t in opens %}
            <tr>
                <td><b>{{ t.symbol }}</b> <span class="badge">S:{{t.score}}</span></td>
                <td>{{ t.open_time }}</td>
                <td>{{ "%.4f"|format(t.entry_price) }}</td><td>{{ "%.4f"|format(t.current_price) }}</td>
                <td class="{{ 'profit' if t.current_price >= t.entry_price else 'loss' }}"><b>{{ "%+.2f"|format(((t.current_price-t.entry_price)/t.entry_price)*100) }}%</b></td>
                <td><a href="/close/{{ t.symbol }}" class="btn-close">إغلاق</a></td>
            </tr>
            {% endfor %}
        </table>
        <h3 style="color: #848e9c;">آخر 15 صفقة مغلقة</h3>
        <table>
            <tr style="color: #848e9c;"><th>العملة</th><th>النتيجة</th><th>وقت الخروج</th></tr>
            {% for t in closed %}
            <tr>
                <td>{{ t.symbol }}</td>
                <td class="{{ 'profit' if t.exit_price >= t.entry_price else 'loss' }}">{{ "%+.2f"|format(((t.exit_price-t.entry_price)/t.entry_price)*100) }}%</td>
                <td>{{ t.close_time }}</td>
            </tr>
            {% endfor %}
        </table>
    </body></html>
    """
    return render_template_string(html, total=total, realized=realized, floating=floating, opens=opens, closed=closed)

@app.route('/close/<symbol>')
def close_trade(symbol):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE trades SET status='CLOSED', exit_price=current_price, close_time=%s WHERE symbol=%s AND status='OPEN'", (datetime.now().strftime('%H:%M:%S'), symbol))
        conn.commit(); cur.close(); conn.close()
    except: pass
    return redirect(url_for('index'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: asyncio.run(main_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=port)
