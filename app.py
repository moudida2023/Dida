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
CSV_FILE = "/tmp/final_market_scan.csv"
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# سكور 60 لسهولة التجربة (يمكنك رفعه لـ 85 لاحقاً)
SCORE_LIMIT = 60 

data_lock = threading.Lock()

class CSVManager:
    def __init__(self):
        self.headers = ['Time', 'Symbol', 'Score', 'Price', 'Change_24h']
        self._init_csv()

    def _init_csv(self):
        """إنشاء الملف وكتابة الرأس إذا لم يكن موجوداً"""
        if not os.path.exists(CSV_FILE):
            try:
                with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(self.headers)
                    # سطر اختباري للتأكد من الصلاحيات
                    writer.writerow([datetime.now().strftime('%H:%M:%S'), 'BOOT/OK', 100, 0, "0%"])
            except Exception as e:
                print(f"Error initializing CSV: {e}")

    def append_trade(self, row):
        """إضافة سطر جديد لقاعدة البيانات"""
        with data_lock:
            try:
                with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(row)
            except Exception as e:
                print(f"CSV Write Error: {e}")

    def read_all(self):
        """قراءة البيانات للعرض"""
        if not os.path.exists(CSV_FILE):
            return []
        try:
            df = pd.read_csv(CSV_FILE)
            return df.values.tolist()
        except:
            return []

csv_db = CSVManager()

# ======================== 2. محرك مسح السوق الشامل ========================

async def main_engine():
    recorded_symbols = set() # استخدام set لمنع التكرار بفعالية
    
    while True:
        try:
            # جلب أسعار جميع العملات
            tickers = await EXCHANGE.fetch_tickers()
            # تصفية أزواج USDT فقط
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            print(f"🔍 بدء مسح {len(symbols)} عملة...")

            for sym in symbols:
                await asyncio.sleep(0.02) # تأخير بسيط لمنع الحظر
                
                ticker = tickers[sym]
                price = ticker.get('last', 0)
                change = ticker.get('percentage', 0)
                
                # منطق السكور (أي عملة صاعدة > 1.2% تأخذ سكور 60)
                score = 70 if change > 1.2 else 0
                
                if score >= SCORE_LIMIT and sym not in recorded_symbols:
                    row = [
                        datetime.now().strftime('%H:%M:%S'),
                        sym,
                        score,
                        price,
                        f"{change:+.2f}%"
                    ]
                    csv_db.append_trade(row)
                    recorded_symbols.add(sym)
                    print(f"🎯 صيد: {sym} | سكور: {score}")

            print("✅ انتهت دورة المسح. استراحة 20 ثانية...")
            await asyncio.sleep(20)
        except Exception as e:
            print(f"⚠️ Engine Error: {e}")
            await asyncio.sleep(10)

# ======================== 3. واجهة الموقع (Flask) ========================

@app.route('/download')
def download_csv():
    """تحميل ملف قاعدة البيانات"""
    if os.path.exists(CSV_FILE):
        return send_file(CSV_FILE, as_attachment=True, mimetype='text/csv')
    return "File not found."

@app.route('/')
def home():
    """الصفحة الرئيسية لعرض الجدول"""
    data = csv_db.read_all()
    rows_html = ""
    
    # عرض آخر 25 عملة تم اصطيادها
    for row in reversed(data):
        if row[1] in ['Symbol', 'BOOT/OK']: continue
        
        # تلوين النسبة (أخضر للصعود، أحمر للهبوط)
        color = "#00ff00" if "+" in str(row[4]) else "#ff4444"
        
        rows_html += f"""
        <tr style="border-bottom: 1px solid #2b3139;">
            <td style="padding:12px;">{row[0]}</td>
            <td style="color:#f0b90b; font-weight:bold;">{row[1]}</td>
            <td style="color:#00ff00;">{row[2]}</td>
            <td>{row[3]}</td>
            <td style="color:{color}; font-weight:bold;">{row[4]}</td>
        </tr>"""

    return f"""
    <html>
    <head>
        <title>Market Scanner v71</title>
        <meta http-equiv="refresh" content="20">
        <style>
            body {{ background:#0b0e11; color:white; font-family:sans-serif; padding:20px; }}
            .container {{ max-width:900px; margin:auto; background:#1e2329; padding:20px; border-radius:15px; border:1px solid #363a45; }}
            table {{ width:100%; border-collapse:collapse; margin-top:20px; text-align:center; }}
            th {{ color:#848e9c; padding:10px; border-bottom:2px solid #2b3139; }}
            .header-flex {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; }}
            .btn {{ background:#f0b90b; color:black; padding:8px 15px; border-radius:5px; text-decoration:none; font-weight:bold; font-size:0.9em; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header-flex">
                <h2 style="margin:0;">📊 رادار المسح الشامل (CSV)</h2>
                <a href="/download" class="btn">📥 تحميل السجل الكامل</a>
            </div>
            <p style="color:#848e9c; font-size:0.9em;">يتم تحديث الجدول تلقائياً كل 20 ثانية. السكور الحالي: <b>{SCORE_LIMIT}</b></p>
            <table>
                <thead>
                    <tr><th>الوقت</th><th>العملة</th><th>السكور</th><th>السعر</th><th>تغير 24h</th></tr>
                </thead>
                <tbody>
                    {rows_html if rows_html else "<tr><td colspan='5' style='padding:40px; color:#444;'>جاري فحص السوق وتعبئة ملف CSV...</td></tr>"}
                </tbody>
            </table>
        </div>
    </body>
    </html>"""

# ======================== 4. التشغيل ========================

if __name__ == "__main
