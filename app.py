import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import csv
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. الإعدادات والمسارات ========================
app = Flask('')
CSV_FILE = "/tmp/trades_database.csv"
EXCHANGE = ccxt.binance({'enableRateLimit': True})

data_lock = threading.Lock()

class CSVManager:
    def __init__(self):
        self.headers = ['Time', 'Symbol', 'Entry_Price', 'Current_Price', 'Change_Pct']
        self._init_csv()

    def _init_csv(self):
        """إنشاء الملف وكتابة العناوين إذا لم يكن موجوداً"""
        if not os.path.exists(CSV_FILE):
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.headers)
                # إضافة سطر تجريبي للتأكد من نجاح الكتابة
                writer.writerow([datetime.now().strftime('%H:%M:%S'), 'CSV/START', 1.0, 1.0, 0.0])

    def append_trade(self, trade_list):
        """إضافة صفقة جديدة كسطر في نهاية ملف CSV"""
        with data_lock:
            try:
                with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(trade_list)
                print(f"📝 تم تدوين {trade_list[1]} في ملف CSV")
            except Exception as e:
                print(f"❌ خطأ كتابة CSV: {e}")

    def read_all(self):
        """قراءة الملف بالكامل لعرضه في الموقع"""
        if not os.path.exists(CSV_FILE): return []
        try:
            df = pd.read_csv(CSV_FILE)
            return df.values.tolist()
        except: return []

csv_db = CSVManager()

# ======================== 2. محرك الصيد السريع ========================

async def main_engine():
    # قائمة داخلية لمنع تكرار نفس العملة في الدورة الواحدة
    recorded_symbols = [] 
    
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s][:100]
            
            for sym in symbols:
                await asyncio.sleep(0.02)
                ticker = tickers[sym]
                price = ticker['last']
                change = ticker.get('percentage', 0)

                # إذا كانت العملة صاعدة بقوة ولم نسجلها بعد
                if change > 1.5 and sym not in recorded_symbols:
                    trade_data = [
                        datetime.now().strftime('%H:%M:%S'),
                        sym,
                        price,
                        price,
                        0.0
                    ]
                    csv_db.append_trade(trade_data)
                    recorded_symbols.append(sym)
            
            await asyncio.sleep(10)
        except Exception as e:
            print(f"⚠️ Engine Error: {e}")
            await asyncio.sleep(10)

# ======================== 3. واجهة العرض (قراءة من CSV) ========================

@app.route('/')
def home():
    data = csv_db.read_all()
    # ترتيب البيانات ليكون الأحدث في الأعلى (تجاهل سطر العناوين)
    rows_html = ""
    for row in reversed(data):
        if row[1] == 'Symbol': continue # تخطي العناوين
        color = "#00ff00" if float(row[4]) >= 0 else "#ff4444"
        rows_html += f"""
        <tr style="border-bottom: 1px solid #2b3139;">
            <td style="padding:10px;">{row[0]}</td>
            <td style="color:#f0b90b; font-weight:bold;">{row[1]}</td>
            <td>{float(row[2]):.4f}</td>
            <td>{float(row[3]):.4f}</td>
            <td style="color:{color};">{float(row[4]):+.2f}%</td>
        </tr>"""

    return f"""
    <html><head><meta http-equiv="refresh" content="15">
    <style>
        body {{ background:#0b0e11; color:white; font-family:sans-serif; padding:20px; }}
        .box {{ max-width:850px; margin:auto; background:#1e2329; padding:20px; border-radius:12px; border:1px solid #363a45; }}
        table {{ width:100%; border-collapse:collapse; margin-top:20px; text-align:center; }}
        th {{ color:#848e9c; padding:10px; border-bottom:2px solid #2b3139; }}
        .csv-link {{ color:#f0b90b; text-decoration:none; background:#2b3139; padding:5px 10px; border-radius:4px; }}
    </style>
    </head>
    <body>
        <div class="box">
            <h2 style="text-align:center;">📊 نظام تخزين CSV المستقر v68</h2>
            <div style="text-align:center; margin-bottom:20px;">
                <a href="/download" class="csv-link">📥 تحميل قاعدة البيانات CSV</a>
            </div>
            <table>
                <thead><tr><th>الوقت</th><th>العملة</th><th>الدخول</th><th>الحالي</th><th>التغير</th></tr></thead>
                <tbody>{rows_html if rows_html else "<tr><td colspan='5'>بانتظار البيانات...</td></tr>"}</tbody>
            </table>
        </div>
    </body></html>"""

@app.route('/download')
def download_file():
    if os.path.exists(CSV_FILE):
        return send_file(CSV_FILE, as_attachment=True, mimetype='text/csv')
    return "File not found"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
