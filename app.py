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
HOURLY_CLOSED_LOG = [] 

ACTIVATION_PCT = 0.03
CALLBACK_PCT = 0.015

@app.route('/')
def home():
    return f"🚀 Sniper v8 | Top 5 Mode | Balance: {CURRENT_BALANCE:.2f}$"

# ======================== 2. محرك السكور المطور ========================

async def calculate_elite_score(sym):
    try:
        score = 0
        # أ. انضغاط البولنجر (40 نقطة)
        for tf, weight in [('4h', 20), ('1h', 10), ('15m', 10)]:
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe=tf, limit=50)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            width = (4 * df['close'].rolling(20).std()) / (df['close'].rolling(20).mean() + 1e-9)
            if width.iloc[-1] < 0.04: score += weight

        # ب. المؤشرات والسيولة (60 نقطة)
        bars_4h = await EXCHANGE.fetch_ohlcv(sym, timeframe='4h', limit=200)
        df_4h = pd.DataFrame(bars_4h, columns=['ts','open','high','low','close','vol'])
        vol = df_4h['vol']
        close = df_4h['close']

        # 1. فلتر انفجار السيولة (20 نقطة)
        if vol.iloc[-1] > vol.rolling(20).mean().iloc[-1] * 1.3: score += 20
        # 2. EMA 200 (10 نقاط)
        if close.iloc[-1] > close.ewm(span=200, adjust=False).mean().iloc[-1]: score += 10
        # 3. RSI (15 نقطة)
        delta = close.diff()
        rsi = 100 - (100 / (1 + (delta.where(delta > 0, 0).rolling(14).mean() / (-delta.where(delta < 0, 0).rolling(14).mean() + 1e-9))))
        if 50 < rsi.iloc[-1] < 65: score += 15
        # 4. MFI (15 نقطة)
        tp = (df_4h['high'] + df_4h['low'] + close) / 3
        mf = tp * vol
        mfi = 100 - (100 / (1 + (mf.where(tp > tp.shift(1), 0).rolling(14).sum() / (mf.where(tp < tp.shift(1), 0).rolling(14).sum() + 1e-9))))
        if mfi.iloc[-1] > 60: score += 15
        
        return score, close.iloc[-1]
    except: return 0, 0

# ======================== 3. دورة البحث وقائمة التوب 5 ========================

async def sniper_cycle():
    global CURRENT_BALANCE
    while True:
        try:
            start_time = datetime.now()
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and s not in EXCLUDE_LIST]
            
            all_scores = [] # قائمة لتخزين نتائج البحث الحالي

            for sym in symbols:
                score, price = await calculate_elite_score(sym)
                if score > 0:
                    all_scores.append({'sym': sym, 'score': score, 'price': price})
                
                # الدخول الآلي الفوري (للمشتركين في القائمة المفتوحة فقط)
                if score >= 90 and sym not in OPEN_TRADES and len(OPEN_TRADES) < MAX_TRADES:
                    OPEN_TRADES[sym] = {'entry': price, 'highest_price': price, 'trailing_active': False}
                    CURRENT_BALANCE -= TRADE_AMOUNT
                    send_telegram(f"🚀 *دخول آلي*\n💎 `{sym}` | سكور: `{score}`")
                
                await asyncio.sleep(0.01)

            # --- إرسال قائمة أفضل 5 عملات في نهاية البحث ---
            if all_scores:
                # ترتيب العملات حسب السكور من الأعلى للأقل
                top_5 = sorted(all_scores, key=lambda x: x['score'], reverse=True)[:5]
                
                report = "🏆 *أفضل 5 عملات في هذا البحث:*\n"
                for i, item in enumerate(top_5, 1):
                    tag = "🔥" if item['score'] >= 90 else "👀"
                    report += f"{i}. `{item['sym']}` | سكور: `{item['score']}` {tag}\n"
                
                send_telegram(report)

            await asyncio.sleep(max(0, 1800 - (datetime.now() - start_time).total_seconds()))
        except: await asyncio.sleep(60)

# [دوال monitor_trades و hourly_report و send_telegram تبقى كما هي في الكود السابق]

async def monitor_trades():
    global CURRENT_BALANCE
    while True:
        try:
            if OPEN_TRADES:
                symbols = list(OPEN_TRADES.keys())
                tickers = await EXCHANGE.fetch_tickers(symbols)
                for sym in symbols:
                    curr_p = tickers[sym]['last']
                    trade = OPEN_TRADES[sym]
                    pnl_pct = (curr_p - trade['entry']) / trade['entry']
                    if curr_p > trade['highest_price']: trade['highest_price'] = curr_p
                    if not trade['trailing_active'] and pnl_pct >= ACTIVATION_PCT: trade['trailing_active'] = True
                    
                    if trade['trailing_active']:
                        if (trade['highest_price'] - curr_p) / trade['highest_price'] >= CALLBACK_PCT:
                            pnl_val = TRADE_AMOUNT * pnl_pct
                            CURRENT_BALANCE += (TRADE_AMOUNT + pnl_val)
                            HOURLY_CLOSED_LOG.append({'sym': sym, 'res': '✅ Trailing', 'pnl': pnl_val})
                            send_telegram(f"🔔 *جني أرباح:* `{sym}` (+{pnl_pct*100:.2f}%)")
                            del OPEN_TRADES[sym]
                            continue
                    if pnl_pct <= -0.03:
                        pnl_val = TRADE_AMOUNT * pnl_pct
                        CURRENT_BALANCE += (TRADE_AMOUNT + pnl_val)
                        HOURLY_CLOSED_LOG.append({'sym': sym, 'res': '❌ SL', 'pnl': pnl_val})
                        send_telegram(f"🛡️ *وقف خسارة:* `{sym}`")
                        del OPEN_TRADES[sym]
        except: pass
        await asyncio.sleep(15)

async def hourly_report():
    while True:
        await asyncio.sleep(3600)
        try:
            rep = f"📊 *ملخص المحفظة*\n💰 الرصيد: `{CURRENT_BALANCE:.2f}$` | المفتوحة: `{len(OPEN_TRADES)}`"
            send_telegram(rep)
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
