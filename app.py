import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. الإعدادات والبيانات ========================
app = Flask('')
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})
RENDER_URL = "https://your-app-name.onrender.com/" 

# قائمة الاستبعاد (العملات المستقرة والعملات القيادية الضخمة)
EXCLUDE_LIST = [
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT',
    'USDC/USDT', 'FDUSD/USDT', 'TUSD/USDT', 'USDP/USDT', 'DAI/USDT', 'USDE/USDT'
]

# إعدادات المحفظة
INITIAL_BALANCE = 500.0
CURRENT_BALANCE = 500.0
MAX_TRADES = 10
TRADE_AMOUNT = 50.0 
OPEN_TRADES = {}     
HOURLY_CLOSED_LOG = [] 

@app.route('/')
def home():
    return f"🚀 Sniper Bot v3 | Balance: {CURRENT_BALANCE:.2f}$ | Open: {len(OPEN_TRADES)}"

# ======================== 2. محرك التحليل والسكور ========================

def calculate_advanced_score(df):
    try:
        if len(df) < 200: return 0
        close = df['close']
        
        # حساب المؤشرات
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        
        tp = (df['high'] + df['low'] + close) / 3
        mf = tp * df['vol']
        pos_f = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
        neg_f = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
        mfi = 100 - (100 / (1 + (pos_f / (neg_f + 1e-9))))
        
        sma = close.rolling(20).mean()
        std = close.rolling(20).std()
        width = (4 * std) / (sma + 1e-9)
        
        ema200 = close.ewm(span=200, adjust=False).mean()

        score = 0
        last = -1
        if close.iloc[last] > ema200.iloc[last]: score += 20
        if width.iloc[last] < 0.035: score += 40
        elif width.iloc[last] < 0.05: score += 20
        if 50 < rsi.iloc[last] < 65: score += 20
        if mfi.iloc[last] > 60: score += 20
        
        return score
    except: return 0

# ======================== 3. دورة القنص والفلترة ========================

async def sniper_cycle():
    global CURRENT_BALANCE
    while True:
        try:
            start_time = datetime.now()
            
            tickers = await EXCHANGE.fetch_tickers()
            # فلترة العملات: استبعاد المستقرة والكبيرة + استبعاد أي عملة مفتوحة حالياً
            symbols = [s for s in tickers.keys() if '/USDT' in s 
                       and s not in EXCLUDE_LIST 
                       and s not in OPEN_TRADES.keys()]
            
            candidates = []
            for sym in symbols:
                try:
                    bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='4h', limit=205)
                    df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
                    score = calculate_advanced_score(df)
                    if score >= 60:
                        candidates.append({'symbol': sym, 'score': score, 'price': df['close'].iloc[-1]})
                except: continue
                await asyncio.sleep(0.01)

            if candidates:
                sorted_candidates = sorted(candidates, key=lambda x: x['score'], reverse=True)
                
                # تقرير المسح الصامت لأفضل 5
                report = "📋 *أفضل فرص العملات البديلة حالياً:*\n"
                for item in sorted_candidates[:5]:
                    report += f"🔹 `{item['symbol']}` | Score: *{item['score']}*\n"
                send_telegram(report)

                # تنفيذ الصفقة (أعلى سكور فوق 85)
                best = sorted_candidates[0]
                if best['score'] >= 85 and len(OPEN_TRADES) < MAX_TRADES:
                    sym, entry_price = best['symbol'], best['price']
                    tp_price, sl_price = entry_price * 1.06, entry_price * 0.97
                    entry_time = datetime.now().strftime('%Y-%m-%d %H:%M')

                    OPEN_TRADES[sym] = {'entry': entry_price, 'current': entry_price, 'time': entry_time}
                    CURRENT_BALANCE -= TRADE_AMOUNT
                    
                    entry_msg = (
                        f"🚀 *دخول صفقة جديدة*\n"
                        f"───────────────────\n"
                        f"💎 *العملة:* `{sym}`\n"
                        f"💰 *سعر الدخول:* `{entry_price:.6f}`\n"
                        f"⏰ *وقت الدخول:* `{entry_time}`\n"
                        f"🎯 *الهدف (6%):* `{tp_price:.6f}`\n"
                        f"🛡️ *الوقف (-3%):* `{sl_price:.6f}`\n"
                        f"───────────────────"
                    )
                    send_telegram(entry_msg)
            
            elapsed = (datetime.now() - start_time).total_seconds()
            await asyncio.sleep(max(0, 1800 - elapsed))
        except: await asyncio.sleep(60)

# ======================== 4. التقارير والمراقبة ========================

async def hourly_report_scheduler():
    while True:
        await asyncio.sleep(3600)
        try:
            now_str = datetime.now().strftime('%H:%M')
            report = f"📊 *تقرير الساعة ({now_str})*\n"
            report += f"💰 الرصيد: `{CURRENT_BALANCE:.2f}$` | نشطة: `{len(OPEN_TRADES)}`\n"
            report += "───────────────────\n"
            
            if OPEN_TRADES:
                report += "📍 *أداء الصفقات المفتوحة:*\n"
                for sym, data in OPEN_TRADES.items():
                    pnl_pct = ((data['current'] - data['entry']) / data['entry']) * 100
                    report += f"• `{sym}`: `{pnl_pct:+.2f}%` \n"
            
            if HOURLY_CLOSED_LOG:
                report += "\n✅ *المغلقة مؤخراً:*\n"
                for log in HOURLY_CLOSED_LOG:
                    report += f"• `{log['sym']}`: {log['res']} ({log['pnl']:+.2f}$)\n"
                HOURLY_CLOSED_LOG.clear()
            
            send_telegram(report)
        except: pass

async def monitor_trades():
    global CURRENT_BALANCE, HOURLY_CLOSED_LOG
    while True:
        try:
            if OPEN_TRADES:
                tickers = await EXCHANGE.fetch_tickers(list(OPEN_TRADES.keys()))
                for sym in list(OPEN_TRADES.keys()):
                    curr_price = tickers[sym]['last']
                    OPEN_TRADES[sym]['current'] = curr_price
                    entry = OPEN_TRADES[sym]['entry']
                    change = (curr_price - entry) / entry
                    
                    if change >= 0.06 or change <= -0.03:
                        pnl = TRADE_AMOUNT * change
                        CURRENT_BALANCE += (TRADE_AMOUNT + pnl)
                        res_status = "✅ هدف" if change >= 0.06 else "❌ وقف"
                        HOURLY_CLOSED_LOG.append({'sym': sym, 'res': res_status, 'pnl': pnl})
                        
                        send_telegram(f"🔔 *إغلاق صفقة*\n💎 `{sym}` | {res_status}\n💰 صافي: `{pnl:+.2f}$`")
                        del OPEN_TRADES[sym]
        except: pass
        await asyncio.sleep(20)

async def keep_alive():
    while True:
        try: requests.get(RENDER_URL, timeout=10)
        except: pass
        await asyncio.sleep(600)

def send_telegram(msg):
    for cid in DESTINATIONS:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                          json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        except: pass

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080, use_reloader=False), daemon=True).start()
    loop = asyncio.get_event_loop()
    loop.create_task(sniper_cycle())
    loop.create_task(monitor_trades())
    loop.create_task(hourly_report_scheduler())
    loop.create_task(keep_alive())
    loop.run_forever()
