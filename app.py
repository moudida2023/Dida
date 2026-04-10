import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import csv
import time
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. الإعدادات والمسارات ========================
app = Flask(__name__)
CSV_FILE = "/tmp/market_scan_v73.csv"
EXCHANGE = ccxt.binance({'enableRateLimit': True})

SCORE_LIMIT = 60 
data_lock = threading.Lock()

class CSVManager:
    def __init__(self):
        # ترتيب الأعمدة الجديد
        self.headers = ['Symbol', 'Entry_Time', 'Entry_Price', 'Current_Price', 'Score']
        self._init_csv()

    def _init_csv(self):
        if not os.path.exists(CSV_FILE):
            try:
                with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(self.headers)
            except Exception as e:
                print(f"Error: {e}")

    def append_trade(self, row):
        with data_lock:
            try:
                with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(row)
            except Exception as e:
                print(f"CSV Error: {e}")

    def read_all(self):
        if not os.path.exists(CSV_FILE): return []
        try:
            df = pd.read_csv(CSV_FILE)
            return df.values.tolist()
        except: return []

csv_db = CSVManager()
current_prices_cache = {} # لتخزين الأسعار الحالية وتحديثها في الجدول

# ======================== 2. محرك مسح السوق ========================

async def main_engine():
    recorded_symbols = set()
    
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                await asyncio.sleep(0.01)
                ticker = tickers[sym]
                price = ticker.get('last', 0)
                change = ticker.get('percentage', 0)
                
                # تحديث الكاش للسعر الحالي لجميع العملات
                current_prices_cache[sym] = price
                
                # منطق السكور
                score = 75 if change > 1.5 else 0
                
                if score >= SCORE_LIMIT and sym not in recorded_symbols:
                    # [اسم العملة، وقت الدخول، سعر الدخول، السعر الحالي، السكور]
                    row = [
                        sym,
                        datetime.now().strftime('%H:%M:%S'),
                        price,
                        price,
                        score
                    ]
                    csv_db.append_trade(row)
                    recorded_symbols.add(sym)

            await asyncio.sleep(15)
        except Exception as e:
            print(f"⚠️ Engine Error: {e}")
            await asyncio.sleep(10)

# ======================== 3. واجهة الموقع المحدثة ========================

@app.route('/')
def home():
    data = csv_db.read_all()
    rows_html = ""
    
    for row in reversed(data):
        sym = row[0]
        entry_price = float(row[2])
        # جلب السعر الحالي من الكاش إذا كان متاحاً، وإلا استخدام السعر المخزن
        current_p = current_prices_cache.get(sym, float(row[3]))
        
        # تلوين السعر الحالي بناءً على الربح/الخسارة مقارنة بالدخول
        price_color = "#00ff00" if current_p >= entry_price else "#ff4444"
        
        rows_html += f"""
        <tr style="border-bottom: 1px solid #2b3139;">
            <td style="color:#f0b90b; font-weight:bold; padding:12px;">{sym}</td>
            <td>{row[1]}</td>
            <td>{entry_price:.4f}</td>
            <td style="color:{price_color}; font-weight:bold;">{current_p:.4f}</td>
            <td style="color:#00ff00;">{row[4]}</td>
        </tr>"""

    return f"""
    <html>
    <head>
        <title>Market Scanner v73</title>
        <meta http-equiv="refresh" content="10">
        <style>
            body {{ background:#0b0e11; color:white; font-family:sans-serif; padding:20px; }}
            .container {{ max-width:900px; margin:auto; background:#1e2329; padding:20px; border-radius:15px; border:1px solid #363a45; }}
            table {{ width:100%; border-collapse:collapse; margin-top:20px; text-align:center; }}
            th {{ color:#848e9c; padding:10px; border-bottom:2px solid #2b3139; font-size:0.9em; }}
            .header {{ display:flex; justify-content:space-between; align-items:center; }}
            .download-btn {{ color:#f0b90b; text-decoration:none; border:1px solid #f0b90b; padding:5px 10px; border-radius:5px; font-size:0.8em; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin:0;">📊 رادار المسح (CSV)</h2>
                <a href="/download" class="download-btn">📥 تحميل CSV</a>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>اسم العملة</th>
                        <th>وقت الدخول</th>
                        <th>سعر الدخول</th>
                        <th>السعر الحالي</th>
                        <th>السكور</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html if rows_html else "<tr><td colspan='5' style='padding:40px;'>جاري البحث عن صفقات...</td></tr>"}
                </tbody>
            </table>
        </div>
    </body>
    </html>"""

@app.route('/download')
def download():
    if os.path.exists(CSV_FILE):
        return send_file(CSV_FILE, as_attachment=True, mimetype='text/csv')
    return "File not found."

# ======================== 4. التشغيل النهائي ========================

if __name__ == "__main__":
    # تأكد من إغلاق كل شيء بشكل صحيح هنا
    port = int(os.environ.get("PORT", 8080))
    
    # تشغيل Flask
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    
    # تشغيل المحرك
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main_engine())
