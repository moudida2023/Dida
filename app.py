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
CSV_FILE = "/tmp/test_scan_database.csv"
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# تم خفض السكور لـ 60 بناءً على طلبك للتجربة السريعة
TEST_SCORE_LIMIT = 60 

data_lock = threading.Lock()

class CSVManager:
    def __init__(self):
        self.headers = ['Time', 'Symbol', 'Score', 'Price', 'Change_24h']
        self._init_csv()

    def _init_csv(self):
        if not os.path.exists(CSV_FILE):
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.headers)
                # سطر لبدء الاختبار
                writer.writerow([datetime.now().strftime('%H:%M:%S'), 'TEST/START', 100, 0, 0])

    def append_trade(self, row):
        with data_lock:
            try:
                with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(row)
            except Exception as e:
                print(f"❌ CSV Write Error: {e}")

    def read_all(self):
        if not os.path.exists(CSV_FILE): return []
        try:
            df = pd.read_csv(CSV_FILE)
            return df.values.tolist()
        except: return []

csv_db = CSVManager()

# ======================== 2. محرك مسح السوق السريع ========================

async def main_engine():
    recorded_symbols = [] 
    
    while True:
        try:
            # جلب بيانات السوق بالكامل
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            print(f"🔄 بدأت دورة مسح شاملة لـ {len(symbols)} عملة...")

            for sym in symbols:
                await asyncio.sleep(0.02) # تسريع المسح قليلاً
                
                ticker = tickers[sym]
                price = ticker['last']
                change_24h = ticker.get('percentage', 0)
                
                # حساب سكور مبسط للتجربة (يعتمد على نسبة التغير اليومي)
                # إذا كانت العملة صاعدة بأكثر من 1.5% ستحصل على سكور 60+
                current_score = 70 if change_24h > 1.5 else 0
                
                if current_score >= TEST_SCORE_LIMIT:
                    if sym not in recorded_symbols:
                        row = [
                            datetime.now().strftime('%H:%M:%S'),
                            sym,
                            current_score,
                            price,
                            f"{change_24h:+.2f}%"
                        ]
                        csv_db.append_trade(row)
                        recorded_symbols.append(sym)
                        print(f"✅ تم صيد {sym} بسكور {current_score}")
            
            print("🏁 انتهت الدورة. استراحة 10 ثوانٍ...")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"⚠️ خطأ: {e}")
            await asyncio.sleep(10)

# ======================== 3. الواجهة المبسطة ========================

@app.route('/')
