import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات والربط ========================
app = Flask('')
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

data_lock = threading.Lock()

SYSTEM_STATE = {
    'open_trades': [],   
    'closed_trades': [], 
    'radar_70': [],      # الجدول الجديد للعملات 70+
    'last_full_sync': "جاري التحميل..."
}

# العتبات (Thresholds)
RADAR_SCORE = 70   
TRADE_SCORE = 85   

# ======================== 2. لوحة التحكم المطورة ========================

@app.route('/')
def home():
    with data_lock:
        open_list = list(SYSTEM_STATE['open_trades'])
        closed_list = list(SYSTEM_STATE['closed_trades'])
        radar_list = list(SYSTEM_STATE['radar_70'])
        sync_time = SYSTEM_STATE['last_full_sync']

    # جدول الصفقات المفتوحة
    open_rows = ""
    for tr in reversed(open_list):
        change = ((tr['current_price'] - tr['entry_price']) / tr['entry_price']) * 100
        color = "#00ff00" if change >= 0 else "#ff4444"
        open_rows += f"<tr><td>{tr['time']}</td><td><b>{tr['sym']}</b></td><td>{tr['entry_price']:.6f}</td><td>{tr['current_price']:.6f}</td><td style='color:{color}; font-weight:bold;'>{change:+.2f}%</td></tr>"

    # جدول الرادار (70+) - الجديد
    radar_rows = ""
    for r in reversed(radar_list[-15:]):
        radar_rows += f"<tr><td>{r['time']}</td><td>{r['sym']}</td><td style='color:#f0b90b;'>{r['score']}</td><td>{r['price']:.6f}</td></tr>"

    # جدول الصفقات المغلقة
    closed_rows = ""
    for tr in reversed(closed_list[-10:]):
        color = "#00ff00" if tr['final_pnl'] >= 0 else "#ff4444"
        closed_rows += f"<tr><td>{tr['exit_time']}</td><td>{tr['sym']}</td><td>{tr['final_pnl']:+.2f}%</td></tr>"

    return f"""
    <html><head><meta http-equiv="refresh" content="20"><style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; text-align: center; padding: 10px; }}
        .container {{ max-width: 1100px; margin: auto; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e2329; margin-bottom: 20px; border-radius: 8px; overflow: hidden; }}
        th, td {{ padding: 10px; border: 1px solid #2b3139; text-align: center; }}
        th {{ background: #2b3139; color: #f0b90b; }}
        h2 {{ color: #f0b90b; text-align: left; border-left: 4px solid #f0b90b; padding-left: 10px; margin-top: 30px; }}
        .header-box {{ background: #1e2329; padding: 10px; border-bottom: 3px solid #f0b90b; border-radius: 10px; }}
    </style></head><body>
        <div class="container">
            <div class="header-box">
                <h1>🚀 Sniper Multi-Tracker v25</h1>
                <p>آخر تحديث شامل: <span style="color:#00ff00;">{sync_time}</span></p>
            </div>

            <h2>🟢 صفقات نشطة (85+)</h2>
            <table>
                <thead><tr><th>وقت الدخول</th><th>العملة</th><th>الدخول</th><th>الحالي</th><th>PNL%</th></tr></thead>
                <tbody>{open_rows if open_rows else "<tr><td colspan='5'>لا توجد صفقات مفتوحة</td></tr>"}</tbody>
            </table>

            <h2>📡 رادار المراقبة (70+)</h2>
            <table>
                <thead><tr><th>وقت الرصد</th><th>العملة</th><th>السكور</th><th>السعر</th></tr></thead>
                <tbody>{radar_rows if radar_rows else "<tr><td colspan='4'>جاري البحث عن عملات قوية...</td></tr>"}</tbody>
            </table>

            <h2>🔴 سجل النتائج الأخيرة</h2>
            <table>
                <thead><tr><th>الوقت</th><th>العملة</th><th>النتيجة</th></tr></thead>
                <tbody>{closed_rows if closed_rows else "<tr><td colspan='3'>لا توجد عمليات مغلقة</td></tr>"}</tbody>
            </table>
        </div>
    </body></html>"""

# ======================== 3. المحرك الفني والمزامنة ========================

async def calculate_logic_v25(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=100)
        df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
        score = 0
        curr_p = df['close'].iloc[-1]
        
        # 1. بولنجر (40)
        std = df['close'].rolling(20).std(); ma20 = df['close'].rolling(20).mean()
        if ((4 * std) / (ma20 + 1e-9)).iloc[-1] < 0.05: score += 40
        # 2. متوسطات (20)
        ma9 = df['close'].rolling(9).mean().iloc[-1]; ma200 = df['close'].rolling(200).mean().iloc[-1]
        if curr_p > ma200: score += 10
        if curr_p > ma9: score += 10
        # 3. سيولة (20) + RSI (20)
        if df['vol'].iloc[-1] > df['vol'].rolling(20).mean().iloc[-1]: score += 20
        delta = df['close'].diff(); g = delta.where(delta>0,0).rolling(14).mean(); l = -delta.where(delta<0,0).rolling(14).mean()
        rsi = 100 - (100 / (1 + (g/(l+1e-9)))).iloc[-1]
        if 50 < rsi < 70: score += 20
        
        return int(score), curr_p
    except: return 0, 0

async def scanner_loop():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                score, price = await calculate_logic_v25(sym)
                
                with data_lock:
                    SYSTEM_STATE['last_full_sync'] = datetime.now().strftime('%H:%M:%S')

                    # تحديث أسعار المفتوح
                    for tr in SYSTEM_STATE['open_trades']:
                        if tr['sym'] == sym:
                            tr['current_price'] = price
                            pnl = ((price - tr['entry_price']) / tr['entry_price']) * 100
                            if pnl >= 3.0 or pnl <= -2.0:
                                SYSTEM_STATE['closed_trades'].append({'sym':sym,'final_pnl':pnl,'exit_time':SYSTEM_STATE['last_full_sync']})
                                SYSTEM_STATE['open_trades'].remove(tr)

                    # إضافة للرادار (70+)
                    if score >= RADAR_SCORE:
                        if sym not in [x['sym'] for x in SYSTEM_STATE['radar_70'][-15:]]:
                            SYSTEM_STATE['radar_70'].append({'sym':sym, 'score':score, 'price':price, 'time':SYSTEM_STATE['last_full_sync']})
                            if len(SYSTEM_STATE['radar_70']) > 30: SYSTEM_STATE['radar_70'].pop(0)

                    # دخول صفقة (85+)
                    if score >= TRADE_SCORE:
                        if sym not in [x['sym'] for x in SYSTEM_STATE['open_trades']]:
                            SYSTEM_STATE['open_trades'].append({'sym':sym, 'entry_price':price, 'current_price':price, 'time':SYSTEM_STATE['last_full_sync']})
                            send_telegram(f"✅ دخول صفقة: {sym} (السكور: {score})")

                await asyncio.sleep(0.04)
            await asyncio.sleep(300)
        except Exception as e:
            print(f"Error: {e}"); await asyncio.sleep(60)

def send_telegram(msg):
    for cid in DESTINATIONS:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": cid, "text": msg})
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(scanner_loop())
