import asyncio
import ccxt.pro as ccxt
import pandas as pd
import psycopg2
from psycopg2 import extras
import os
import threading
import requests
from flask import Flask, render_template_string
from datetime import datetime

# ======================== 1. الإعدادات والربط ========================
app = Flask(__name__)

DB_URL = os.environ.get('DATABASE_URL')
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# الإعدادات المطلوبة
INITIAL_BALANCE = 1000.0    # الرصيد الأساسي
TRADE_AMOUNT = 50.0        # مبلغ كل صفقة
MAX_OPEN_TRADES = 20       # أقصى عدد صفقات

STOP_LOSS_PCT = -0.05
MIN_PROFIT_FOR_EXIT = 0.05
EXIT_SCORE_THRESHOLD = 95
MIN_VOLUME_24H = 1000000

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
            (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, 
             exit_price REAL, investment REAL, status TEXT, score INTEGER, 
             open_time TEXT, close_time TEXT)''')
        conn.commit()
        cur.close(); conn.close()
    except Exception as e: print(f"DB Error: {e}")

# ======================== 2. المحرك والتحليل ========================

async def perform_analysis(sym, exchange_instance):
    try:
        bars = await exchange_instance.fetch_ohlcv(sym, timeframe='1h', limit=40)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']
        score = 0
        ma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        bw = ((ma20 + 2*std20) - (ma20 - 2*std20)) / (ma20 + 1e-9)
        if bw.iloc[-1] < 0.045: score += 50 
        delta = close.diff(); gain = (delta.where(delta > 0, 0)).rolling(14).mean(); loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 40 < rsi.iloc[-1] < 70: score += 45 
        return int(score), close.iloc[-1]
    except: return 0, 0

async def main_engine():
    init_db()
    EXCHANGE = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            valid_symbols = [s for s, t in tickers.items() if '/USDT' in s and s not in EXCLUDED_COINS and (t.get('quoteVolume', 0) or 0) >= MIN_VOLUME_24H and (t.get('percentage', 0) or 0) <= 5.0]
            
            scored_candidates = []
            for sym in sorted(valid_symbols, key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:60]:
                score, _ = await perform_analysis(sym, EXCHANGE)
                if score >= 85: 
                    scored_candidates.append({'symbol': sym, 'score': score, 'price': tickers[sym]['last']})
                await asyncio.sleep(0.02)

            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)

            if scored_candidates:
                best = sorted(scored_candidates, key=lambda x: x['score'], reverse=True)[0]
                cur.execute("SELECT COUNT(*) FROM trades WHERE symbol = %s AND status = 'OPEN'", (best['symbol'],))
                if cur.fetchone()[0] == 0:
                    cur.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
                    if cur.fetchone()[0] < MAX_OPEN_TRADES:
                        entry_time = datetime.now().strftime('%H:%M:%S')
                        cur.execute("INSERT INTO trades (symbol, entry_price, current_price, investment, status, score, open_time) VALUES (%s, %s, %s, %s, 'OPEN', %s, %s)", 
                                   (best['symbol'], best['price'], best['price'], TRADE_AMOUNT, best['score'], entry_time))
                        send_telegram_msg(f"💎 *دخول:* {best['symbol']} | سكور: {best['score']}")

            cur.execute("SELECT * FROM trades WHERE status = 'OPEN'")
            for ot in cur.fetchall():
                sym = ot['symbol']
                current_p = tickers[sym]['last'] if sym in tickers else ot['current_price']
                pnl = (current_p - ot['entry_price']) / ot['entry_price']
                s_score, _ = await perform_analysis(sym, EXCHANGE)
                if pnl <= STOP_LOSS_PCT or (s_score >= EXIT_SCORE_THRESHOLD and pnl >= MIN_PROFIT_FOR_EXIT):
                    cur.execute("UPDATE trades SET exit_price=%s, status='CLOSED', close_time=%s WHERE symbol=%s", (current_p, datetime.now().strftime('%H:%M:%S'), sym))
                    send_telegram_msg(f"🛑 *إغلاق:* {sym} | النتيجة: {pnl*100:+.2f}%")
                else:
                    cur.execute("UPDATE trades SET current_price=%s WHERE symbol=%s", (current_p, sym))

            conn.commit(); cur.close(); conn.close()
            await asyncio.sleep(20)
        except Exception as e: await asyncio.sleep(15)

# ======================== 3. واجهة الموقع ========================

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY open_time DESC")
        opens = cur.fetchall()
        cur.execute("SELECT * FROM trades WHERE status = 'CLOSED'")
        all_closed = cur.fetchall()
        
        # حسابات المحفظة
        realized_pnl = sum([ (t['investment'] * ((t['exit_price']-t['entry_price'])/t['entry_price'])) for t in all_closed ])
        floating_pnl = sum([ (t['investment'] * ((t['current_price']-t['entry_price'])/t['entry_price'])) for t in opens ])
        
        used_margin = len(opens) * TRADE_AMOUNT  # الرصيد المستخدم حالياً
        total_equity = INITIAL_BALANCE + realized_pnl + floating_pnl # الرصيد الكلي
        
        cur.close(); conn.close()

        html_code = """
        <!DOCTYPE html><html lang="ar"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
        <title>لوحة التحكم</title><style>
        body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; direction: rtl; }
        .stats { display: flex; gap: 15px; margin-bottom: 25px; flex-wrap: wrap; }
        .card { background: #1e2329; padding: 15px; border-radius: 10px; flex: 1; min-width: 180px; text-align: center; border-top: 4px solid #f0b90b; }
        .profit { color: #0ecb81; } .loss { color: #f6465d; }
        table { width: 100%; border-collapse: collapse; background: #1e2329; margin-top: 15px; }
        th, td { padding: 12px; text-align: right; border-bottom: 1px solid #2b3139; }
        </style></head><body>
        <h1>📊 حالة المحفظة الرقمية</h1>
        <div class="stats">
            <div class="card"><h3>إجمالي الرصيد</h3><p>${{ "%.2f"|format(total_equity) }}</p></div>
            <div class="card"><h3>الرصيد المستخدم</h3><p>${{ "%.2f"|format(used_margin) }}</p></div>
            <div class="card"><h3>الرصيد المتاح</h3><p>${{ "%.2f"|format(total_equity - used_margin) }}</p></div>
            <div class="card"><h3>عدد الصفقات</h3><p>{{ opens|length }} / 20</p></div>
            <div class="card"><h3>الربح العائم</h3><p class="{{ 'profit' if floating_pnl >= 0 else 'loss' }}">${{ "%+.2f"|format(floating_pnl) }}</p></div>
        </div>
        <h2>🚀 صفقات مفتوحة حالياً</h2>
        <table><tr><th>العملة</th><th>الدخول</th><th>الحالي</th><th>الربح%</th><th>الوقت</th></tr>
        {% for t in opens %}
        <tr><td><b>{{ t.symbol }}</b></td><td>{{ t.entry_price }}</td><td>{{ t.current_price }}</td>
        <td class="{{ 'profit' if t.current_price >= t.entry_price else 'loss' }}">{{ "%+.2f"|format(((t.current_price-t.entry_price)/t.entry_price)*100) }}%</td>
        <td>{{ t.open_time }}</td></tr>
        {% endfor %}</table>
        </body></html>
        """
        return render_template_string(html_code, total_equity=total_equity, used_margin=used_margin, floating_pnl=floating_pnl, opens=opens)
    except Exception as e: return str(e)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_engine())
