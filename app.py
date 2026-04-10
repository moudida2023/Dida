import asyncio
import ccxt.pro as ccxt
import pandas as pd
import sqlite3
import os
import threading
import requests
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات المستهدفة ========================
app = Flask(__name__)
DB_PATH = "test_mode_v117.db"
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=5)
    except: pass

def get_db_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with get_db_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS radar (symbol TEXT PRIMARY KEY, discovery_price REAL, current_price REAL, score INTEGER, discovery_time TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS trades (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, status TEXT, score INTEGER, open_time TEXT)")
        conn.commit()
init_db()

EXCHANGE = ccxt.gateio({'enableRateLimit': True})

# ======================== 2. محرك فحص سريع (شروط سهلة للاختبار) ========================
async def fast_test_analysis(sym):
    try:
        # جلب شموع قليلة جداً لسرعة التنفيذ
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=20)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # سكور تجريبي يعتمد فقط على تحرك السعر البسيط
        change = ((df['close'].iloc[-1] - df['open'].iloc[-1]) / df['open'].iloc[-1]) * 100
        score = 25 if change > 0 else 5 # إذا الشمعة خضراء السكور 25 (سيفتح صفقة فوراً)
        
        return int(score), df['close'].iloc[-1]
    except: return 0, 0

async def main_engine():
    print("🛠️ وضع الاختبار يعمل... ستصلك رسائل تلغرام الآن.")
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s][:50] # فحص أول 50 عملة لسرعة النتائج
            
            for sym in symbols:
                price = tickers[sym]['last']
                score, _ = await fast_test_analysis(sym)
                
                now_time = datetime.now().strftime('%H:%M:%S')
                conn = get_db_connection()

                # أي عملة سكورها > 10 تظهر في الرادار
                if score >= 10:
                    conn.execute("INSERT OR REPLACE INTO radar VALUES (?, ?, ?, ?, ?)", (sym, price, price, score, now_time))

                # أي عملة سكورها > 20 تفتح صفقة تجريبية
                if score >= 20:
                    cursor = conn.execute("INSERT OR IGNORE INTO trades VALUES (?, ?, ?, 'OPEN', ?, ?)", (sym, price, price, score, now_time))
                    if cursor.rowcount > 0:
                        send_telegram_msg(f"🧪 *تجربة:* تم فتح صفقة لعملة `{sym}` بسعر `{price}`")

                conn.commit()
                conn.close()
                await asyncio.sleep(0.1) # سرعة عالية في الفحص
            
            print("✅ دورة فحص سريعة انتهت.")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(5)

# ======================== 3. واجهة الموقع المبسطة ========================
@app.route('/')
def index():
    conn = get_db_connection()
    radar = conn.execute("SELECT * FROM radar ORDER BY score DESC").fetchall()
    trades = conn.execute("SELECT * FROM trades WHERE status = 'OPEN'").fetchall()
    conn.close()

    r_rows = "".join([f"<tr><td>{r[0]}</td><td>{r[3]}</td><td>{r[2]}</td></tr>" for r in radar])
    t_rows = "".join([f"<tr><td>{t[0]}</td><td>{t[1]}</td><td>{t[2]}</td></tr>" for t in trades])

    return f"""
    <html><head><meta http-equiv="refresh" content="5">
    <style>
        body {{ background:#121212; color:white; font-family:sans-serif; text-align:center; }}
        table {{ width:80%; margin:20px auto; border-collapse:collapse; background:#1e1e1e; }}
        th, td {{ padding:10px; border:1px solid #333; }}
        th {{ background:#f0b90b; color:black; }}
    </style></head><body>
        <h2>📡 رادار الاختبار (سكور منخفض للتدفق)</h2>
        <table><tr><th>العملة</th><th>السكور</th><th>السعر الحالي</th></tr>{r_rows}</table>
        <h2>🚀 صفقات تجريبية نشطة</h2>
        <table><tr><th>العملة</th><th>سعر الدخول</th><th>السعر الحالي</th></tr>{t_rows}</table>
    </body></html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_engine())
