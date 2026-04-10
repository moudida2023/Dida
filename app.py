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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.json")

EXCHANGE = ccxt.binance({'enableRateLimit': True})
MAX_OPEN_TRADES = 20
ENTRY_SCORE = 70      
INVESTMENT = 50.0
data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        # القائمة الأساسية (المحملة من القرص)
        self.open_trades = self.load_from_disk()
        # قائمة مؤقتة للصفقات الجديدة التي تنتظر الحفظ
        self.temp_buffer = [] 
        self.last_sync = "بدء النظام..."
        self.total_scanned = 0
        self.last_disk_save = datetime.now().strftime('%H:%M:%S')

    def load_from_disk(self):
        try:
            if os.path.exists(DB_FILE):
                with open(DB_FILE, 'r') as f:
                    data = json.load(f)
                    return data if isinstance(data, list) else []
        except: pass
        return []

    def save_to_disk(self):
        """ترحيل كل ما في الذاكرة إلى القرص الصلب"""
        with data_lock:
            try:
                # دمج الصفقات الجديدة مع القديمة (تجنب التكرار)
                all_trades = self.open_trades
                with open(DB_FILE, 'w') as f:
                    json.dump(all_trades, f, indent=4)
                self.last_disk_save = datetime.now().strftime('%H:%M:%S')
                print(f"💾 [الترحيل الدوري] تم حفظ {len(all_trades)} صفقة في قاعدة البيانات.")
            except Exception as e:
                print(f"❌ فشل الحفظ الدوري: {e}")

state = PersistentState()

# ======================== 2. وظيفة الحفظ المجدول ========================

def scheduled_save_worker():
    """هذه الوظيفة تعمل في خيط مستقل وتقوم بالحفظ كل 15 دقيقة"""
    while True:
        time.sleep(900) # الانتظار لمدة 15 دقيقة (900 ثانية)
        print("⏰ حان موعد الترحيل الدوري للبيانات...")
        state.save_to_disk()

# ======================== 3. المحرك الرئيسي ========================

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                with data_lock: state.total_scanned += 1
                
                # تحليل مبسط للسكور
                bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=30)
                df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
                score = 75 if df['c'].iloc[-1] > df['o'].iloc[-1] else 0 # مثال للتبسيط
                
                with data_lock:
                    # تحديث أسعار الصفقات الحية في الذاكرة فوراً
                    for tr in state.open_trades:
                        if tr['sym'] in tickers:
                            tr['current_price'] = tickers[tr['sym']]['last']

                    # إذا وجد صفقة، يضيفها للذاكرة (العرض الفوري)
                    if score >= ENTRY_SCORE:
                        if not any(t['sym'] == sym for t in state.open_trades):
                            if len(state.open_trades) < MAX_OPEN_TRADES:
                                state.open_trades.append({
                                    'sym': sym, 'score': score, 
                                    'entry_price': df['c'].iloc[-1], 
                                    'current_price': df['c'].iloc[-1],
                                    'investment': INVESTMENT,
                                    'time': datetime.now().strftime('%H:%M:%S')
                                })
                await asyncio.sleep(0.01)
            
            with data_lock: state.last_sync = datetime.now().strftime('%H:%M:%S')
            await asyncio.sleep(60)
        except: await asyncio.sleep(30)

# ======================== 4. واجهة العرض ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        sync = state.last_sync
        disk_save = state.last_disk_save
    
    rows = "".join([f"<tr><td>{t['time']}</td><td><b>{t['sym']}</b></td><td>{t['score']}</td><td>{t['current_price']:.4f}</td><td style='color:{'#00ff00' if t['current_price']>=t['entry_price'] else '#ff4444'};'>{((t['current_price']-t['entry_price'])/t['entry_price']*100):+.2f}%</td></tr>" for t in reversed(active)])
    
    html = f"""<html><body style="background:#0b0e11; color:white; font-family:sans-serif; padding:20px;">
        <div style="background:#1e2329; padding:20px; border-radius:10px; border-top:5px solid #f0b90b;">
            <h2>🚀 رادار التداول (نظام الترحيل 15 دقيقة)</h2>
            <div style="font-size:0.8em; color:#848e9c; margin-bottom:10px;">
                آخر تحديث للسوق: {sync} | <b>آخر حفظ في قاعدة البيانات: {disk_save}</b>
            </div>
            <table border="1" style="width:100%; border-collapse:collapse; text-align:center;">
                <thead><tr><th>الوقت</th><th>الزوج</th><th>السكور</th><th>السعر</th><th>الربح</th></tr></thead>
                <tbody>{rows if rows else "<tr><td colspan='5'>جاري البحث...</td></tr>"}</tbody>
            </table>
        </div></body></html>"""
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # 1. تشغيل خيط الحفظ المجدول (كل 15 دقيقة)
    threading.Thread(target=scheduled_save_worker, daemon=True).start()
    # 2. تشغيل السيرفر
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    # 3. تشغيل المحرك
    asyncio.get_event_loop().run_until_complete(main_engine())
