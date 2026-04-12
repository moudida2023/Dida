import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
from flask import Flask
from waitress import serve
from datetime import datetime

# ======================== 1. الإعدادات والربط ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0
MAX_OPEN_TRADES = 20
TARGET_PROFIT_USD = 1.1    # الربح الذي يبدأ عنده ملاحقة السعر
TRAILING_GAP_USD = 0.3     # المسافة المسموح بها للتراجع قبل الإغلاق
TRADE_AMOUNT_USD = 50.0

portfolio = {"open_trades": {}}
closed_this_hour = []

# ======================== 2. محرك التحليل والسكور (200 نقطة) ========================

def check_candlestick_patterns(df):
    """تحليل سلوك السعر (Price Action)"""
    last, prev = df.iloc[-1], df.iloc[-2]
    body = abs(last['close'] - last['open'])
    l_shadow = min(last['open'], last['close']) - last['low']
    score = 0
    # نموذج المطرقة (Hammer)
    if l_shadow > (body * 2) and body > 0: score += 25
    # الابتلاع الشرائي (Bullish Engulfing)
    if last['close'] > prev['open'] and last['open'] < prev['close']: score += 25
    return min(score, 40)

async def calculate_mega_score(symbol):
    """حساب سكور الجودة الشامل من 200 نقطة"""
    try:
        bars = await EXCHANGE.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
        close = df['close']
        
        # حساب المؤشرات
        basis = close.rolling(20).mean()
        std = close.rolling(20).std()
        df['bb_width'] = (std * 4) / basis
        upper_bb = basis + (std * 2)
        
        delta = close.diff()
        gain, loss = (delta.where(delta > 0, 0)).rolling(14).mean(), (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain / loss)))
        df['ema200'] = close.ewm(span=200).mean()
        
        last, score = df.iloc[-1], 0

        # --- فلتر عدم الدخول في القمة (Anti-Top) ---
        dist_ema = (last['close'] - last['ema200']) / last['ema200']
        if dist_ema > 0.10 or last['close'] > upper_bb.iloc[-1] * 1.01:
            return 0, 0 # استبعاد تام للقمم

        # [1] اختناق بولنجر (50 نقطة)
        if last['bb_width'] < 0.05: score += 50 
        
        # [2] دايفرجنس RSI (50 نقطة)
        p_low1, p_low2 = df['low'].iloc[-15:-7].min(), df['low'].iloc[-7:].min()
        r_low1, r_low2 = df['rsi'].iloc[-15:-7].min(), df['rsi'].iloc[-7:].min()
        if p_low2 < p_low1 and r_low2 > r_low1: score += 50
        
        # [3] نماذج الشموع (40 نقطة)
        score += check_candlestick_patterns(df)
        
        # [4] عمق السوق (30 نقطة)
        ob = await EXCHANGE.fetch_order_book(symbol, limit=20)
        if sum([b[1] for b in ob['bids']]) > sum([a[1] for a in ob['asks']]) * 1.5: score += 30
        
        # [5] الترند والفوليوم (30 نقطة)
        if last['close'] > last['ema200'] and last['vol'] > df['vol'].rolling(20).mean().iloc[-1] * 1.5: score += 30
        
        return score, last['close']
    except: return 0, 0

# ======================== 3. إدارة السوق والمسح الهجومي ========================

async def check_market_crash():
    """حماية المحفظة من هبوط البيتكوين"""
    global VIRTUAL_BALANCE
    try:
        btc = await EXCHANGE.fetch_ohlcv('BTC/USDT', timeframe='5m', limit=2)
        drop = (btc[-1][4] - btc[0][1]) / btc[0][1] * 100
        if drop <= -1.5:
            if portfolio["open_trades"]:
                send_telegram_msg(f"🚨 *KILL SWITCH ACTIVATED!*\nهبوط البيتكوين: {drop:.2f}%\nتصفية الصفقات...")
                for sym in list(portfolio["open_trades"].keys()):
                    t = portfolio["open_trades"][sym]
                    tick = await EXCHANGE.fetch_ticker(sym)
                    pnl = (tick['last'] / t['entry_price'] - 1) * t['amount']
                    VIRTUAL_BALANCE += (t['amount'] + pnl)
                    portfolio["open_trades"].pop(sym)
            return True
        return False
    except: return False

async def try_instant_entry(symbol):
    global VIRTUAL_BALANCE
    if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES or VIRTUAL_BALANCE < TRADE_AMOUNT_USD: return
    score, price = await calculate_mega_score(symbol)
    if score >= 155:
        portfolio["open_trades"][symbol] = {"entry_price": price, "amount": TRADE_AMOUNT_USD, "max_pnl": 0}
        VIRTUAL_BALANCE -= TRADE_AMOUNT_USD
        send_telegram_msg(f"🚀 *دخول قناص (V20)*\n🎫 {symbol}\n📊 سكور: {score}/200\n💰 السعر: {price}")

async def scanner_loop():
    blacklist = ['BTC/USDT','ETH/USDT','BNB/USDT','SOL/USDT','USDC/USDT','FDUSD/USDT','DAI/USDT','XRP/USDT']
    while True:
        if await check_market_crash(): await asyncio.sleep(60); continue
        try:
            tickers = await EXCHANGE.fetch_tickers()
            # استهداف العملات الرشيقة (سيولة بين 5 و 150 مليون)
            symbols = [s for s in tickers.keys() if '/USDT' in s and s not in blacklist and 5_000_000 < tickers[s].get('quoteVolume',0) < 150_000_000]
            sorted_syms = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:500]
            
            for i in range(0, len(sorted_syms), 150):
                batch = sorted_syms[i:i+150]
                tasks = [try_instant_entry(s) for s in batch if s not in portfolio["open_trades"]]
                await asyncio.gather(*tasks)
                await asyncio.sleep(1)
            await asyncio.sleep(10)
        except: await asyncio.sleep(10)

# ======================== 4. الأرباح والتقارير ========================

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                t = portfolio["open_trades"][sym]
                tick = await EXCHANGE.fetch_ticker(sym)
                cp = tick['last']
                pnl = (cp / t['entry_price'] - 1) * t['amount']
                
                if pnl > t.get('max_pnl', 0): t['max_pnl'] = pnl

                if t.get('max_pnl', 0) >= TARGET_PROFIT_USD:
                    if pnl < (t['max_pnl'] - TRAILING_GAP_USD):
                        VIRTUAL_BALANCE += (t['amount'] + pnl)
                        closed_this_hour.append({"sym": sym, "profit": pnl})
                        portfolio["open_trades"].pop(sym)
                        send_telegram_msg(f"💰 *خروج بملاحقة الربح*\n🎫 {sym}\n✅ الربح: ${pnl:.2f}\n📈 القمة: ${t['max_pnl']:.2f}")
            await asyncio.sleep(10)
        except: await asyncio.sleep(5)

def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except: pass

async def hourly_report():
    global VIRTUAL_BALANCE, closed_this_hour
    while True:
        await asyncio.sleep(3600)
        p_sum = sum(t['profit'] for t in closed_this_hour)
        send_telegram_msg(f"📊 *التقرير الساعي V20*\n💰 الرصيد: ${VIRTUAL_BALANCE:.2f}\n💵 أرباح الساعة: ${p_sum:+.2f}\n📂 صفقات نشطة: {len(portfolio['open_trades'])}")
        closed_this_hour = []

# ======================== 5. البدء ========================

app = Flask('')
@app.route('/')
def home(): return f"Active. Balance: {VIRTUAL_BALANCE}"

async def main():
    send_telegram_msg("⚡ *تم تفعيل Snowball Sniper V20.0*\nالأنظمة: [سكور 200] [ملاحقة ربح] [حماية قمة] [درع BTC]")
    asyncio.create_task(manage_trades()); asyncio.create_task(hourly_report())
    await scanner_loop()

if __name__ == "__main__":
    threading.Thread(target=lambda: serve(app, host='0.0.0.0', port=10000), daemon=True).start()
    asyncio.run(main())
