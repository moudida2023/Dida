import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import os
from flask import Flask
from datetime import datetime
from waitress import serve

# ======================== 1. الإعدادات والبيانات ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0
MAX_OPEN_TRADES = 20
TARGET_PROFIT_USD = 1.1    # الربح الصافي المطلوب لكل صفقة
TRADE_AMOUNT_USD = 50.0     # مبلغ الدخول لكل صفقة

portfolio = {"open_trades": {}}
closed_this_hour = []       # لسجل التقرير الساعي

# ======================== 2. محرك التحليل الفني والسكور ========================

def calculate_indicators(df):
    close = df['close']
    # بولنجر باند (الاختناق)
    basis = close.rolling(20).mean()
    std = close.rolling(20).std()
    df['bb_width'] = ((basis + (std * 2)) - (basis - (std * 2))) / basis
    # RSI (الدايفرجنس)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    # المتوسطات (الترند والتقاطع الذهبي)
    df['ema50'] = close.ewm(span=50, adjust=False).mean()
    df['ema200'] = close.ewm(span=200, adjust=False).mean()
    return df

def check_divergence(df):
    if len(df) < 20: return False
    # مقارنة القيعان السعرية مع قيعان RSI
    p_low1, p_low2 = df['low'].iloc[-15:-7].min(), df['low'].iloc[-7:].min()
    r_low1, r_low2 = df['rsi'].iloc[-15:-7].min(), df['rsi'].iloc[-7:].min()
    return p_low2 < p_low1 and r_low2 > r_low1

async def get_orderbook_strength(symbol):
    try:
        ob = await EXCHANGE.fetch_order_book(symbol, limit=20)
        total_bids = sum([b[1] for b in ob['bids']]) # طلبات الشراء
        total_asks = sum([a[1] for a in ob['asks']]) # طلبات البيع
        return 20 if total_bids > total_asks * 1.5 else (10 if total_bids > total_asks else 0)
    except: return 0

async def calculate_pro_score(symbol):
    try:
        bars = await EXCHANGE.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = calculate_indicators(pd.DataFrame(bars, columns=['ts','open','high','low','close','vol']))
        last = df.iloc[-1]
        score = 0
        
        # 1. اختناق بولنجر (25 نقطة)
        if last['bb_width'] < 0.05: score += 25
        # 2. دايفرجنس RSI (25 نقطة)
        if check_divergence(df): score += 25
        # 3. الفوليوم الانفجاري (20 نقطة)
        avg_vol = df['vol'].rolling(20).mean().iloc[-1]
        if last['vol'] > avg_vol * 1.8: score += 20
        # 4. قوة طلبات الشراء (20 نقطة)
        score += await get_orderbook_strength(symbol)
        # 5. تأكيد الترند الصاعد (10 نقاط)
        if last['close'] > last['ema200'] and last['ema50'] > last['ema200']: score += 10
        
        return score, last['close']
    except: return 0, 0

# ======================== 3. نظام الإشعارات والتقارير ========================

def send_telegram_msg(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except Exception as e: print(f"Telegram Error: {e}")

async def hourly_report():
    global VIRTUAL_BALANCE, closed_this_hour
    while True:
        await asyncio.sleep(3600)
        profit_sum = sum(t['profit'] for t in closed_this_hour)
        
        open_list = "\n".join([f"🔹 {s}: ${((await EXCHANGE.fetch_ticker(s))['last']/d['entry_price']-1)*d['amount']:+.2f}" 
                             for s, d in portfolio["open_trades"].items()]) or "لا يوجد"
        
        msg = (f"📊 *التقرير الساعي الشامل*\n"
               f"💰 الرصيد الحالي: ${VIRTUAL_BALANCE:.2f}\n"
               f"💵 أرباح الساعة: ${profit_sum:+.2f}\n\n"
               f"📂 *الصفقات المفتوحة:*\n{open_list}\n\n"
               f"🏁 تم إغلاق {len(closed_this_hour)} صفقات بنجاح.")
        send_telegram_msg(msg)
        closed_this_hour = []

# ======================== 4. إدارة التداول (دخول/خروج) ========================

async def manage_exits():
    global VIRTUAL_BALANCE
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                current_price = ticker['last']
                profit_usd = (current_price / trade['entry_price'] - 1) * trade['amount']
                
                if profit_usd >= TARGET_PROFIT_USD:
                    VIRTUAL_BALANCE += (trade['amount'] + profit_usd)
                    closed_this_hour.append({"sym": sym, "profit": profit_usd})
                    portfolio.pop(sym, None) # استخدام pop لضمان الحذف الآمن من القاموس الداخلي
                    portfolio["open_trades"].pop(sym, None)
                    
                    send_telegram_msg(f"✅ *خرجنا بربح! (+${TARGET_PROFIT_USD})*\n🎫 {sym}\n💰 الرصيد: ${VIRTUAL_BALANCE:.2f}")
            await asyncio.sleep(15)
        except Exception as e:
            print(f"Exit Manager Error: {e}")
            await asyncio.sleep(5)

async def scanner_loop():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            # مسح 500 عملة مقسمة (Batches)
            all_symbols = [s for s in tickers.keys() if '/USDT' in s and tickers[s].get('quoteVolume', 0) > 5000000]
            sorted_symbols = sorted(all_symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:500]
            
            for i in range(0, len(sorted_symbols), 150):
                batch = sorted_symbols[i:i+150]
                for sym in batch:
                    if sym not in portfolio["open_trades"] and len(portfolio["open_trades"]) < MAX_OPEN_TRADES:
                        score, price = await calculate_pro_score(sym)
                        if score >= 80: # الدخول فقط للفرص الخارقة
                            portfolio["open_trades"][sym] = {"entry_price": price, "amount": TRADE_AMOUNT_USD}
                            VIRTUAL_BALANCE -= TRADE_AMOUNT_USD
                            send_telegram_msg(f"🚀 *قناص: دخول صفقة*\n🎫 {sym}\n📊 السكور: {score}%\n💰 السعر: {price}")
                        await asyncio.sleep(0.1) # راحة للمنصة
                await asyncio.sleep(2) # راحة بين المجموعات
            await asyncio.sleep(30) # انتظار قبل دورة المسح التالية
        except Exception as e:
            print(f"Scanner Error: {e}")
            await asyncio.sleep(10)

# ======================== 5. السيرفر والتشغيل النهائي ========================

app = Flask('')
@app.route('/')
def home(): return f"Snowball Sniper Active. Balance: {VIRTUAL_BALANCE:.2f} USDT"

async def main():
    send_telegram_msg("⚡ *تم تفعيل نظام القناص V15.0*\nالرصيد: $1000 | 500 عملة قيد المسح...")
    asyncio.create_task(manage_exits())
    asyncio.create_task(hourly_report())
    await scanner_loop()

if __name__ == "__main__":
    # تشغيل Flask باستخدام Waitress لإزالة التنبيه الأحمر
    threading.Thread(target=lambda: serve(app, host='0.0.0.0', port=10000), daemon=True).start()
    asyncio.run(main())
