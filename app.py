import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import json
import time
from flask import Flask, send_file
from datetime import datetime

app = Flask('')
DB_FILE = "/tmp/database.json"
EXCHANGE = ccxt.binance({'enableRateLimit': True})

data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        self.high_score_list = []
        self.last_db_fill = "انتظار..."
        # حقن بيانات وهمية فوراً للتأكد من أن الملف يعمل
        self.high_score_list.append({
            "sym": "STARTUP/CHECK", "score": 100, "price": 0, "time": datetime.now().strftime('%H:%M:%S')
        })
        self.remplir_DB()

    def remplir_DB(self):
        with data_lock:
            try:
                with open(DB_FILE, 'w') as f:
                    json.dump(self.high_score_list, f, indent=4)
                self.last_db_fill = datetime.now().strftime('%H:%M:%S')
                print(f"✅ تم التحديث بنجاح: {self.last_db_fill}")
            except Exception as e:
                print(f"❌ خطأ كتابة: {e}")

state = PersistentState()

async def main_engine():
    while True:
        try:
            # جلب البيانات الأساسية مرة واحدة لكل دورة
            tickers = await EXCHANGE.fetch_tickers()
            all_symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            symbols = all_symbols[:100] # أول 100 فقط
            
            for sym in symbols:
                # إضافة تأخير 0.1 ثانية لمنع الحظر وتخفيف الضغط على المعالج
                await asyncio.sleep(0.1) 
                
                # تحليل مبسط جداً لضمان السرعة
                change = tickers[sym].get('percentage', 0)
                score = 70 if change > 1 else 0 # سكور سهل جداً (أي صعود > 1%)
                
                if score >= 60:
                    with data_lock:
                        if not any(t['sym'] == sym for t in state.high_score_list):
                            state.high_score_list.append({
                                'sym': sym, 'score': score, 
                                'price': tickers[sym]['last'],
                                'time': datetime.now().strftime('%H:%M:%S')
                            })
                            state.remplir_DB()
            
            await asyncio.sleep(10) # راحة بين الدورات
        except Exception as e:
            print(f"⚠️ خطأ محرك: {e}")
            await asyncio.sleep(10)

@app.route('/')
def home():
    return f"<h2>المحرك يعمل!</h2><p>آخر ترحيل: {state.last_db_fill}</p><a href='/database'>عرض البيانات</a>"

@app.route('/database')
def view_db():
    return send_file(DB_FILE) if os.path.exists(DB_FILE) else "[]"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # تفعيل المزامنة الدورية كل دقيقة
    threading.Thread(target=lambda: (time.sleep(60), state.remplir_DB()), daemon=True).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
