import asyncio
import ccxt.pro as ccxt
import sqlite3
import os
import threading
import requests
from flask import Flask, send_file
from datetime import datetime

app = Flask(__name__)

# إعداد قاعدة البيانات
DB_PATH = "/tmp/trading_bot.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS signals 
            (symbol TEXT PRIMARY KEY, time TEXT, entry REAL, current REAL, tp REAL, sl REAL, score INTEGER)''')

init_db()

TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# --- دالة الكتابة في قاعدة البيانات (بديلة للـ CSV) ---
def save_signal(symbol, price, score):
    tp, sl = price * 1.05, price * 0.97
    time_now = datetime.now().strftime('%H:%M:%S')
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # INSERT OR REPLACE تقوم بالتحديث إذا كانت العملة موجودة، أو الإضافة إذا كانت جديدة
            conn.execute('''INSERT OR REPLACE INTO signals (symbol, time, entry, current, tp, sl, score) 
                          VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                          (symbol, time_now, price, price, tp, sl, score))
        return True
    except Exception as e:
        print(f"DB Error: {e}")
        return False

# --- المحرك الرئيسي ---
async def market_engine():
    exchange = ccxt.binance({'enableRateLimit': True})
    sent_list = set()
    
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            for sym, data in tickers.items():
                if '/USDT' not in sym or 'UP/' in sym or 'DOWN/' in sym: continue
                
                price = data.get('last', 0)
                change = data.get('percentage', 0)
                score = 85 if change > 3 else (65 if change > 1.5 else 0)

                if score >= 60:
                    if save_signal(sym, price, score):
                        if score >= 85 and sym not in sent_list:
                            msg = f"🚀 إشارة: {sym}\n💰 دخول: {price}\n📊 سكور: {score}"
                            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                                          json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
                            sent_list.add(sym)
            await asyncio.sleep(15)
        except: await asyncio.sleep(10)

# --- عرض البيانات في الموقع ---
@app.route('/')
def home():
    rows = ""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute("SELECT * FROM signals ORDER BY time DESC LIMIT 20")
            for r in cursor:
                color = "#00ff00" if r[3] >= r[2] else "#ff4444"
                rows += f"""<tr style="border-bottom:1px solid #2b3139;">
                    <td style="color:#f0b90b; padding:12px;">{r[0]}</td>
                    <td>{r[1]}</td>
                    <td>{r[2]:.4f}</td>
                    <td style="color:{color};">{r[3]:.4f}</td>
                    <td>{r[6]}</td>
                </tr>"""
    except: pass

    return f"""<html><head><meta http-equiv="refresh" content="10">
    <style>body{{background:#0b0e11; color:white; font-family:sans-serif; text-align:center;}} table{{width:90%; margin:auto; background:#1e2329; border-collapse:collapse;}}</style>
    </head><body>
        <h2>📊 رادار التداول v94 (SQL Edition)</h2>
        <table>
            <thead><tr><th>الرمز</th><th>الوقت</th><th>دخول</th><th>حالي</th><th>السكور</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </body></html>"""

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    asyncio.get_event_loop().run_until_complete(market_engine())
