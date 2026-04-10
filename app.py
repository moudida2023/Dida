import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات والبيانات ========================
app = Flask('')
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

EXCLUDE_LIST = [
    'TUSD/USDT', 'USDC/USDT', 'FDUSD/USDT', 'USDT/USDT', 'DAI/USDT', 
    'USDE/USDT', 'USDP/USDT', 'BUSD/USDT', 'AEUR/USDT', 'EUR/USDT',
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT', 
    'ADA/USDT', 'DOGE/USDT', 'TRX/USDT', 'DOT/USDT', 'LINK/USDT'
]

INITIAL_BALANCE = 500.0
CURRENT_BALANCE = 500.0
MAX_TRADES = 10
TRADE_AMOUNT = 50.0 
OPEN_TRADES = {}     
SEARCH_HISTORY = [] # قائمة لحفظ نتائج أفضل 5 عملات تاريخياً

# إعدادات التتبع
ACTIVATION_PCT = 0.03
CALLBACK_PCT = 0.015

# ======================== 2. لوحة التحكم (الموقع) ========================

@app.route('/')
def home():
    # 1. جدول الصفقات المفتوحة
    trades_html = ""
    for sym, data in OPEN_TRADES.items():
        pnl = ((data['current'] - data['entry']) / data['entry']) * 100
        color = "#00ff00" if pnl >= 0 else "#ff4444"
        trades_html += f"""
        <tr>
            <td>{sym}</td>
            <td>{data['entry']:.6f}</td>
            <td>{data['current']:.6f}</td>
            <td style="color: {color}; font-weight: bold;">{pnl:+.2f}%</td>
            <td>{data.get('score', 'N/A')}</td>
        </tr>"""
    
    # 2. جدول تاريخ أفضل العملات (أحدث 50 نتيجة)
    history_html = ""
    for item in reversed(SEARCH_HISTORY[-50:]):
        history_html += f"""
        <tr>
            <td>{item['time']}</td>
            <td>{item['sym']}</td>
            <td>{item['score']}</td>
            <td>{item['price']:.6f}</td>
        </tr>"""

    return f"""
    <html>
    <head>
        <title>Sniper Elite Dashboard</title>
        <meta http-equiv="refresh" content="30">
        <style>
            body {{ background: #0f0f0f; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; text-align: center; margin: 0; }}
            .container {{ padding: 20px; }}
            .header {{ background: #1a1a1a; padding: 20px; border-bottom: 2px solid #4CAF50; }}
            .stats-bar {{ display: flex; justify-content: space-around; background: #222; padding: 15px; margin-bottom: 20px; }}
            table {{ width: 90%; margin: 20px auto; border-collapse: collapse; background: #1a1a1a; box-shadow: 0 0 10px rgba(0,0,0,0.5); }}
            th, td {{ padding: 12px; border: 1px solid #333; }}
            th {{ background: #4CAF50; color: white; }}
            h2 {{ color: #4CAF50; margin-top: 40px; }}
            .status {{ color: #00ff00; font-size: 0.8em; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🚀 Sniper Elite Dashboard <span class="status">● LIVE</span></h1>
        </div>
        <div class="stats-bar">
            <div><strong>Balance:</strong> {CURRENT_BALANCE:.2f} USDT</div>
            <div><strong>Active Trades:</strong> {len(OPEN_TRADES)} / {MAX_TRADES}</div>
            <div><strong>Last Update:</strong> {datetime.now().strftime('%H:%M:%S')}</div>
        </div>
        
        <div class="container">
            <h2>💎 الصفقات المفتوحة حالياً</h2>
            <table>
                <thead><tr><th>العملة</th><th>سعر الدخول</th><th>السعر الحالي</th><th>الربح/الخسارة</th><th>السكور</th></tr></thead>
                <tbody>{trades_html if trades_html else "<tr><td colspan='5'>لا توجد صفقات</td></tr>"}</tbody>
            </table>

            <h2>🏆 سجل أفضل العملات المكتشفة (History)</h2>
            <table>
                <thead><tr><th>الوقت</th><th>العملة</th><th>السكور</th><th>السعر عند البحث</th></tr></thead>
                <tbody>{history_html if history_html else "<tr><td colspan='4'>جاري المسح...</td></tr>"}</tbody>
            </table>
        </div>
    </body>
    </html>
    """

# ======================== 3. المحرك الفني والدورة ========================

async def calculate_elite_score(sym):
    try:
        score = 0
        # انضغاط البولنجر (3 فريمات)
        for tf, weight in [('4h', 20), ('1h', 10), ('15m', 10)]:
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe=tf, limit=50)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            width = (4 * df['close'].rolling(20).std()) / (df['close'].rolling(20).mean() + 1e-9)
            if width.iloc[-1] < 0.04: score += weight

        # السيولة والمؤشرات
        bars_4h = await EXCHANGE.fetch_ohlcv(sym, timeframe='4h', limit=100)
        df = pd.DataFrame(bars_4h, columns=['ts','open','high','low','close','vol'])
        if df['vol'].iloc[-1] > df['vol'].rolling(20).mean().iloc[-1] * 1.3: score += 20
        if df['close'].iloc[-1] > df['close'].ewm(span=200, adjust=False).mean().iloc[-1]: score += 20
        # RSI مبسط
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 50 < rsi.iloc[-1] < 70: score += 20
        
        return score, df['close'].iloc[-1]
    except: return 0, 0

async def sniper_cycle():
    global CURRENT_BALANCE
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and s not in EXCLUDE_LIST]
            current_found = []

            for sym in symbols:
                score, price = await calculate_elite_score(sym)
                if score > 50: # تسجيل العملات القوية فقط في التاريخ
                    current_found.append({'sym': sym, 'score': score, 'price': price, 'time': datetime.now().strftime('%H:%M')})
                
                if score >= 90 and sym not in OPEN_TRADES and len(OPEN_TRADES) < MAX_TRADES:
                    OPEN_TRADES[sym] = {'entry': price, 'current': price, 'highest_price': price, 'trailing_active': False, 'score': score}
                    CURRENT_BALANCE -= TRADE_AMOUNT
                    send_telegram(f"🚀 *دخول آلي:* {sym} (Score: {score})")
                await asyncio.sleep(0.02)

            # إضافة أفضل 5 عملات للسجل التاريخي
            if current_found:
                top_5 = sorted(current_found, key=lambda x: x['score'], reverse=True)[:5]
                SEARCH_HISTORY.extend(top_5)
                # إرسال تلجرام
                msg = "🏆 *توب 5 في البحث الحالي:*\n" + "\n".join([f"- `{x['sym']}`: {x['score']}" for x in top_5])
                send_telegram(msg)

            await asyncio.sleep(1800)
        except: await asyncio.sleep(60)

async def monitor_trades():
    global CURRENT_BALANCE
    while True:
        try:
            if OPEN_TRADES:
                for sym in list(OPEN_TRADES.keys()):
                    ticker = await EXCHANGE.fetch_ticker(sym)
                    curr_p = ticker['last']
                    trade = OPEN_TRADES[sym]
                    trade['current'] = curr_p
                    pnl = (curr_p - trade['entry']) / trade['entry']
                    
                    if curr_p > trade['highest_price']: trade['highest_price'] = curr_p
                    if not trade['trailing_active'] and pnl >= ACTIVATION_PCT: trade['trailing_active'] = True
                    
                    if trade['trailing_active']:
                        if (trade['highest_price'] - curr_p) / trade['highest_price'] >= CALLBACK_PCT:
                            res_pnl = TRADE_AMOUNT * pnl
                            CURRENT_BALANCE += (TRADE_AMOUNT + res_pnl)
                            send_telegram(f"🔔 *إغلاق (تتبع):* {sym} | الربح: {res_pnl:+.2f}$")
                            del OPEN_TRADES[sym]
                            continue
                    if pnl <= -0.03:
                        res_pnl = TRADE_AMOUNT * pnl
                        CURRENT_BALANCE += (TRADE_AMOUNT + res_pnl)
                        send_telegram(f"🛡️ *إغلاق (وقف):* {sym} | الخسارة: {res_pnl:+.2f}$")
                        del OPEN_TRADES[sym]
        except: pass
        await asyncio.sleep(20)

def send_telegram(msg):
    for cid in DESTINATIONS:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"})
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    loop = asyncio.get_event_loop()
    loop.create_task(sniper_cycle()); loop.create_task(monitor_trades())
    loop.run_forever()
