import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import json
import time
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. الإعدادات والمسارات ========================
app = Flask('')
DB_FILE = "/tmp/database.json"
EXCHANGE = ccxt.binance({'enableRateLimit': True})

data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        # القائمة الأساسية (المصدر الوحيد للحقيقة)
        self.high_score_list = [] 
        self.last_db_fill = "انتظار..."
        
        # تصفير الملف عند البداية لضمان نظافة المسار
        self.clear_file_on_start()
        
        # إضافة صفقة "فحص النظام" للتأكد من أن الليست تعمل
        self.add_test_entry()

    def clear_file_on_start(self):
        try:
            with open(DB_FILE, 'w') as f:
                json.dump([], f)
            print("🧹 تم تنظيف ملف قاعدة البيانات للبدء من جديد.")
        except: pass

    def add_test_entry(self):
        test_data = {
            "sym": "SYSTEM/READY", 
            "score": 100, 
            "entry_price": 1.0, 
            "current_price": 1.0, 
            "time": datetime.now().strftime('%H:%M:%S'),
            "change": 0.0
        }
        self.high_score_list.append(test_data)
        self.remplir_DB()

    def remplir_DB(self):
        """الدالة المسؤولة عن تحويل الليست إلى JSON"""
        with data_lock:
            try:
                # التأكد من أن الليست ليست فارغة قبل الكتابة (اختياري)
                data_to_save = list(self.high_score_list)
                
                # تحويل آمن إلى نص JSON ثم الكتابة
                json_string = json.dumps(data_to_save, indent=4)
                
                with open(DB_FILE, 'w') as f:
                    f.write(json_string)
                    f.flush() # إجبار السيرفر على إفراغ الذاكرة في الملف
                    os.fsync(f.fileno()) # التأكد من الكتابة الفعلية على القرص
                
                self.last_db_fill = datetime.now().strftime('%H:%M:%S')
                print(f"✅ [SUCCESS] ترحيل {len(data_to_save)} عنصر إلى القاعدة.")
            except Exception as e:
                print(f"❌ [CRITICAL ERROR] فشل الكتابة: {e}")

state = PersistentState()

# ======================== 2. محرك الصيد المطور ========================

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s][:100]
            
            for sym in symbols:
                await asyncio.sleep(0.02)
                ticker = tickers[sym]
                current_price = ticker['last']
                
                with data_lock:
                    # تحديث العملات الموجودة فعلياً في الليست
                    for item in state.high_score_list:
                        if item['sym'] == sym:
                            item['current_price'] = current_price
                            item['change'] = ((current_price - item['entry_price']) / item['entry_price']) * 100

                    # شرط الإضافة (إذا تحقق السكور ولم تكن موجودة)
                    # سنستخدم سكور بسيط جداً (50) للتأكد من أن الإضافة تعمل
                    if ticker.get('percentage', 0) > 0.5: # أي عملة صاعدة بنسبة نصف بالمئة
                        if not any(t['sym'] == sym for t in state.high_score_list):
                            new_trade = {
                                'sym': sym,
                                'score': 60,
                                'entry_price': current_price,
                                'current_price': current_price,
                                'time': datetime.now().strftime('%H:%M:%S'),
                                'change': 0.0
                            }
                            state.high_score_list.append(new_trade)
                            state.remplir_DB() # حفظ فوري
            
            await asyncio.sleep(5)
        except Exception as e:
            print(f"⚠️ Engine Error: {e}")
            await asyncio.sleep(10)

# ======================== 3. واجهة المستخدم والمنافذ ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.high_score_list)
        last_fill = state.last_db_fill
    
    rows = ""
    for t in reversed(active):
        color = "#00ff00" if t.get('change', 0) >= 0 else "#ff4444"
        rows += f"""<tr style="border-bottom: 1px solid #2b3139;">
            <td style="padding:10px;">{t['time']}</td>
            <td style="color:#f0b90b;">{t['sym']}</td>
            <td>{t['entry_price']:.4f}</td>
            <td>{t['current_price']:.4f}</td>
            <td style="color:{color};">{t.get('change', 0):+.2f}%</td>
        </tr>"""

    return f"""<html><head><meta http-equiv="refresh" content="10"></head>
    <body style="background:#0b0e11; color:white; font-family:sans-serif; text-align:center; padding:20px;">
        <div style="max-width:800px; margin:auto; background:#1e2329; border-radius:15px; padding:20px; border:1px solid #363a45;">
            <h2>🛡️ نظام التحقق من البيانات v67</h2>
            <div style="background:#2b3139; padding:15px; border-radius:8px; margin-bottom:20px;">
                <p>حالة المزامنة: <b style="color:#00ff00;">{last_fill}</b></p>
                <p style="font-size:0.8em; color:#848e9c;">المسار النشط: {DB_FILE}</p>
            </div>
            <table style="width:100%; border-collapse:collapse;">
                <thead><tr style="color:#848e9c;"><th>الوقت</th><th>العملة</th><th>الدخول</th><th>الحالي</th><th>التغير</th></tr></thead>
                <tbody>{rows if rows else "<tr><td colspan='5'>جاري ملء القائمة...</td></tr>"}</tbody>
            </table>
            <br><a href="/database" style="color:#f0b90b; text-decoration:none;">📂 فتح الرابط المباشر للقاعدة</a>
        </div></body></html>"""

@app.route('/database')
def view_db():
    if os.path.exists(DB_FILE):
        return send_file(DB_FILE, mimetype='application/json')
    return "[]"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # ترحيل إجباري كل 30 ثانية لضمان استمرارية الملف
    threading.Thread(target=lambda: (time.sleep(30), state.remplir_DB()), daemon=True).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
