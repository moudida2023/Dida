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

# ======================== 1. الإعدادات المحدثة (10 صفقات) ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509' 

EXCHANGE = ccxt.binance({'enableRateLimit': True})
VIRTUAL_BALANCE = 1000.0    # الرصيد الكلي
BASE_TRADE_USD = 100.0      # قيمة الصفقة الواحدة (1000 / 10 = 100$)
MAX_OPEN_TRADES = 10        # الحد الأقصى للصفقات المفتوحة
MIN_SCORE_TO_ENTRY = 80     

TRAILING_TRIGGER = 0.02    # تفعيل الملاحقة عند ربح 2%
TRAILING_CALLBACK = 0.01   # الإغلاق عند تراجع 1% من القمة

portfolio = {"open_trades": {}}
closed_trades_history = []

# ======================== 2. نظام الإشعارات والتقارير ========================

def send_telegram_msg(msg, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
        if reply_markup: payload["reply_markup"] = reply_markup
        requests.post(url, json=payload, timeout=10)
    except: pass

async def hourly_report_scheduler():
    while True:
        await asyncio.sleep(3600)
        now = datetime.now().strftime("%H:%M")
        open_msg = "📂 *OPEN ORDERS:*\n" + ("\n".join([f"• `{s}`" for s in portfolio["open_trades"]]) if portfolio["open_trades"] else "_None_")
        h_pnl = sum([t['pnl'] for t in closed_trades_history]) if closed_trades_history else 0
        closed_trades_history.clear()
        report = f"🕒 *HOURLY REPORT ({now})*\n\n{open_msg}\n✅ Profit Last Hour: `{h_pnl:.2f}$`"
        send_telegram_msg(report)

def handle_telegram_commands():
    global VIRTUAL_BALANCE
    last_id = 0
    main_menu = {"keyboard": [[{"text": "/status"}, {"text": "/report"}], [{"text": "/panic"}]], "resize_keyboard": True}
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_id+1}&timeout=10"
            res = requests.get(url, timeout=15).json()
            if "result" in res:
                for update in res["result"]:
                    last_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        msg = update["message"]["text"].lower()
                        if str(update["message"]["chat_id"]) != TELEGRAM_CHAT_ID: continue
                        if msg == "/status":
                            send_telegram_msg(f"📊 *STATUS:* Bal: `{VIRTUAL_BALANCE:.2f}$` | Active: `{len(portfolio['open_trades'])}/10`")
                        elif msg == "/panic":
                            for s in list(portfolio["open_trades"].keys()):
                                VIRTUAL_BALANCE += BASE_TRADE_USD
                                portfolio["open_trades"].pop(s)
                            send_telegram_msg("🚨 *PANIC:* 10 slots cleared. All trades closed.")
        except: time.sleep(5)
        time.sleep(1)

# ======================== 3. محرك تحليل 300 عملة ========================

def add_indicators(df):
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
    # RSI & MFI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain/loss)))
    tp = (df['high'] + df['low'] + df['close']) / 3
    rmf = tp * df['vol']
    df['mfi'] = 100 - (100 / (1 + (rmf.where(tp > tp.shift(1), 0).rolling(14).sum() / rmf.where(tp < tp.shift(1), 0).rolling(14).sum())))
    df['vol_avg'] = df['vol'].rolling(window=15).mean()
    return df

async def get_score(sym):
    try:
        b1h = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=30)
        df1h = add_indicators(pd.DataFrame(b1h, columns=['ts','open','high','low','close','vol']))
        b15m = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=30)
        df15m = add_indicators(pd.DataFrame(b15m, columns=['ts','open','high','low','close','vol']))
        l1h, l15m = df1h.iloc[-1], df15m.iloc[-1]
        
        score = 0
        if l1h['close'] > l1h['ema21']: score += 20
        if l15m['ema9'] > l15m['ema21']: score += 30
        if l15m['vol'] > l15m['vol_avg'] * 1.8: score += 25
        if l15m['mfi'] > 60: score += 25
        return score, l15m['close']
    except: return 0, 0

# ======================== 4. الإدارة والماسح الشامل ========================

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
                if t['trailing_active'] and (t['highest_price'] - cp) / t['highest_price'] >= TRAILING_CALLBACK:
                    pnl = (t['coins'] * cp) - t['amount_usd']
                    VIRTUAL_BALANCE += (t['amount_usd'] + pnl)
                    send_telegram_msg(f"💰 *EXIT:* `{sym}` | PNL: `{pnl:.2f}$`")
                    closed_trades_history.append({"sym": sym, "pnl": pnl})
                    portfolio["open_trades"].pop(sym)
                elif profit <= -0.04:
                    pnl = (t['coins'] * cp) - t['amount_usd']
                    VIRTUAL_BALANCE += (t['amount_usd'] + pnl)
                    send_telegram_msg(f"🛑 *SL:* `{sym}`")
                    closed_trades_history.append({"sym": sym, "pnl": pnl})
                    portfolio["open_trades"].pop(sym)
            await asyncio.sleep(5)
        except: await asyncio.sleep(5)

async def scanner():
    global VIRTUAL_BALANCE
    if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES: return
    try:
        tk = await EXCHANGE.fetch_tickers()
        syms = [s for s in tk.keys() if '/USDT' in s and tk[s]['quoteVolume'] > 1000000]
        sorted_syms = sorted(syms, key=lambda x: tk[x]['quoteVolume'], reverse=True)[:300]
        
        for s in sorted_syms:
            if s in portfolio["open_trades"] or VIRTUAL_BALANCE < BASE_TRADE_USD: continue
            sc, pr = await get_score(s)
            if sc >= MIN_SCORE_TO_ENTRY:
                portfolio["open_trades"][s] = {
                    "entry_price": pr, "highest_price": pr, "coins": BASE_TRADE_USD/pr,
                    "amount_usd": BASE_TRADE_USD, "trailing_active": False
                }
                VIRTUAL_BALANCE -= BASE_TRADE_USD
                send_telegram_msg(f"🟢 *ENTRY:* `{s}` | Score: `{sc}/100` | (Slot {len(portfolio['open_trades'])}/10)")
                if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES: break
            await asyncio.sleep(0.03) 
    except: pass

# ======================== 5. التشغيل ========================

app = Flask('')
@app.route('/')
def home(): return "Bot 1000$ - 10 Trades - 300 Scanning"

async def main_engine():
    send_telegram_msg("🚀 **Bot Ready: 10 Trade Slots Active**\nBalance: 1000$ | Each Trade: 100$")
    asyncio.create_task(trade_manager())
    asyncio.create_task(hourly_report_scheduler())
    while True:
        await scanner()
        await asyncio.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=handle_telegram_commands, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: serve(app, host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_engine())
