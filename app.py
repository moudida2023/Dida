import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
import json
from flask import Flask, send_file
from datetime import datetime

app = Flask('')
EXCHANGE = ccxt.binance({'enableRateLimit': True})
DB_FILE = "database.json"

# إعدادات مخففة جداً لضمان العمل الآن
MAX_OPEN_TRADES = 20
ENTRY_SCORE = 50 # سكور منخفض جداً للتأكد من امتلاء الجدول
INVESTMENT = 50.0
data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        self.open_trades = self.load_from_disk()
        self.last_sync = "بدء المسح..."
        self.total_scanned = 0

    def load_from_disk(self):
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, 'r') as f: return json.load(f)
            except: return []
        return []

    def save_to_disk(self):
        with open(DB_FILE, 'w') as f:
            json.dump(self.open_trades, f, indent=4)

state = PersistentState()

async def get_score_fast(sym):
    try:
        # جلب أقل عدد ممكن من الشمعات لتسريع السيرفر
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=30)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        last_price = df['c'].iloc[-1]
        
        # شرط بسيط جداً: إذا كانت الشمعة الحالية خضراء والسيولة موجودة
        score = 0
        if df['c'].iloc[-1] > df['o'].iloc[-1]: score += 30
        if df['v'].iloc[-1] > df['v'].mean(): score += 30
        if df['c'].iloc[-1] > df['c'].iloc[-5]: score += 20
        
        return score, last_price
    except: return 0, 0

async def main_engine():
    print("🚀 المحرك بدأ العمل الآن...")
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            print(f"🔍 تم العثور على {len(symbols)} عملة. بدأ الفحص...")
            
            scanned = 0
            for sym in symbols:
                scanned += 1
                with data_lock: state.total_scanned = scanned
                
                # جلب سكور سريع
                score, price = await get_score_fast(sym)
                
                with data_lock:
                    # تحديث الأسعار الحية دائماً
                    for tr in state.open_trades:
                        if tr['sym'] == sym: tr['current_price'] = tickers[sym]['last']

                    if score >= ENTRY_SCORE:
                        if not any(t['sym'] == sym for t in state.open_trades):
                            if len(state.open_trades) < MAX_OPEN_TRADES:
                                state.open_trades.append({
                                    'sym': sym, 'score': score, 
                                    'entry_price': price, 'current_price': price,
                                    'investment': INVESTMENT,
                                    'time': datetime.now().strftime('%H:%M:%S')
                                })
                                state.save_to_disk()
                                print(f"✅ تم إضافة عملة: {sym}")

                await asyncio.sleep(0.01) # تأخير بسيط لعدم حظر السيرفر

            with data_lock: state.last_sync = datetime.now().strftime('%H:%M:%S')
            print("✅ انتهت دورة المسح بنجاح.")
            await asyncio.sleep(60)
        except Exception as e:
            print(f"⚠️ خطأ في المحرك: {e}")
            await asyncio.sleep(30)

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        sync = state.last_sync
        count = state.total_scanned
    
    rows = "".join([f"<tr><td>{t['time']}</td><td><b>{t['sym']}</b></td><td>{t['score']}</td><td>{t['entry_price']:.6f}</td><td>{t['current_price']:.6f}</td><td>{((t['current_price']-t['entry_price'])/t['entry_price']*100):+.2f}%</td></tr>" for t in reversed(active)])
    
    return f"""<html><head><meta http-equiv="refresh" content="10"></head><body style="background:#0b0e11; color:white; font-family:sans-serif; padding:20px;">
        <div style="background:#1e2329; padding:20px; border-radius:10px; border-top:5px solid #f0b90b;">
            <h2>📊 رادار الطوارئ (v49)</h2>
            <p>يتم الآن فحص العملة: {count} | آخر تحديث: {sync}</p>
            <table border="1" style="width:100%; border-collapse:collapse; text-align:center;">
                <thead><tr><th>الوقت</th><th>الزوج</th><th>السكور</th><th>الدخول</th><th>الحالي</th><th>PNL%</th></tr></thead>
                <tbody>{rows if rows else "<tr><td colspan='6'>جاري البحث... انتظر دقيقة واحدة.</td></tr>"}</tbody>
            </table>
        </div></body></html>"""

@app.route('/database')
def view_db():
    if os.path.exists(DB_FILE): return send_file(DB_FILE, mimetype='application/json')
    return "[]"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
