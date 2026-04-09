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
RENDER_URL = "https://your-app-name.onrender.com/" 

EXCLUDE_LIST = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'USDC/USDT', 'FDUSD/USDT']

INITIAL_BALANCE = 500.0
CURRENT_BALANCE = 500.0
MAX_TRADES = 10
TRADE_AMOUNT = 50.0 
OPEN_TRADES = {}     
HOURLY_CLOSED_LOG = [] 

@app.route('/')
def home():
    return f"🚀 Sniper v4 Active | Balance: {CURRENT_BALANCE:.2f}$ | Active: {len(OPEN_TRADES)}"

# ======================== 2. محرك السكور متعدد الفريمات ========================

async def calculate_elite_score(sym):
    try:
        score = 0
        # 1. فحص الانضغاط على 3 فريمات (40 نقطة)
        sq_score = 0
        for tf, weight in [('4h', 20), ('1h', 10), ('15m', 10)]:
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe=tf, limit=50)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            width = (4 * df['close'].rolling(20).std()) / df['close'].rolling(20).mean()
            if width.iloc[-1] < 0.04: sq_score += weight
        score += sq_score

        # 2. فحص المؤشرات على فريم 4 ساعات (60 نقطة)
        bars_4h = await EXCHANGE.fetch_ohlcv(sym, timeframe='4h', limit=200)
        df_4h = pd.DataFrame(bars_4h, columns=['ts','open','high','low','close','vol'])
        close = df_4h['close']
        
        # EMA 200 (20 pts)
        ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
        if close.iloc[-1] > ema200: score += 20
        
        # RSI (20 pts)
        delta = close.diff()
        rsi = 100 - (100 / (1 + (delta.where(delta > 0, 0).rolling(14).mean() / (-delta.where(delta < 0, 0).rolling(14).mean() + 1e-9))))
        if 50 < rsi.iloc[-1] < 65: score += 20
        
        # MFI (20 pts)
        tp = (df_4h['high'] + df_4h['low'] + close) / 3
        mf = tp * df_4h['vol']
        mfi = 100 - (100 / (1 + (mf.where(tp > tp.shift(1), 0).rolling(14).sum() / (mf.where(tp < tp.shift(1), 0).rolling(14).sum() + 1e-9))))
        if mfi.iloc[-1] > 60: score += 20
        
        return score, close.iloc[-1]
    except: return 0, 0

# ======================== 3. منطق الإرسال والدخول ========================

async def sniper_cycle():
    global CURRENT_BALANCE
    while True:
        try:
            start_time = datetime.now()
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and s not in EXCLUDE_LIST and s not in OPEN_TRADES.keys()]
            
            for sym in symbols:
                score, price = await calculate_elite_score(sym)
                
                # الحالة 1: سكور 85+ (إرسال تنبيه فقط)
                if 85 <= score < 90:
                    send_telegram(f"📢 *تنبيه رادار (فرصة قوية)*\n💎 العملة: `{sym}`\n📊 السكور: `{score}/100`\n💡 ملاحظة: للمراقبة اليدوية فقط.")

                # الحالة 2: سكور 90+ (دخول آلي + إرسال تنبيه)
                elif score >= 90 and len(OPEN_TRADES) < MAX_TRADES:
                    tp_p, sl_p = price * 1.06, price * 0.97
                    OPEN_TRADES[sym] = {'entry': price, 'current': price, 'time': datetime.now().strftime('%H:%M')}
                    CURRENT_BALANCE -= TRADE_AMOUNT
                    
                    msg = (f"🚀 *دخول آلي (نخبة النخبة)*\n💎 العملة: `{sym}`\n🏆 السكور: `{score}/100`\n"
                           f"💰 الدخول: `{price:.6f}`\n🎯 الهدف: `{tp_p:.6f}`\n🛡️ الوقف: `{sl_p:.6f}`")
                    send_telegram(msg)
                
                await asyncio.sleep(0.01)

            elapsed = (datetime.now() - start_time).total_seconds()
            await asyncio.sleep(max(0, 1800 - elapsed))
        except: await asyncio.sleep(60)

async def monitor_trades():
    global CURRENT_BALANCE
    while True:
        try:
            if OPEN_TRADES:
                tickers = await EXCHANGE.fetch_tickers(list(OPEN_TRADES.keys()))
                for sym in list(OPEN_TRADES.keys()):
                    curr_p = tickers[sym]['last']
                    OPEN_TRADES[sym]['current'] = curr_p
                    entry = OPEN_TRADES[sym]['entry']
                    change = (curr_p - entry) / entry
                    
                    if change >= 0.06 or change <= -0.03:
                        pnl = TRADE_AMOUNT * change
                        CURRENT_BALANCE += (TRADE_AMOUNT + pnl)
                        res = "✅ هدف +6%" if change >= 0.06 else "❌ وقف -3%"
                        HOURLY_CLOSED_LOG.append({'sym': sym, 'res': res, 'pnl': pnl})
                        send_telegram(f"🔔 *إغلاق صفقة*\n💎 `{sym}` | {res}\n💰 الربح: `{pnl:+.2f}$`")
                        del OPEN_TRADES[sym]
        except: pass
        await asyncio.sleep(20)

async def hourly_report():
    while True:
        await asyncio.sleep(3600)
        try:
            report = f"📊 *تقرير الساعة*\n💰 الرصيد: `{CURRENT_BALANCE:.2f}$`\n📍 صفقات مفتوحة: `{len(OPEN_TRADES)}`"
            if HOURLY_CLOSED_LOG:
                report += "\n✅ مغلقة مؤخراً:\n" + "\n".join([f"• `{l['sym']}`: {l['res']}" for l in HOURLY_CLOSED_LOG])
                HOURLY_CLOSED_LOG.clear()
            send_telegram(report)
        except: pass

def send_telegram(msg):
    for cid in DESTINATIONS:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    loop = asyncio.get_event_loop()
    loop.create_task(sniper_cycle()); loop.create_task(monitor_trades()); loop.create_task(hourly_report())
    loop.run_forever()
