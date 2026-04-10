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
SEARCH_HISTORY = [] # سجل العملات المكتشفة الفريدة (80+)

ACTIVATION_PCT = 0.03
CALLBACK_PCT = 0.015

# ======================== 2. لوحة التحكم (الويب) ========================

async def update_live_prices_in_history():
    """تحديث الأسعار اللحظية لكل شيء في الجدول قبل عرض الصفحة"""
    if not SEARCH_HISTORY: return
    try:
        # جلب أسعار آخر 30 عملة فريدة في السجل
        symbols_to_update = list(set([x['sym'] for x in SEARCH_HISTORY[-30:]]))
        if symbols_to_update:
            tickers = await EXCHANGE.fetch_tickers(symbols_to_update)
            for item in SEARCH_HISTORY:
                if item['sym'] in tickers:
                    item['live_price'] = tickers[item['sym']]['last']
    except: pass

@app.route('/')
def home():
    # تحديث الأسعار عند كل تحميل للصفحة
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(update_live_prices_in_history())
    
    # جدول الصفقات المفتوحة
    trades_html = "".join([f"<tr><td>{s}</td><td>{d['entry']:.6f}</td><td>{d['current']:.6f}</td><td style='color:{'#00ff00' if ((d['current']-d['entry'])/d['entry'])>=0 else '#ff4444'}; font-weight:bold;'>{((d['current']-d['entry'])/d['entry'])*100:+.2f}%</td><td>{d.get('score','N/A')}</td><td>{'🔥 ملاحقة' if d.get('trailing_active') else '⏳ انتظار'}</td></tr>" for s, d in OPEN_TRADES.items()])

    # جدول الرادار (التاريخ الفريد)
    history_html = ""
    for item in reversed(SEARCH_HISTORY[-50:]):
        disc_p = item['price']
        live_p = item.get('live_price', disc_p)
        change = ((live_p - disc_p) / disc_p) * 100
        history_html += f"<tr><td>{item['time']}</td><td><strong>{item['sym']}</strong></td><td>{item['score']}</td><td>{disc_p:.6f}</td><td>{live_p:.6f}</td><td style='color:{'#00ff00' if change>=0 else '#ff4444'}; font-weight:bold;'>{change:+.2f}%</td></tr>"

    return f"""
    <html><head><title>Sniper Elite v13</title><meta http-equiv="refresh" content="30">
    <style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; margin: 0; }}
        .header {{ background: #1e2329; padding: 15px; border-bottom: 2px solid #f0b90b; text-align: center; }}
        .stats {{ display: flex; justify-content: space-around; background: #181a20; padding: 10px; border-bottom: 1px solid #2b3139; }}
        table {{ width: 95%; margin: 20px auto; border-collapse: collapse; background: #1e2329; border-radius: 8px; overflow: hidden; }}
        th, td {{ padding: 10px; border: 1px solid #2b3139; text-align: center; }}
        th {{ background: #2b3139; color: #f0b90b; }}
        h2 {{ color: #f0b90b; text-align: center; margin-top: 20px; }}
    </style></head>
    <body>
        <div class="header"><h1>🚀 Sniper Elite Dashboard v13</h1></div>
        <div class="stats">
            <span>Balance: <b>{CURRENT_BALANCE:.2f} USDT</b></span>
            <span>Active Trades: <b>{len(OPEN_TRADES)} / {MAX_TRADES}</b></span>
            <span>Auto-Refresh: <b>30s</b></span>
        </div>
        <div class="container">
            <h2>💎 الصفقات الحالية</h2>
            <table><thead><tr><th>العملة</th><th>الدخول</th><th>الحالي</th><th>الربح %</th><th>السكور</th><th>الحالة</th></tr></thead><tbody>{trades_html if trades_html else "<tr><td colspan='6'>لا توجد صفقات مفتوحة</td></tr>"}</tbody></table>
            <h2>🏆 رادار الفرص الفريدة (سكور 80+ | إضافة فورية)</h2>
            <table><thead><tr><th>وقت الرصد</th><th>العملة</th><th>السكور</th><th>سعر الاكتشاف</th><th>السعر الحالي</th><th>الأداء اللحظي</th></tr></thead><tbody>{history_html if history_html else "<tr><td colspan='6'>جاري مسح السوق...</td></tr>"}</tbody></table>
        </div></body></html>"""

# ======================== 3. المحرك الفني ودورة البحث السريع ========================

async def calculate_elite_score(sym):
    try:
        score = 0
        # انضغاط البولنجر (40 نقطة)
        for tf, weight in [('4h', 20), ('1h', 10), ('15m', 10)]:
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe=tf, limit=50)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            width = (4 * df['close'].rolling(20).std()) / (df['close'].rolling(20).mean() + 1e-9)
            if width.iloc[-1] < 0.04: score += weight

        # السيولة والاتجاه (60 نقطة)
        bars_4h = await EXCHANGE.fetch_ohlcv(sym, timeframe='4h', limit=100)
        df = pd.DataFrame(bars_4h, columns=['ts','open','high','low','close','vol'])
        if df['vol'].iloc[-1] > df['vol'].rolling(20).mean().iloc[-1] * 1.3: score += 20
        if df['close'].iloc[-1] > df['close'].ewm(span=200, adjust=False).mean().iloc[-1]: score += 20
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
            start_time = datetime.now()
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and s not in EXCLUDE_LIST]
            
            for sym in symbols:
                score, price = await calculate_elite_score(sym)
                
                # --- الإضافة الفورية للجدول (سكور 80+ وبدون تكرار) ---
                if score >= 60:
                    existing_symbols = [item['sym'] for item in SEARCH_HISTORY[-50:]]
                    if sym not in existing_symbols:
                        SEARCH_HISTORY.append({
                            'sym': sym, 'score': score, 'price': price, 'live_price': price,
                            'time': datetime.now().strftime('%H:%M:%S')
                        })
                        if len(SEARCH_HISTORY) > 100: SEARCH_HISTORY.pop(0)

                # --- الدخول الآلي الفوري (سكور 90+) ---
                if score >= 80 and sym not in OPEN_TRADES and len(OPEN_TRADES) < MAX_TRADES:
                    OPEN_TRADES[sym] = {
                        'entry': price, 'current': price, 'highest_price': price, 
                        'trailing_active': False, 'score': score
                    }
                    CURRENT_BALANCE -= TRADE_AMOUNT
                    send_telegram(f"⚡ *قنص آلي:* {sym} (Score: {score})")
                
                await asyncio.sleep(0.01) # سرعة المسح

            elapsed = (datetime.now() - start_time).total_seconds()
            await asyncio.sleep(max(10, 360 - elapsed)) # دورة كل 6 دقائق تقريباً
        except: await asyncio.sleep(30)

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
                            res = TRADE_AMOUNT * pnl
                            CURRENT_BALANCE += (TRADE_AMOUNT + res)
                            send_telegram(f"✅ *إغلاق ربح:* {sym} | {res:+.2f}$")
                            del OPEN_TRADES[sym]
                            continue
                    if pnl <= -0.03:
                        res = TRADE_AMOUNT * pnl
                        CURRENT_BALANCE += (TRADE_AMOUNT + res)
                        send_telegram(f"🛡️ *وقف خسارة:* {sym} | {res:+.2f}$")
                        del OPEN_TRADES[sym]
        except: pass
        await asyncio.sleep(15)

def send_telegram(msg):
    for cid in DESTINATIONS:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    loop = asyncio.get_event_loop()
    loop.create_task(sniper_cycle()); loop.create_task(monitor_trades())
    loop.run_forever()
