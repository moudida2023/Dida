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

# نظام التخزين المحدث ليشمل السعر الحالي والوقت
SYSTEM_STATE = {
    'history': [],      
    'trades': {},       
    'last_update': "جاري المزامنة..."
}

TABLE_SCORE = 50   
TRADE_SCORE = 85   

# ======================== 2. لوحة التحكم (التصميم المطور) ========================

@app.route('/')
def home():
    with data_lock:
        current_history = list(SYSTEM_STATE['history'])
        last_sync = SYSTEM_STATE['last_update']

    history_rows = ""
    for item in reversed(current_history[-40:]):
        # حساب نسبة التغير بين سعر الدخول والسعر الحالي
        entry_p = item['entry_price']
        live_p = item.get('current_price', entry_p)
        change = ((live_p - entry_p) / entry_p) * 100
        color = "#00ff00" if change >= 0 else "#ff4444"
        
        history_rows += f"""
        <tr>
            <td>{item['entry_time']}</td>
            <td><b>{item['sym']}</b></td>
            <td style="color:#f0b90b;">{item['score']}</td>
            <td>{entry_p:.6f}</td>
            <td>{live_p:.6f}</td>
            <td style="color:{color}; font-weight:bold;">{change:+.2f}%</td>
        </tr>"""

    return f"""
    <html><head><meta http-equiv="refresh" content="15"><style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; text-align: center; padding: 20px; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e2329; margin-bottom: 30px; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }}
        th, td {{ padding: 12px; border: 1px solid #2b3139; text-align: center; }}
        th {{ background: #2b3139; color: #f0b90b; text-transform: uppercase; font-size: 0.9em; }}
        .header {{ background: #1e2329; padding: 15px; border-bottom: 3px solid #f0b90b; border-radius: 10px; margin-bottom: 20px; }}
        .live-indicator {{ color: #00ff00; font-weight: bold; animation: blink 1s infinite; }}
        @keyframes blink {{ 0% {{opacity: 1;}} 50% {{opacity: 0.3;}} 100% {{opacity: 1;}} }}
    </style></head><body>
        <div class="header">
            <h1>🎯 Sniper Tracker v23</h1>
            <p>تزامن السيرفر: <span class="live-indicator">● LIVE</span> | تحديث: {last_sync}</p>
        </div>

        <h3>🏆 رادار الفرص المكتشفة وتتبع الأداء</h3>
        <table>
            <thead>
                <tr>
                    <th>وقت الرصد</th>
                    <th>العملة</th>
                    <th>السكور</th>
                    <th>سعر الدخول</th>
                    <th>السعر الحالي</th>
                    <th>نسبة التغير %</th>
                </tr>
            </thead>
            <tbody>
                {history_rows if history_rows else "<tr><td colspan='6'>جاري مسح السوق وتحديث الأسعار...</td></tr>"}
            </tbody>
        </table>
    </body></html>"""

# ======================== 3. محرك التحليل والمزامنة ========================

async def calculate_score_v23(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=210)
        df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
        score = 0
        curr_p = df['close'].iloc[-1]

        # 1. البولنجر (40)
        std = df['close'].rolling(20).std(); ma20 = df['close'].rolling(20).mean()
        if ((4 * std) / (ma20 + 1e-9)).iloc[-1] < 0.05: score += 40
        # 2. المتوسطات 200/21/9 (20)
        ma9 = df['close'].rolling(9).mean().iloc[-1]; ma21 = df['close'].rolling(21).mean().iloc[-1]; ma200 = df['close'].rolling(200).mean().iloc[-1]
        if curr_p > ma200: score += 10
        if ma9 > ma21 and curr_p > ma9: score += 10
        # 3. السيولة (20) + RSI (20)
        if df['vol'].iloc[-1] > df['vol'].rolling(20).mean().iloc[-1] * 1.2: score += 20
        delta = df['close'].diff(); g = delta.where(delta>0,0).rolling(14).mean(); l = -delta.where(delta<0,0).rolling(14).mean()
        rsi = 100 - (100 / (1 + (g/(l+1e-9)))).iloc[-1]
        if 50 < rsi < 70: score += 20
        
        return int(score), curr_p
    except: return 0, 0

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                score, price = await calculate_score_v23(sym)
                
                with data_lock:
                    SYSTEM_STATE['last_update'] = datetime.now().strftime('%H:%M:%S')
                    
                    # تحديث السعر الحالي للعملات الموجودة مسبقاً في الجدول
                    for item in SYSTEM_STATE['history']:
                        if item['sym'] == sym:
                            item['current_price'] = price

                    # إضافة عملة جديدة للرادار
                    if score >= TABLE_SCORE:
                        if sym not in [x['sym'] for x in SYSTEM_STATE['history'][-20:]]:
                            SYSTEM_STATE['history'].append({
                                'sym': sym, 
                                'score': score, 
                                'entry_price': price, 
                                'current_price': price,
                                'entry_time': SYSTEM_STATE['last_update']
                            })
                            if len(SYSTEM_STATE['history']) > 50: SYSTEM_STATE['history'].pop(0)

                    # إرسال تلجرام
                    if score >= TRADE_SCORE and sym not in SYSTEM_STATE['trades']:
                        SYSTEM_STATE['trades'][sym] = {'entry': price, 'score': score}
                        send_telegram(f"🚀 *إشارة دخول v23:*\nالعملة: {sym}\nالسكور: {score}\nالسعر: {price}")
                
                await asyncio.sleep(0.04)
            await asyncio.sleep(300)
        except Exception as e:
            print(f"Error: {e}"); await asyncio.sleep(60)

def send_telegram(msg):
    for cid in DESTINATIONS:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"})
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
