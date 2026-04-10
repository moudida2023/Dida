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
MAX_OPEN_TRADES = 20
STRICT_SCORE = 85      # السكور المطلوب للنخبة
INVESTMENT = 10.0      # مبلغ الاستثمار لكل صفقة

data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        # قائمة العملات التي سكورها > 85
        self.high_score_list = [] 
        self.total_scanned = 0
        self.last_sync = "بدء..."
        self.last_db_fill = "جاري المراقبة..."
        
        # محاولة تحميل البيانات السابقة
        self.load_from_disk()

    def load_from_disk(self):
        try:
            if os.path.exists(DB_FILE):
                with open(DB_FILE, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list): self.high_score_list = data
        except: pass

    # الدالة الأساسية لنقل المعطيات إلى قاعدة البيانات
    def remplir_DB(self):
        with data_lock:
            try:
                with open(DB_FILE, 'w') as f:
                    json.dump(self.high_score_list, f, indent=4)
                self.last_db_fill = datetime.now().strftime('%H:%M:%S')
                print(f"✅ [ترحيل النخبة] تم حفظ {len(self.high_score_list)} صفقة بسكور 85+")
            except Exception as e:
                print(f"❌ خطأ ترحيل: {e}")

state = PersistentState()

# ======================== 2. محرك الصيد والتحليل ========================

async def get_strict_score(sym):
    try:
        # جلب بيانات OHLCV لتحليل السيولة والسعر
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=30)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        
        score = 0
        # شرط 1: صعود قوي (أعلى من متوسط آخر 5 شمعات)
        if df['c'].iloc[-1] > df['c'].iloc[-5:].mean(): score += 40
        # شرط 2: انفجار حجم التداول (Volume Spike)
        if df['v'].iloc[-1] > df['v'].mean() * 2: score += 50
        
        return score, df['c'].iloc[-1]
    except: return 0, 0

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                with data_lock: state.total_scanned += 1
                
                # جلب السكور بناءً على الشروط الصارمة
                score, price = await get_strict_score(sym)
                
                with data_lock:
                    # تحديث أسعار الصفقات الموجودة مسبقاً في القائمة
                    for tr in state.high_score_list:
                        if tr['sym'] == sym: tr['current_price'] = price

                    # الفلترة: فقط العملات التي سكورها أكثر من 85
                    if score >= STRICT_SCORE and len(state.high_score_list) < MAX_OPEN_TRADES:
                        if not any(t['sym'] == sym for t in state.high_score_list):
                            new_entry = {
                                'sym': sym, 
                                'score': score, 
                                'entry_price': price, 
                                'current_price': price,
                                'investment': INVESTMENT,
                                'time': datetime.now().strftime('%H:%M:%S')
                            }
                            # الإضافة للقائمة
                            state.high_score_list.append(new_entry)
                            # ترحيل فوري لقاعدة البيانات عند الصيد
                            state.remplir_DB()
                
                await asyncio.sleep(0.01)
            
            with data_lock: state.last_sync = datetime.now().strftime('%H:%M:%S')
            # ترحيل دوري في نهاية كل دورة مسح أيضاً
            state.remplir_DB()
            await asyncio.sleep(10)
        except: await asyncio.sleep(10)

# ======================== 3. واجهة الموقع ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.high_score_list)
        last_fill = state.last_db_fill
    
    rows = "".join([f"<tr style='border-bottom:1px solid #2b3139;'><td>{t['time']}</td><td><b style='color:#f0b90b;'>{t['sym']}</b></td><td style='color:#00ff00;'>{t['score']}</td><td>{t['current_price']:.4f}</td><td>${t['investment']}</td></tr>" for t in reversed(active)])

    return f"""<html><head><meta http-equiv="refresh" content="15"></head>
    <body style="background:#0b0e11; color:white; font-family:sans-serif; padding:20px;">
        <div style="max-width:900px; margin:auto; background:#1e2329; padding:25px; border-radius:15px; border:1px solid #363a45;">
            <h2 style="color:#f0b90b; margin:0;">💎 رادار النخبة (Score 85+)</h2>
            <p style="color:#848e9c; font-size:0.9em;">آخر ترحيل لملف JSON: <span style="color:#00ff00;">{last_fill}</span></p>
            
            <table style="width:100%; text-align:center; border-collapse:collapse; margin-top:20px;">
                <thead style="background:#2b3139; color:#848e9c;">
                    <tr><th>الوقت</th><th>العملة</th><th>السكور</th><th>السعر</th><th>الاستثمار</th></tr>
                </thead>
                <tbody>{rows if rows else "<tr><td colspan='5' style='padding:30px; color:#444;'>انتظار عملات تحقق شروط النخبة (85+)...</td></tr>"}</tbody>
            </table>
            
            <div style="margin-top:20px; text-align:center;">
                <a href="/database" target="_blank" style="color:#f0b90b; text-decoration:none; font-size:0.8em;">🔗 فتح قاعدة البيانات (JSON)</a>
            </div>
        </div></body></html>"""

@app.route('/database')
def view_db():
    return send_file(DB_FILE, mimetype='application/json') if os.path.exists(DB_FILE) else "[]"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # تشغيل الموقع والمحرك
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
