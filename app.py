import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
from flask import Flask
from waitress import serve
from datetime import datetime

# ======================== 1. الإعدادات التجريبية (مكثفة) ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 5000.0      # رصيد وهمي كبير للتجربة
MAX_OPEN_TRADES = 50         # رفع الحد الأقصى للصفقات
TRADE_AMOUNT_USD = 20.0      # مبلغ صغير لفتح صفقات أكثر
TARGET_PROFIT_USD = 0.5      # هدف ربح قريب للخروج السريع
TRAILING_GAP_USD = 0.15      # ملاحقة ربح حساسة
ENTRY_SCORE_THRESHOLD = 110  # سكور منخفض لزيادة عدد الصفقات

portfolio = {"open_trades": {}}
stats = {"win": 0, "loss": 0, "total_profit": 0.0} # سجل الإحصائيات
closed_this_hour = []

# ======================== 2. محرك التحليل والسكور ========================

def check_candlestick_patterns(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    body = abs(last['close'] - last['open'])
    l_shadow = min(last['open'], last['close']) - last['low']
    score = 0
    if l_shadow > (body * 1.5) and body > 0: score += 25
    if last['close'] > prev['open'] and last['open'] < prev['close']: score += 25
    return min(score, 40)

async def calculate_mega_score(symbol):
    try:
        bars = await EXCHANGE.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
        close = df['close']
        basis = close.rolling(20).mean()
        std = close.rolling(20).std()
        df['bb_width'] = (std * 4) / basis
        upper_bb = basis + (std * 2)
        df['ema200'] = close.ewm(span=200).mean()
        
        last, score = df.iloc[-1], 0

        # فلاتر القمة (مخففة قليلاً للتجربة)
        if (last['close'] - last['ema200']) / last['ema200'] > 0.15: return 0, 0
        if last['close'] > upper_bb.iloc[-1] * 1.02: return 0, 0

        if last['bb_width'] < 0.07: score += 50 
        score += check_candlestick_patterns(df)
        
        ob = await EXCHANGE.fetch_order_book(symbol, limit=20)
        if sum([b[1] for b in ob['bids']]) > sum([a[1] for a in ob['asks']]): score += 30
        if last['close'] > last['ema200']: score += 30
        
        return score, last['close']
    except: return 0, 0

# ======================== 3. إدارة التنفيذ والمسح السريع ========================

async def try_instant_entry(symbol):
    global VIRTUAL_BALANCE
    if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES or VIRTUAL_BALANCE < TRADE_AMOUNT_USD: return
    score, price = await calculate_mega_score(symbol)
    
    if score >= ENTRY_SCORE_THRESHOLD:
        portfolio["open_trades"][symbol] = {"entry_price": price, "amount": TRADE_AMOUNT_USD, "max_pnl": 0}
        VIRTUAL_BALANCE -= TRADE_AMOUNT_USD
        send_telegram_msg(f"⚡ *تجربة: دخول فوري*\n🎫 {symbol}\n📊 السكور: {score}\n💰 السعر: {price}")

async def scanner_loop():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            # مسح واسع (أي عملة سيولتها فوق مليون دولار)
            symbols = [s for s in tickers.keys() if '/USDT' in s and tickers[s].get('quoteVolume',0) > 1000000]
            sorted_syms = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:500]
            
            for i in range(0, len(sorted_syms), 150):
                tasks = [try_instant_entry(s) for s in sorted_syms[i:i+150] if s not in portfolio["open_trades"]]
                await asyncio.gather(*tasks)
            await asyncio.sleep(5) # فحص متكرر كل 5 ثوانٍ
        except: await asyncio.sleep(5)

# ======================== 4. إدارة الأرباح والتقارير والإحصائيات ========================

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
                        # تحديث الإحصائيات عند الإغلاق
                        VIRTUAL_BALANCE += (t['amount'] + pnl)
                        if pnl > 0: stats["win"] += 1
                        else: stats["loss"] += 1
                        
                        closed_this_hour.append(pnl)
                        portfolio.pop(sym) if isinstance(portfolio, dict) else portfolio["open_trades"].pop(sym)
                        send_telegram_msg(f"✅ *تم الإغلاق*\n🎫 {sym}\n💵 الربح: ${pnl:.2f}")
            await asyncio.sleep(5)
        except: await asyncio.sleep(5)

def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except: pass

async def hourly_report():
    global closed_this_hour
    while True:
        await asyncio.sleep(3600)
        total_trades = stats["win"] + stats["loss"]
        win_rate = (stats["win"] / total_trades * 100) if total_trades > 0 else 0
        p_hour = sum(closed_this_hour)
        
        report = (f"📊 *تقرير الأداء الساعي*\n"
                  f"💰 الرصيد: ${VIRTUAL_BALANCE:.2f}\n"
                  f"💵 أرباح الساعة: ${p_hour:+.2f}\n"
                  f"✅ صفقات ناجحة: {stats['win']}\n"
                  f"❌ صفقات خاسرة: {stats['loss']}\n"
                  f"🎯 نسبة النجاح: %{win_rate:.1f}\n"
                  f"📂 صفقات مفتوحة: {len(portfolio['open_trades'])}")
        
        send_telegram
