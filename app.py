import asyncio
import ccxt.pro as ccxt
import pandas as pd
import psycopg2
from psycopg2 import extras
import os
import threading
import requests
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime, timedelta

# ======================== 1. الإعدادات والربط ========================
app = Flask(__name__)

DB_URL = os.environ.get('DATABASE_URL')
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

INITIAL_BALANCE = 1000.0
MAX_OPEN_TRADES = 20
TAKE_PROFIT_PCT = 0.05
STOP_LOSS_PCT = -0.05
TRAILING_ACTIVATE = 0.02

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
             take_profit REAL, stop_loss REAL, investment REAL, 
             status TEXT, score INTEGER, open_time TEXT, close_time TEXT, date_added DATE)''')
        conn.commit()
        cur.close(); conn.close()
    except Exception as e: print(f"DB Error: {e}")

# ======================== 2. محرك التحليل ========================

async def is_market_safe(exchange_instance):
    try:
        bars = await exchange_instance.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=2)
        change = (bars[-1][4] - bars[-2][4]) / bars[-2][4]
        return change > -0.015 
    except: return True

async def perform_analysis(sym, exchange_instance):
    try:
        bars = await exchange_instance.fetch_ohlcv(sym, timeframe='1h', limit=40)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']; volume = df['vol']
        score = 0
        
        avg_vol = volume.iloc[-21:-1].mean()
        if volume.iloc[-1] > (avg_vol * 2.5): score += 40
        
        ma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        if (((ma20 + 2*std20) - (ma20 - 2*std20)) / (ma20 + 1e-9)).iloc[-1] < 0.045: score += 30
        
        delta = close.diff(); gain = (delta.where(delta > 0, 0)).rolling(14).mean(); loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 45 < rsi.iloc[-1] < 65: score += 30
            
        return int(score), close.iloc[-1]
    except: return 0, 0

# ======================== 3. المحرك الرئيسي ========================

async def main_engine():
    init_db()
    EXCHANGE = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            market_safe = await is_market_safe(EXCHANGE)
            tickers = await EXCHANGE.fetch_tickers()
            valid_symbols = [s for s, t in tickers.items() if '/USDT' in s and s not in EXCLUDED_COINS and (t.get('quoteVolume', 0) or 0) >= MIN_VOLUME_24H]
            
            scored_candidates = []
            if market_safe:
                for sym in sorted(valid_symbols, key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:60]:
                    score, _ = await perform_analysis(sym, EXCHANGE)
                    if score >= 85: 
                        scored_candidates.append({'symbol': sym, 'score': score, 'price': tickers[sym]['last']})
                    await asyncio.sleep(0.01)

            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)

            if scored_candidates:
                best = sorted(scored_candidates, key=lambda x: x['score'], reverse=True)[0]
                cur.execute("SELECT COUNT(*) FROM trades WHERE symbol = %s AND status = 'OPEN'", (best['symbol'],))
                if cur.fetchone()[0] == 0:
                    cur.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
                    if cur.fetchone()[0] < MAX_OPEN_TRADES:
                        # توزيع مخاطر: 75$ للسكور العالي جداً، و50$ للسكور الجيد
                        amt = 75.0 if best['score'] >= 95 else 50.0
                        tp = best['price'] * (1 + TAKE_PROFIT_PCT); sl = best['price'] * (1 + STOP_LOSS_PCT)
                        cur.execute("INSERT INTO trades (symbol, entry_price, current_price, take_profit, stop_loss, investment, status, score, open_time, date_added) VALUES (%s, %s, %s, %s, %s, %s, 'OPEN', %s, %s, %s)", 
                                   (best['symbol'], best['price'], best['price'], tp, sl, amt, best['score'], datetime.now().strftime('%H:%M:%S'), datetime.now().date()))
                        send_telegram_msg(f"🚀 *دخول:* {best['symbol']} | المبلغ: `${amt}`")

            cur.execute("SELECT * FROM trades WHERE status = 'OPEN'")
            for ot in cur.fetchall():
                sym = ot['symbol']
                if sym not in tickers: continue
                cp = tickers[sym]['last']; pnl = (cp - ot['entry_price']) / ot['entry_price']
                
                new_sl = ot['stop_loss']
                if pnl >= TRAILING_ACTIVATE and ot['stop_loss'] < ot['entry_price']: new_sl = ot['entry_price']
                
                if cp <= new_sl or cp >= ot['take_profit']:
                    cur.execute("UPDATE trades SET exit_price=%s, status='CLOSED', close_time=%s WHERE symbol=%s", (cp, datetime.now().strftime('%H:%M:%S'), sym))
                    send_telegram_msg(f"🏁 *إغلاق:* {sym} ({pnl*100:+.2f}%)")
                else:
                    cur.execute("UPDATE trades SET current_price=%s, stop_loss=%s WHERE symbol=%s", (cp, new_sl, sym))

            conn.commit(); cur.close(); conn.close()
            await asyncio.sleep(20)
        except: await asyncio.sleep(15)

# ======================== 4. الموقع (مع إضافة عمود المبلغ) ========================

@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=extras.DictCursor)
    cur.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY open_time DESC")
    opens = cur.fetchall()
    cur.execute("SELECT investment, entry_price, exit_price FROM trades WHERE status = 'CLOSED'")
    cls = cur.fetchall()
    realized = sum([ (t[0] * ((t[2]-t[1])/t[1])) for t in cls ])
    total = INITIAL_BALANCE + realized
    cur.close(); conn.close()

    html = """
    <!DOCTYPE html><html lang="ar"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
    <title>Master Bot v138</title><style>
    body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; direction: rtl; }
    .stats { display: flex; gap: 15px; margin-bottom: 20px; }
    .card { background: #1e2329; padding: 15px; border-radius: 8px; flex: 1; text-align: center; border-top: 4px solid #f0b90b; }
    table { width: 100%; border-collapse: collapse; background: #1e2329; border-radius: 8px; }
    th, td { padding: 12px; text-align: center; border-bottom: 1px solid #2b3139; }
    .profit { color: #0ecb81; } .loss { color: #f6465d; }
    .btn-close { background: #f6465d; color: white; border: none; padding: 5px 10px; border-radius: 4px; cursor: pointer; text-decoration: none; font-size: 11px; }
    </style></head><body>
    <h1>🛰️ لوحة التحكم المركزية</h1>
    <div class="stats">
        <div class="card"><h3>الرصيد الكلي</h3><p>${{ "%.2f"|format(total) }}</p></div>
        <div class="card"><h3>أرباح محققة</h3><p class="profit">${{ "%.2f"|format(realized) }}</p></div>
    </div>
    <table><tr>
        <th>العملة</th>
        <th>مبلغ الدخول</th> <th>سعر الدخول</th>
        <th>السعر الحالي</th>
        <th>الربح %</th>
        <th>السكور</th>
        <th>الإجراء</th>
    </tr>
    {% for t in opens %}
    <tr>
        <td><b>{{ t.symbol }}</b></td>
        <td><b>${{ t.investment }}</b></td> <td>{{ "%.4f"|format(t.entry_price) }}</td>
        <td>{{ "%.4f"|format(t.current_price) }}</td>
        <td class="{{ 'profit' if t.current_price >= t.entry_price else 'loss' }}">
            {{ "%+.2f"|format(((t.current_price-t.entry_price)/t.entry_price)*100) }}%
        </td>
        <td>{{ t.score }}</td>
        <td><a href="/close/{{ t.symbol }}" class="btn-close" onclick="return confirm('إغلاق يدوي؟')">إغلاق</a></td>
    </tr>
    {% endfor %}</table></body></html>
    """
    return render_template_string(html, total=total, realized=realized, opens=opens)

@app.route('/close/<symbol>')
def close_trade(symbol):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE trades SET status='CLOSED', close_time=%s WHERE symbol=%s AND status='OPEN'", (datetime.now().strftime('%H:%M:%S'), symbol))
        conn.commit(); cur.close(); conn.close()
    except: pass
    return redirect(url_for('index'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_engine())
