import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات ========================
app = Flask('')
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# قائمة البيانات (المصدر الوحيد للحقيقة)
GLOBAL_DATA = {
    'history': [],      # سجل الرادار
    'trades': {},       # الصفقات المفتوحة
    'balance': 500.0,
    'last_scan': "لم يبدأ بعد"
}

TABLE_THRESHOLD = 50
TRADE_THRESHOLD = 85

# ======================== 2. لوحة التحكم ========================

@app.route('/')
def home():
    # بناء جدول الصفقات من GLOBAL_DATA مباشرة
    trades_rows = ""
    for sym, d in GLOBAL_DATA['trades'].items():
        pnl = ((d['current'] - d['entry']) / d['entry']) * 100
        trades_rows += f"<tr><td>{sym}</td><td>{d['entry']:.6f}</td><td>{d['current']:.6f}</td><td style='color:{'#00ff00' if pnl>=0 else '#ff4444'};'>{pnl:+.2f}%</td></tr>"

    # بناء جدول الرادار من GLOBAL_DATA مباشرة
    history_rows = ""
    for item in reversed(GLOBAL_DATA['history']):
        history_rows += f"<tr><td>{item['time']}</td><td><b>{item['sym']}</b></td><td style='color:#f0b90b;'>{item['score']}</td><td>{item['price']:.6f}</td></tr>"

    return f"""
    <html><head><meta http-equiv="refresh" content="20">
    <style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; text-align: center; padding: 20px; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e2329; margin-bottom: 30px; }}
        th, td {{ padding: 12px; border: 1px solid #2b3139; text-align: center; }}
        th {{ background: #2b3139; color: #f0b90b; }}
        .header {{ background: #1e2329; padding: 10px; border-radius: 8px; border-bottom: 3px solid #f0b90b; }}
    </style></head>
    <body>
        <div class="header"><h1>🚀 Sniper Dashboard v18</h1>
        <p>آخر فحص: {GLOBAL_DATA['last_scan']} | الرصيد: {GLOBAL_DATA['balance']:.2f} | الرادار: {len(GLOBAL_DATA['history'])}</p></div>
        
        <h3>💎 صفقات التلجرام النشطة</h3>
        <table><thead><tr><th>العملة</th><th>الدخول</th><th>الحالي</th><th>PNL%</th></tr></thead>
        <tbody>{trades_rows if trades_rows else "<tr><td colspan='4'>بانتظار إشارة تلجرام...</td></tr>"}</tbody></table>

        <h3>🏆 سجل رادار الاكتشاف</h3>
        <table><thead><tr><th>الوقت</th><th>العملة</th><th>السكور</th><th>السعر</th></tr></thead>
        <tbody>{history_rows if history_rows else "<tr><td colspan='4'>البوت يبحث الآن...</td></tr>"}</tbody></table>
    </body></html>"""

# ======================== 3. المحرك الفني ========================

async def analyze_coin(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=40)
        df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
        score = 0
        if df['close'].iloc[-1] > df['close'].ewm(span=200).mean().iloc[-1]: score += 40
        if df['vol'].iloc[-1] > df['vol'].rolling(20).mean().iloc[-1]: score += 30
        
        # RSI
        delta = df['close'].diff(); g = delta.where(delta>0,0).rolling(14).mean(); l = -delta.where(delta<0,0).rolling(14).mean()
        rsi = 100 - (100 / (1 + (g/(l+1e-9)))).iloc[-1]
        if 40 < rsi < 75: score += 30
        return int(score), df['close'].iloc[-1]
    except: return 0, 0

async def scanner_loop():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            GLOBAL_DATA['last_scan'] = datetime.now().strftime('%H:%M:%S')

            for sym in symbols:
                score, price = await analyze_coin(sym)
                
                # أي عملة تحقق السكور تضاف فوراً للرادار
                if score >= TABLE_THRESHOLD:
                    if sym not in [x['sym'] for x in GLOBAL_DATA['history'][-20:]]:
                        GLOBAL_DATA['history'].append({'sym': sym, 'score': score, 'price': price, 'time': datetime.now().strftime('%H:%M:%S')})
                        if len(GLOBAL_DATA['history']) > 50: GLOBAL_DATA['history'].pop(0)

                # أي عملة ترسل تلجرام تضاف فوراً لجدول الصفقات
                if score >= TRADE_THRESHOLD and sym not in GLOBAL_DATA['trades']:
                    GLOBAL_DATA['trades'][sym] = {'entry': price, 'current': price, 'score': score}
                    send_telegram(f"🚀 *إشارة دخول!*\nالعملة: {sym}\nالسكور: {score}")
                
                await asyncio.sleep(0.05)
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
    asyncio.get_event_loop().run_until_complete(scanner_loop())
