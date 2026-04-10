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

# --- ضع رابط قاعدة البيانات الخاص بك هنا بين علامتي التنصيص ---
# الرابط تجده في Render باسم External Database URL ويبدأ بـ postgres://
DB_URL = "ضع_رابط_قاعدة_بياناتك_هنا" 

# إذا كنت تريد استخدامه عبر إعدادات Render (أفضل للأمان)، اترك السطر التالي كما هو:
if os.environ.get('DATABASE_URL'):
    DB_URL = os.environ.get('DATABASE_URL')

# تغيير بسيط لضمان توافق الرابط مع مكتبة psycopg2
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

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
    # الاتصال مع تفعيل خاصية SSL المطلوبة في Render
    return psycopg2.connect(DB_URL, sslmode='require')

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS trades 
            (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, 
             exit_price REAL, investment REAL, status TEXT, score INTEGER, 
             open_time TEXT, close_time TEXT)''')
        conn.commit()
        cur.close()
        conn.close()
        print("✅ قاعدة البيانات جاهزة ومتصلة.")
    except Exception as e:
        print(f"❌ خطأ في الاتصال بقاعدة البيانات: {e}")

# ======================== 2. محرك التحليل والعمليات ========================

async def perform_analysis(sym, exchange_instance):
    try:
        bars = await exchange_instance.fetch_ohlcv(sym, timeframe='1h', limit=40)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']
        
        # استراتيجية السكور
        ma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        bw = ((ma20 + 2*std20) - (ma20 - 2*std20)) / (ma20 + 1e-9)
        score = 50 if bw.iloc[-1] < 0.045 else 0
        
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
            valid_symbols = [s for s, t in tickers.items() if '/USDT' in s and s not in EXCLUDED_COINS and (t.get('percentage', 0) or 0) <= 5.0 and (t.get('quoteVolume', 0) or 0) >= MIN_VOLUME_24H]
            
            scored_candidates = []
            for sym in valid_symbols[:80]:
                score, _ = await perform_analysis(sym, EXCHANGE)
                if score >= 85: 
                    scored_candidates.append({'symbol': sym, 'score': score, 'price': tickers[sym]['last']})
                await asyncio.sleep(0.01)

            if scored_candidates:
                scored_candidates.sort(key=lambda x: x['score'], reverse=True)
                best = scored_candidates[0]
                
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM trades WHERE symbol = %s AND status = 'OPEN'", (best['symbol'],))
                if cur.fetchone()[0] == 0:
                    cur.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
                    if cur.fetchone()[0] < MAX_OPEN_TRADES:
                        cur.execute("INSERT INTO trades (symbol, entry_price, current_price, investment, status, score, open_time) VALUES (%s, %s, %s, %s, 'OPEN', %s, %s)", 
                                   (best['symbol'], best['price'], best['price'], TRADE_AMOUNT, best['score'], datetime.now().strftime('%H:%M:%S')))
                        conn.commit()
                cur.close(); conn.close()

            # تحديث الصفقات
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute("SELECT * FROM trades WHERE status = 'OPEN'")
            for ot in cur.fetchall():
                curr_p = tickers[ot['symbol']]['last'] if ot['symbol'] in tickers else ot['current_price']
                change = (curr_p - ot['entry_price']) / ot['entry_price']
                s_score, _ = await perform_analysis(ot['symbol'], EXCHANGE)
                
                if change <= STOP_LOSS_PCT or (s_score >= EXIT_SCORE_THRESHOLD and change >= MIN_PROFIT_FOR_EXIT):
                    cur.execute("UPDATE trades SET exit_price=%s, status='CLOSED', close_time=%s WHERE symbol=%s", 
                               (curr_p, datetime.now().strftime('%H:%M:%S'), ot['symbol']))
                else:
                    cur.execute("UPDATE trades SET current_price=%s WHERE symbol=%s", (curr_p, ot['symbol']))
            conn.commit(); cur.close(); conn.close()
            
            await asyncio.sleep(20)
        except Exception as e:
            print(f"Loop Error: {e}"); await asyncio.sleep(15)

# ======================== 3. واجهة العرض (Dashboard) ========================

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY open_time DESC")
        opens = cur.fetchall()
        cur.execute("SELECT * FROM trades WHERE status = 'CLOSED' ORDER BY close_time DESC LIMIT 10")
        closeds = cur.fetchall()
        cur.close(); conn.close()
        
        html = """
        <!DOCTYPE html><html><head><meta http-equiv="refresh" content="15">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; padding: 20px; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; background: #1e2329; }
            th, td { padding: 12px; border-bottom: 1px solid #2b3139; text-align: left; }
            .profit { color: #0ecb81; } .loss { color: #f6465d; }
        </style></head><body>
            <h2>📊 صفقات البوت المفتوحة</h2>
            <table><tr><th>العملة</th><th>الدخول</th><th>السعر الحالي</th><th>الربح</th></tr>
            {% for t in opens %}
            <tr><td>{{ t.symbol }}</td><td>{{ t.entry_price }}</td><td>{{ t.current_price }}</td>
            <td class="{{ 'profit' if t.current_price >= t.entry_price else 'loss' }}">
            {{ "%.2f"|format(((t.current_price-t.entry_price)/t.entry_price)*100) }}%</td></tr>
            {% endfor %}</table>
            <h2>✅ آخر الصفقات المغلقة</h2>
            <table><tr><th>العملة</th><th>النتيجة</th><th>الوقت</th></tr>
            {% for t in closeds %}
            <tr><td>{{ t.symbol }}</td><td class="{{ 'profit' if t.exit_price >= t.entry_price else 'loss' }}">
            {{ "%.2f"|format(((t.exit_price-t.entry_price)/t.entry_price)*100) }}%</td><td>{{ t.close_time }}</td></tr>
            {% endfor %}</table>
        </body></html>
        """
        return render_template_string(html, opens=opens, closeds=closeds)
    except Exception as e: return f"خطأ في عرض البيانات: {e}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_engine())
