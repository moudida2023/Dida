import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import os
import gc
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. الإعدادات ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0
TRADE_SIZE_USD = 100.0  # القيمة الثابتة للدخول لكل صفقة
portfolio = {"open_trades": {}}
trade_history = {}
closed_trades_history = []
current_market_mode = "NORMAL"
daily_start_balance = 1000.0

# ======================== 2. وحدة ذكاء السوق ========================

async def get_market_regime():
    global current_market_mode
    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s]
        top_50 = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:50]
        up_count = sum(1 for sym in top_50 if tickers[sym]['percentage'] > 0.5)
        
        if up_count <= 10:
            current_market_mode = "PROTECT"
            return {"mode": "PROTECT", "max_trades": 3, "vol_mult": 6.0, "mfi_limit": 70, "count": 50}
        elif up_count >= 35:
            current_market_mode = "ULTRA_BULL"
            return {"mode": "ULTRA_BULL", "max_trades": 20, "vol_mult": 1.8, "mfi_limit": 40, "count": 400}
        else:
            current_market_mode = "NORMAL"
            return {"mode": "NORMAL", "max_trades": 10, "vol_mult": 3.0, "mfi_limit": 50, "count": 250}
    except:
        return {"mode": "NORMAL", "max_trades": 10, "vol_mult": 3.0, "mfi_limit": 50, "count": 250}

# ======================== 3. مسح السوق بنظام السكور 5/5 ========================

async def scan_market():
    global VIRTUAL_BALANCE
    regime = await get_market_regime()
    if len(portfolio["open_trades"]) >= regime['max_trades']: return
    
    # التأكد من توفر رصيد (100 دولار)
    if VIRTUAL_BALANCE < TRADE_SIZE_USD: return

    try:
        tickers = await EXCHANGE.fetch_tickers()
        # اختيار العملات بناءً على حجم التداول في الكود الأصلي
        symbols = [s for s in tickers.keys() if '/USDT' in s and tickers[s]['quoteVolume'] > 1200000]
        top_symbols = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[10:10+regime['count']]
        
        for sym in top_symbols:
            if sym in portfolio["open_trades"]: continue
            if sym in trade_history and (datetime.now() - trade_history[sym]).total_seconds() < 14400: continue
            
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=100)
            df = calculate_indicators(pd.DataFrame(bars, columns=['ts','open','high','low','close','vol']))
            last = df.iloc[-1]
            prev = df.iloc[-2]
            
            # --- نظام السكور الصارم 5/5 ---
            score = 0
            if last['close'] > last['ema9']: score += 1 # 1. السعر فوق المتوسط
            if last['close'] > last['open']: score += 1 # 2. شمعة خضراء
            if last['vol'] > df['vol'].rolling(10).mean().iloc[-1]: score += 1 # 3. حجم تداول متصاعد
            if last['close'] > prev['high']: score += 1 # 4. كسر قمة الشمعة السابقة
            if last['rsi'] > 50: score += 1 # 5. القوة النسبية إيجابية
            
            # الدخول فقط إذا اكتمل السكور 5/5
            if score == 5:
                entry_price = last['close']
                entry_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                portfolio["open_trades"][sym] = {
                    "entry_price": entry_price, 
                    "highest_p": entry_price, 
                    "amount": TRADE_SIZE_USD, # دخول بـ 100$
                    "time": entry_time
                }
                VIRTUAL_BALANCE -= TRADE_SIZE_USD
                trade_history[sym] = datetime.now()

                msg = (
                    f"🚀 *تم اكتشاف صفقة (Score 5/5)*\n"
                    f"🎫 {sym} | $100\n"
                    f"💰 السعر: {entry_price:.6f}\n"
                    f"📊 الوضع: {current_market_mode}"
                )
                send_telegram_msg(msg)
                
                if len(portfolio["open_trades"]) >= regime['max_trades']: break
            await asyncio.sleep(0.1)
    except: pass

# ======================== 4. إدارة الصفقات والخروج ========================

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                profit = (cp - trade['entry_price']) / trade['entry_price']
                
                entry_dt = datetime.strptime(trade['time'], '%Y-%m-%d %H:%M:%S')
                hours_passed = (datetime.now() - entry_dt).total_seconds() / 3600

                reason = None
                # جني أرباح 1.5 دولار (بناءً على طلبك السابق لـ 1.5)
                if (profit * trade['amount']) >= 1.5: reason = "🎯 هدف الربح"
                elif hours_passed >= 24: reason = "⏰ الزمن (24س)"
                elif profit <= -0.02: reason = "🛑 وقف خسارة -2%"

                if reason:
                    final_amount = trade['amount'] * (1 + profit)
                    VIRTUAL_BALANCE += final_amount
                    closed_trades_history.append({"sym": sym, "profit": profit * 100})
                    portfolio["open_trades"].pop(sym, None)
                    
                    msg = (
                        f"🏁 *إغلاق صفقة*\n"
                        f"🎫 {sym} | { (profit * 100):+.2f}%\n"
                        f"📝 السبب: {reason}\n"
                        f"💰 الرصيد: ${VIRTUAL_BALANCE:.2f}"
                    )
                    send_telegram_msg(msg)

            await asyncio.sleep(20)
        except: await asyncio.sleep(5)

# ======================== 5. التقارير والدوال المساعدة ========================

async def periodic_reports():
    global daily_start_balance
    last_4h = datetime.now()
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        if now - last_4h >= timedelta(hours=4):
            report = f"🕒 *تقرير 4س*\n📂 مفتوح: {len(portfolio['open_trades'])}\n💰 الرصيد: ${VIRTUAL_BALANCE:.2f}"
            send_telegram_msg(report)
            last_4h = now

def calculate_indicators(df):
    close = df['close']
    df['ema9'] = close.ewm(span=9, adjust=False).mean()
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    return df

def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

app = Flask('')
@app.route('/')
def home(): return f"Snowball 5/5 Active: {VIRTUAL_BALANCE:.2f} USDT"

async def main_loop():
    send_telegram_msg("✅ *Snowball v11.9* بدأ العمل بنظام السكور 5/5 ودخول 100$.")
    asyncio.create_task(manage_trades())
    asyncio.create_task(periodic_reports())
    while True:
        try:
            await scan_market()
            await asyncio.sleep(60)
        except: await asyncio.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    asyncio.run(main_loop())
