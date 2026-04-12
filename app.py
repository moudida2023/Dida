import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import time
import os
from datetime import datetime
from flask import Flask
from waitress import serve

# ======================== 1. الإعدادات ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509' 

EXCHANGE = ccxt.binance({'enableRateLimit': True})
VIRTUAL_BALANCE = 500.0    
BASE_TRADE_USD = 100.0     
MAX_OPEN_TRADES = 5        
MIN_SCORE_TO_ENTRY = 75    

TRAILING_TRIGGER = 0.02    
TRAILING_CALLBACK = 0.01   

portfolio = {"open_trades": {}}
closed_trades_history = []

# ======================== 2. إصلاح دالة التليجرام ========================

def send_telegram_msg(msg, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
        if reply_markup: payload["reply_markup"] = reply_markup
        requests.post(url, json=payload, timeout=10)
    except: pass

def handle_telegram_commands():
    # تعريف global في بداية الدالة وقبل أي كود آخر
    global VIRTUAL_BALANCE
    last_id = 0
    main_menu = {
        "keyboard": [[{"text": "📊 حالة المحفظة"}, {"text": "📑 تقرير الساعة"}], [{"text": "🚨 إغلاق فوري (Panic)"}]],
        "resize_keyboard": True
    }

    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_id+1}&timeout=10"
            res = requests.get(url, timeout=15).json()
            if "result" in res:
                for update in res["result"]:
                    last_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        msg = update["message"]["text"]
                        if str(update["message"]["chat_id"]) != TELEGRAM_CHAT_ID: continue

                        if msg in ["/start", "العودة"]:
                            send_telegram_msg("🤖 نظام التداول جاهز:", main_menu)
                        elif msg == "📊 حالة المحفظة":
                            send_telegram_msg(f"💰 *الرصيد:* `{VIRTUAL_BALANCE:.2f}$`\n🔄 *الصفقات:* `{len(portfolio['open_trades'])}`")
                        elif msg == "🚨 إغلاق فوري (Panic)":
                            count = len(portfolio["open_trades"])
                            for s in list(portfolio["open_trades"].keys()):
                                VIRTUAL_BALANCE += BASE_TRADE_USD
                                portfolio["open_trades"].pop(s)
                            send_telegram_msg(f"⚠️ تم تصفية `{count}` صفقات.")
        except: time.sleep(5)
        time.sleep(1)

# ======================== 3. المحرك الفني وإدارة الصفقات ========================

def add_indicators(df):
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain/loss)))
    df['vol_avg'] = df['vol'].rolling(window=10).mean()
    mfm = ((df['close'] - df['low']) - (df['high'] - df['close'])) / (df['high'] - df['low'])
    df['cmf'] = (mfm * df['vol']).rolling(20).sum() / df['vol'].rolling(20).sum()
    return df

async def get_score(sym):
    try:
        b1h = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=30)
        df1h = add_indicators(pd.DataFrame(b1h, columns=['ts','open','high','low','close','vol']))
        b15m = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=30)
        df15m = add_indicators(pd.DataFrame(b15m, columns=['ts','open','high','low','close','vol']))
        l1h, l15m = df1h.iloc[-1], df15m.iloc[-1]
        score = 0
        if l1h['close'] > l1h['ema21']: score += 30
        if l15m['ema9'] > l15m['ema21']: score += 30
        if l15m['vol'] > l15m['vol_avg'] * 1.7: score += 20
        if l15m['cmf'] > 0.1: score += 20
        return score, l15m['close']
    except: return 0, 0

async def trade_manager():
    global VIRTUAL_BALANCE
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                t = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                if cp > t['highest_price']: t['highest_price'] = cp
                profit = (cp - t['entry_price']) / t['entry_price']
                if profit >= TRAILING_TRIGGER: t['trailing_active'] = True
                if t['trailing_active']:
                    if (t['highest_price'] - cp) / t['highest_price'] >= TRAILING_CALLBACK:
                        pnl = (t['coins'] * cp) - t['amount_usd']
                        VIRTUAL_BALANCE += (t['amount_usd'] + pnl)
                        send_telegram_msg(f"💰 *جني أرباح:* `{sym}` | الربح: `{pnl:.2f}$`")
                        portfolio["open_trades"].pop(sym)
                elif profit <= -0.04:
                    VIRTUAL_BALANCE += (t['coins'] * cp)
                    portfolio["open_trades"].pop(sym)
            await asyncio.sleep(10)
        except: await asyncio.sleep(10)

async def scanner():
    global VIRTUAL_BALANCE
    if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES: return
    try:
        tk = await EXCHANGE.fetch_tickers()
        syms = [s for s in tk.keys() if '/USDT' in s and tk[s]['quoteVolume'] > 2000000]
        for s in sorted(syms, key=lambda x: tk[x]['quoteVolume'], reverse=True)[:40]:
            if s in portfolio["open_trades"] or VIRTUAL_BALANCE < BASE_TRADE_USD: continue
            sc, pr = await get_score(s)
            if sc >= MIN_SCORE_TO_ENTRY:
                portfolio["open_trades"][s] = {"entry_price": pr, "highest_price": pr, "coins": BASE_TRADE_USD/pr, "amount_usd": BASE_TRADE_USD, "trailing_active": False}
                VIRTUAL_BALANCE -= BASE_TRADE_USD
                send_telegram_msg(f"🟢 *فتح صفقة:* `{s}` | سكور: `{sc}`")
            await asyncio.sleep(0.1)
    except: pass

app = Flask('')
@app.route('/')
def home(): return "Scoring Bot Fixed"

async def main():
    send_telegram_msg("🚀 **تم تشغيل البوت بنجاح!**")
    asyncio.create_task(trade_manager())
    while True:
        await scanner()
        await asyncio.sleep(60)

if __name__ == "__main__":
    # تشغيل نظام الأوامر في خيط منفصل
    threading.Thread(target=handle_telegram_commands, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: serve(app, host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main())
