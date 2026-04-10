import asyncio
import ccxt.pro as ccxt
import pandas as pd
import sqlite3
import os
import threading
from flask import Flask
from datetime import datetime

# ======================== 1. إعداد قاعدة البيانات ========================
app = Flask(__name__)
DB_PATH = "/tmp/test_radar_v103.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS signals") # مسح البيانات القديمة عند كل تشغيل للتجربة
        conn.execute('''CREATE TABLE signals 
            (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, score INTEGER, time TEXT)''')
    print("⚠️ نظام التجربة جاهز: سيتم رصد العملات بسرعة الآن.")

init_db()
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# ======================== 2. محرك الفحص السريع ========================

async def fast_analyze(sym):
    try:
        # لجعل التجربة سريعة، سنأخذ السعر الحالي ونعطي سكور عشوائي فوق 10
        ticker = await EXCHANGE.fetch_ticker(sym)
        price = ticker['last']
        change = ticker['percentage']
        
        # سكور تجريبي: أي عملة تتحرك ولو قليلاً ستحصل على سكور
        test_score = 50 if abs(change) > 0.1 else 15
        return test_score, price
    except: return 0, 0

async def main_engine():
    while True:
        try:
            # سنفحص أول 20 عملة فقط لتكون النتائج فورية
            tickers = await EXCHANGE.fetch_tickers()
            all_symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s][:30]
            
            for sym in all_symbols:
                current_price = tickers[sym]['last']
                
                # تحديث الأسعار في SQL
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("UPDATE signals SET current_price = ? WHERE symbol = ?", (current_price, sym))
                
                # إضافة عملات جديدة بسرعة (سكور منخفض للتجربة)
                score, entry_price = await fast_analyze(sym)
                
                if score >= 10: # شرط سهل جداً للتأكد من عمل الكود
                    now = datetime.now().strftime('%H:%M:%S')
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute('''INSERT OR IGNORE INTO signals (symbol, entry_price, current_price, score, time) 
                                      VALUES (?, ?, ?, ?, ?)''', (sym, entry_price, current_price, score, now))
                
                await asyncio.sleep(0.01)
            
            await asyncio.sleep(5) # تحديث سريع كل 5 ثوانٍ
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(5)

# ======================== 3. الموقع التجريبي ========================

@app.route('/')
def test_dashboard():
    rows = ""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT * FROM signals ORDER BY time DESC")
        for r in cursor:
            pnl = ((r[2] - r[1]) / r[1] * 100)
            pnl_color = "#00ff00" if pnl >= 0 else "#ff4444"
            rows += f"""
            <tr style="border-bottom: 1px solid #2b3139;">
                <td style="color:#f0b90b; font-weight:bold; padding:12px;">{r[0]}</td>
                <td>{r[1]:.4f}</td>
                <td style="color:{pnl_color};">{r[2]:.4f}</td>
                <td><b style="color:#f0b90b;">{r[3]}</b></td>
                <td style="font-size:0.8em; color:#848e9c;">{r[4]}</td>
            </tr>"""

    return f"""
    <html><head><meta http-equiv="refresh" content="5">
    <style>
        body {{ background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 20px; }}
        .box {{ max-width: 800px; margin: auto; background: #1e2329; padding: 20px; border-radius: 10px; border: 2px solid #f0b90b; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        th {{ color: #848e9c; padding: 10px; border-bottom: 2px solid #2b3139; }}
        td {{ padding: 10px; }}
    </style></head><body>
        <div class="box">
            <h2>🧪 وضع الاختبار التجريبي (Test Mode)</h2>
            <p style="color:#00ff00;">إذا ظهرت عملات بالأسفل، فإن الكود يعمل بشكل سليم!</p>
            <table>
                <thead><tr><th>العملة</th><th>الدخول</th><th>الحالي</th><th>السكور</th><th>التوقيت</th></tr></thead>
                <tbody>{rows if rows else "<tr><td colspan='5'>جاري ملء الجدول فوراً...</td></tr>"}</tbody>
            </table>
        </div>
    </body></html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_engine())
