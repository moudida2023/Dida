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

# الإعدادات المطلوبة
MAX_OPEN_TRADES = 20
ENTRY_SCORE = 70      # السكور المطلوب للصيد الحقيقي
INVESTMENT = 50.0
data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        self.open_trades = self.load_from_disk()
        self.last_sync = "بدء المسح الحقيقي..."
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

# ======================== محرك التحليل الفني الصارم ========================

async def get_real_score(sym):
    try:
        # جلب بيانات حقيقية (ساعة واحدة)
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=50)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        close = df['c']
        score = 0
        
        # 1. انضغاط بولنجر (40 نقطة)
        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bandwidth = ((ma20 + (2 * std20)) - (ma20 - (2 * std20))) / ma20
        if bandwidth.iloc[-1] < 0.05: score += 40
            
        # 2. مؤشر RSI (20 نقطة)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 45 < rsi.iloc[-1] < 70: score += 20
            
        # 3. قوة الحجم (20 نقطة)
        if df['v'].iloc[-1] > df['v'].mean() * 1.2: score += 20
            
        # 4. الاتجاه الصاعد (20 نقطة)
        if close.iloc[-1] > close.rolling(20).mean().iloc[-1]: score += 20

        return int(score), close.iloc[-1]
    except:
        return 0, 0

# ======================== المحرك الرئيسي للكتابة ========================

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            scanned = 0
            for sym in symbols:
                scanned += 1
                with data_lock: state.total_scanned = scanned
                
                # جلب السكور الحقيقي
                score, price = await get_real_score(sym)
                
                with data_lock:
                    # تحديث أسعار الصفقات المكتوبة حالياً في الموقع
                    for tr in state.open_trades:
                        if tr['sym'] in tickers:
                            tr['current_price'] = tickers[tr['sym']]['last']

                    # إذا وجدت فرصة حقيقية (سكور 70+)، اكتبها فوراً
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
                                print(f"📍 تم صيد عملة حقيقية: {sym} بسكور {score}")

                await asyncio.sleep(0.02) # سرعة متوازنة للمسح

            with data_lock: state.last_sync = datetime.now().strftime('%H:%M:%S')
            await asyncio.sleep(60) # راحة دقيقة بين المسحات
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(30)

# ======================== واجهة العرض النهائية ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        sync = state.last_sync
        count = state.total_scanned
    
    rows = ""
    for t in reversed(active):
        pnl_pct = ((t['current_price'] - t['entry_price']) / t['entry_price']) * 100
        pnl_usd = (pnl_pct / 100) * t['investment']
        color = "#00ff00" if pnl_pct >= 0 else "#ff4444"
        
        rows += f"""<tr style="border-bottom: 1px solid #2b3139; height: 50px;">
            <td>{t['time']}</td>
            <td><b style="color:#f0b90b;">{t['sym']}</b></td>
            <td><span style="background:#2b3139; padding:3px 8px; border-radius:5px;">{t['score']}</span></td>
            <td>{t['entry_price']:.4f}</td>
            <td>{t['current_price']:.4f}</td>
            <td style="color:{color}; font-weight:bold;">{pnl_pct:+.2f}% (${pnl_usd:+.2f})</td>
        </tr>"""
    
    return f"""<html><head><meta http-equiv="refresh" content="10"><title>رادار الصفقات الحقيقي</title></head>
    <body style="background:#0b0e11; color:#eaecef; font-family:sans-serif; padding:20px;">
        <div style="max-width:1000px; margin:auto; background:#1e2329; border-radius:12px; padding:25px; border-top: 6px solid #f0b90b; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
            <h2 style="margin-top:0;">📡 رادار الصفقات المباشر (v51)</h2>
            <div style="display:flex; justify-content:space-between; background:#2b3139; padding:10px 15px; border-radius:8px; margin-bottom:20px; font-size:0.9em;">
                <span>⚙️ فحص السوق: <b>{count} عملة</b></span>
                <span>⏱️ تحديث: <b>{sync}</b></span>
                <span style="color:#00ff00;">● متصل بباينانس</span>
            </div>
            <table style="width:100%; border-collapse:collapse; text-align:center;">
                <thead><tr style="color:#848e9c; text-transform:uppercase; font-size:0.8em;">
                    <th>الوقت</th><th>الزوج</th><th>السكور</th><th>الدخول</th><th>الحالي</th><th>الربح/الخسارة</th>
                </tr></thead>
                <tbody>{rows if rows else "<tr><td colspan='6' style='padding:40px; color:#848e9c;'>جاري مسح السوق... الصفقات الحقيقية ستظهر هنا فور رصدها.</td></tr>"}</tbody>
            </table>
            <div style="margin-top:20px; font-size:0.8em; color:#848e9c;">* ميزانية كل صفقة افتراضية: $50.00</div>
        </div>
    </body></html>"""

@app.route('/database')
def view_db():
    if os.path.exists(DB_FILE): return send_file(DB_FILE, mimetype='application/json')
    return "[]"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
