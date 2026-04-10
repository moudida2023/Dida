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

# قائمة الاستبعاد (العملات المستقرة والقيادية)
EXCLUDE_LIST = [
    'TUSD/USDT', 'USDC/USDT', 'FDUSD/USDT', 'USDT/USDT', 'DAI/USDT', 
    'USDE/USDT', 'USDP/USDT', 'BUSD/USDT', 'AEUR/USDT', 'EUR/USDT',
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT', 
    'ADA/USDT', 'DOGE/USDT', 'TRX/USDT', 'DOT/USDT', 'LINK/USDT'
]

# إعدادات المحفظة
INITIAL_BALANCE = 500.0
CURRENT_BALANCE = 500.0
MAX_TRADES = 10
TRADE_AMOUNT = 50.0 
OPEN_TRADES = {}     
SEARCH_HISTORY = [] # قائمة سجل العملات المكتشفة

# إعدادات تتبع الربح (Trailing Profit)
ACTIVATION_PCT = 0.03   # تفعيل التتبع عند ربح 3%
CALLBACK_PCT = 0.015    # الخروج عند هبوط 1.5% من القمة

# ======================== 2. محرك لوحة التحكم (الويب) ========================

async def update_live_prices_in_history():
    """تحديث الأسعار الحالية للعملات في سجل التاريخ"""
    if not SEARCH_HISTORY: return
    try:
        symbols_to_update = list(set([x['sym'] for x in SEARCH_HISTORY[-20:]]))
        if symbols_to_update:
            tickers = await EXCHANGE.fetch_tickers(symbols_to_update)
            for item in SEARCH_HISTORY:
                if item['sym'] in tickers:
                    item['live_price'] = tickers[item['sym']]['last']
    except Exception as e:
        print(f"Error updating live prices: {e}")

@app.route('/')
def home():
    # محاولة تحديث الأسعار (تعمل بشكل غير متزامن داخل فلاسك)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(update_live_prices_in_history())
    
    # بناء جدول الصفقات المفتوحة
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
            <td>{'🔥 ملاحقة' if data.get('trailing_active') else '⏳ انتظار'}</td>
        </tr>"""

    # بناء جدول سجل الرادار (History)
    history_html = ""
    for item in reversed(SEARCH_HISTORY[-30:]): # عرض آخر 30 عملة تم رصدها
        disc_p = item['price']
        live_p = item.get('live_price', disc_p)
        change = ((live_p - disc_p) / disc_p) * 100
        c_color = "#00ff00" if change >= 0 else "#ff4444"
        history_html += f"""
        <tr>
            <td>{item['time']}</td>
            <td><strong>{item['sym']}</strong></td>
            <td>{item['score']}</td>
            <td>{disc_p:.6f}</td>
            <td>{live_p:.6f}</td>
            <td style="color: {c_color};">{change:+.2f}%</td>
        </tr>"""

    return f"""
    <html>
    <head>
        <title>Sniper Elite Dashboard v10</title>
        <meta http-equiv="refresh" content="30">
        <style>
            body {{ background: #0b0e11; color: #eaecef; font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 0; }}
            .header {{ background: #1e2329; padding: 20px; border-bottom: 2px solid #f0b90b; text-align: center; }}
            .stats-container {{ display: flex; justify-content: space-around; background: #181a20; padding: 15px; font-size: 1.1em; }}
            .container {{ padding: 20px; }}
            table {{ width: 95%; margin: 20px auto; border-collapse: collapse; background: #1e2329; border-radius: 8px; overflow: hidden; }}
            th, td {{ padding: 12px; border: 1px solid #2b3139; text-align: center; }}
            th {{ background: #2b3139; color: #f0b90b; }}
            h2 {{ color: #f0b90b; margin-top: 30px; text-align: center; }}
            .val-box {{ color: #f0b90b; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="header"><h1>🚀 Sniper Elite Dashboard</h1></div>
        <div class="stats-container">
            <div>Balance: <span class="val-box">{CURRENT_BALANCE:.2f} USDT</span></div>
            <div>Active Trades: <span class="val-box">{len(OPEN_TRADES)} / {MAX_TRADES}</span></div>
            <div>Time: <span class="val-box">{datetime.now().strftime('%H:%M:%S')}</span></div>
        </div>
        <div class="container">
            <h2>💎 الصفقات الحالية (Live)</h2>
            <table>
                <thead><tr><th>العملة</th><th>الدخول</th><th>الحالي</th><th>الربح %</th><th>السكور</th><th>الحالة</th></tr></thead>
                <tbody>{trades_html if trades_html else "<tr><td colspan='6'>لا توجد صفقات مفتوحة</td></tr>"}</tbody>
            </table>
            <h2>🏆 رادار العملات المكتشفة (History)</h2>
            <table>
                <thead><tr><th>الوقت</th><th>العملة</th><th>السكور</th><th>سعر الاكتشاف</th><th>السعر الحالي</th><th>الأداء منذ الرصد</th></tr></thead>
                <tbody>{history_html if history_html else "<tr><td colspan='6'>جاري مسح السوق...</td></tr>"}</tbody>
            </table>
        </div>
    </body>
    </html>
    """

# ======================== 3. المحرك الفني ودورة العمل ========================

async def calculate_elite_score(sym):
    try:
        score = 0
        # أ. انضغاط البولنجر على 3 فريمات (40 نقطة)
        for tf, weight in [('4h', 20), ('1h', 10), ('15m', 10)]:
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe=tf, limit=50)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            width = (4 * df['close'].rolling(20).std()) / (df['close'].rolling(20).mean() + 1e-9)
            if width.iloc[-1] < 0.04: score += weight

        # ب. فحص السيولة والمؤشرات (60 نقطة)
        bars_4h = await EXCHANGE.fetch_ohlcv(sym, timeframe='4h', limit=100)
        df = pd.DataFrame(bars_4h, columns=['ts','open','high','low','close','vol'])
        
        # 1. انفجار السيولة (20 نقطة)
        if df['vol'].iloc[-1] > df['vol'].rolling(20).mean().iloc[-1] * 1.3: score += 20
        # 2. الاتجاه EMA 200 (20 نقطة)
        if df['close'].iloc[-1] > df['close'].ewm(span=200, adjust=False).mean().iloc[-1]: score += 20
        # 3. RSI (20 نقطة)
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
            current_found = []

            for sym in symbols:
                score, price = await calculate_elite_score(sym)
                if score >= 60: # رصد العملات القوية
                    current_found.append({'sym': sym, 'score': score, 'price': price, 'time': datetime.now().strftime('%H:%M')})
                
                # الدخول الآلي (90+)
                if score >= 90 and sym not in OPEN_TRADES and len(OPEN_TRADES) < MAX_TRADES:
                    OPEN_TRADES[sym] = {
                        'entry': price, 'current': price, 'highest_price': price, 
                        'trailing_active': False, 'score': score
                    }
                    CURRENT_BALANCE -= TRADE_AMOUNT
                    send_telegram(f"🚀 *دخول آلي (High Score):* {sym}\n💰 السعر: {price:.6f}\n🏆 السكور: {score}")
                await asyncio.sleep(0.02)

            # تحديث السجل التاريخي وإرسال توب 5 لتلجرام
            if current_found:
                top_5 = sorted(current_found, key=lambda x: x['score'], reverse=True)[:5]
                SEARCH_HISTORY.extend(top_5)
                msg = "🏆 *توب 5 في البحث الحالي:*\n" + "\n".join([f"- `{x['sym']}`: {x['score']}" for x in top_5])
                send_telegram(msg)

            await asyncio.sleep(max(0, 1800 - (datetime.now() - start_time).total_seconds()))
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
                    
                    # تفعيل التتبع عند 3%
                    if not trade['trailing_active'] and pnl >= ACTIVATION_PCT:
                        trade['trailing_active'] = True
                        send_telegram(f"🔥 *بدأ ملاحقة الربح:* {sym}")

                    # خروج جني الأرباح (Trailing)
                    if trade['trailing_active']:
                        if (trade['highest_price'] - curr_p) / trade['highest_price'] >= CALLBACK_PCT:
                            final_p = TRADE_AMOUNT * pnl
                            CURRENT_BALANCE += (TRADE_AMOUNT + final_p)
                            send_telegram(f"✅ *إغلاق (Trailing):* {sym} | الربح: {final_p:+.2f}$")
                            del OPEN_TRADES[sym]
                            continue
                    
                    # وقف الخسارة (-3%)
                    if pnl <= -0.03:
                        final_p = TRADE_AMOUNT * pnl
                        CURRENT_BALANCE += (TRADE_AMOUNT + final_p)
                        send_telegram(f"🛡️ *إغلاق (Stop Loss):* {sym} | الخسارة: {final_p:+.2f}$")
                        del OPEN_TRADES[sym]
        except: pass
        await asyncio.sleep(15)

def send_telegram(msg):
    for cid in DESTINATIONS:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    loop = asyncio.get_event_loop()
    loop.create_task(sniper_cycle()); loop.create_task(monitor_trades())
    loop.run_forever()
