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

# رابط قاعدة البيانات من Render (تأكد من إضافته في إعدادات Render)
DB_URL = os.environ.get('DATABASE_URL', 'your_postgresql_url_here')

TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

INITIAL_BALANCE = 1000.0
TRADE_AMOUNT = 50.0
MAX_OPEN_TRADES = 20
STOP_LOSS_PCT = -0.03
MIN_PROFIT_FOR_EXIT = 0.03
EXIT_SCORE_THRESHOLD = 95
MIN_VOLUME_24H = 1000000

EXCLUDED_COINS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT', 'DOT/USDT', 'LTC/USDT']

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=5)
    except: pass

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS radar (symbol TEXT PRIMARY KEY, discovery_price REAL, current_price REAL, score INTEGER, discovery_time TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS trades (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, exit_price REAL, investment REAL, status TEXT, score INTEGER, open_time TEXT, close_time TEXT)''')
    conn.commit()
    cur.close(); conn.close()

# ======================== 2. محرك التحليل الفني ========================

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

# ======================== 3. منطق التداول ========================

async def main_engine():
    init_db()
    EXCHANGE = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            valid_symbols = [s for s, t in tickers.items() if '/USDT' in s and s not in EXCLUDED_COINS and '3L' not in s and '3S' not in s and (t.get('percentage', 0) or 0) <= 5.0 and (t.get('quoteVolume', 0) or 0) >= MIN_VOLUME_24H]
            
            scored_candidates = []
            valid_symbols = sorted(valid_symbols, key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)

            for sym in valid_symbols[:80]:
                score, _ = await perform_analysis(sym, EXCHANGE)
                if score >= 70: scored_candidates.append({'symbol': sym, 'score': score, 'price': tickers[sym]['last']})
                await asyncio.sleep(0.01)

            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            now_time = datetime.now().strftime('%H:%M:%S')

            if scored_candidates:
                scored_candidates.sort(key=lambda x: x['score'], reverse=True)
                best = scored_candidates[0]
                if best['score'] >= 85:
                    cur.execute("SELECT COUNT(*) FROM trades WHERE symbol = %s AND status = 'OPEN'", (best['symbol'],))
                    if cur.fetchone()[0] == 0:
                        cur.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
                        if cur.fetchone()[0] < MAX_OPEN_TRADES:
                            cur.execute("INSERT INTO trades (symbol, entry_price, current_price, investment, status, score, open_time) VALUES (%s, %s, %s, %s, 'OPEN', %s, %s)", (best['symbol'], best['price'], best['price'], TRADE_AMOUNT, best['score'], now_time))
                            send_telegram_msg(f"✅ *تم الدخول في:* {best['symbol']} (Score: {best['score']})")

            cur.execute("SELECT * FROM trades WHERE status = 'OPEN'")
            for ot in cur.fetchall():
                current_p = tickers[ot['symbol']]['last'] if ot['symbol'] in tickers else ot['current_price']
                change = (current_p - ot['entry_price']) / ot['entry_price']
                s_score, _ = await perform_analysis(ot['symbol'], EXCHANGE)
                
                if change <= STOP_LOSS_PCT or (s_score >= EXIT_SCORE_THRESHOLD and change >= MIN_PROFIT_FOR_EXIT):
                    status = 'CLOSED'
                    cur.execute("UPDATE trades SET exit_price=%s, status=%s, close_time=%s WHERE symbol=%s", (current_p, status, now_time, ot['symbol']))
                    send_telegram_msg(f"🛑 *تم الإغلاق:* {ot['symbol']} ({change*100:+.2f}%)")
                else:
                    cur.execute("UPDATE trades SET current_price=%s WHERE symbol=%s", (current_p, ot['symbol']))

            conn.commit(); cur.close(); conn.close()
            await asyncio.sleep(20)
        except Exception as e: print(f"Error: {e}"); await asyncio.sleep(10)

# ======================== 4. واجهة الموقع ========================

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY open_time DESC")
        open_trades = cur.fetchall()
        cur.execute("SELECT * FROM trades WHERE status = 'CLOSED' ORDER BY close_time DESC LIMIT 15")
        closed_trades = cur.fetchall()
        
        # حساب الرصيد
        cur.execute("SELECT investment, entry_price, exit_price FROM trades WHERE status = 'CLOSED'")
        realized = sum([(t[0] * ((t[2]-t[1])/t[1])) for t in cur.fetchall()])
        cur.execute("SELECT investment, entry_price, current_price FROM trades WHERE status = 'OPEN'")
        unrealized = sum([(t[0] * ((t[2]-t[1])/t[1])) for t in cur.fetchall()])
        
        cur.close(); conn.close()

        html = """
        <!DOCTYPE html><html><head><title>Dashboard</title><meta http-equiv="refresh" content="15">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; }
            .box { background: #1e2329; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #2b3139; }
            .profit { color: #0ecb81; } .loss { color: #f6465d; }
        </style></head><body>
            <h2>💰 الرصيد: ${{ "%.2f"|format(1000 + realized) }} (PNL: {{ "%+.2f"|format(realized + unrealized) }})</h2>
            <div class="box"><h3>🚀 صفقات مفتوحة</h3>
                <table><tr><th>العملة</th><th>الدخول</th><th>السعر</th><th>الربح</th></tr>
                {% for t in open_trades %}
                <tr><td>{{ t['symbol'] }}</td><td>{{ t['entry_price'] }}</td><td>{{ t['current_price'] }}</td>
                <td class="{{ 'profit' if t['current_price'] >= t['entry_price'] else 'loss' }}">
                {{ "%+.2f"|format(((t['current_price']-t['entry_price'])/t['entry_price'])*100) }}%</td></tr>
                {% endfor %}</table></div>
            <div class="box"><h3>✅ صفقات مغلقة</h3>
                <table><tr><th>العملة</th><th>النتيجة</th><th>الوقت</th></tr>
                {% for t in closed_trades %}
                <tr><td>{{ t['symbol'] }}</td><td class="{{ 'profit' if t['exit_price'] >= t['entry_price'] else 'loss' }}">
                {{ "%+.2f"|format(((t['exit_price']-t['entry_price'])/t['entry_price'])*100) }}%</td><td>{{ t['close_time'] }}</td></tr>
                {% endfor %}</table></div>
        </body></html>"""
        return render_template_string(html, open_trades=open_trades, closed_trades=closed_trades, realized=realized, unrealized=unrealized)
    except Exception as e: return str(e)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_engine())
