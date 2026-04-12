import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import os
import time
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات المحسنة ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0
TRADE_SIZE_USD = 100.0      
PROFIT_TARGET_USD = 1.5     # تم التعديل إلى 1.5 دولار ربح مستهدف

portfolio = {"open_trades": {}}
closed_trades_history = []

# ======================== 2. نظام الأوامر (Start / Report / Status) ========================

def telegram_command_listener():
    last_update_id = -1
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=30"
            response = requests.get(url, timeout=35).json()
            if response.get("result"):
                for update in response["result"]:
                    last_update_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        chat_id = str(update["message"]["chat"]["id"])
                        text = update["message"]["text"].lower()

                        if chat_id == TELEGRAM_CHAT_ID:
                            if text == "/start":
                                msg = (
                                    "🚀 *نظام القناص v11.8*\n"
                                    "🎯 الهدف الحالي: +1.5$ (بدون SL)\n"
                                    "💰 الدخول: $100 ثابتة\n"
                                    "استخدم /report لمتابعة أرباحك."
                                )
                                send_telegram_msg(msg)
                            elif text in ["/report", "تقرير", "/status"]:
                                send_telegram_msg(f"📊 *تقرير الأداء الحالي:*\n{generate_report_text()}")
        except: time.sleep(5)
        time.sleep(1)

def generate_report_text():
    total_pnl = sum(t['pnl'] for t in closed_trades_history)
    wins = len(closed_trades_history)
    return (f"📂 صفقات مفتوحة: {len(portfolio['open_trades'])}\n"
            f"✅ صفقات ناجحة (TP): {wins}\n"
            f"💰 إجمالي الأرباح: `${total_pnl:.2f}`\n"
            f"💵 الرصيد الحالي: `${VIRTUAL_BALANCE:.2f}`")

# ======================== 3. منطق التداول (TP = 1.5$) ========================

async def scan_market():
    global VIRTUAL_BALANCE
    if len(portfolio["open_trades"]) >= 10 or VIRTUAL_BALANCE < TRADE_SIZE_USD: return
    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s and tickers[s]['quoteVolume'] > 1500000]
        top_symbols = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:50]
        
        for sym in top_symbols:
            if sym in portfolio["open_trades"]: continue
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=50)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            
            # حساب السكور (دخول عند 70+)
            score = 0
            ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[-1]
            if df['close'].iloc[-1] > ema9: score += 40
            if df['close'].iloc[-1] > df['open'].iloc[-1]: score += 30
            if df['vol'].iloc[-1] > df['vol'].rolling(10).mean().iloc[-1]: score += 30
            
            if score >= 70:
                entry_price = df['close'].iloc[-1]
                portfolio["open_trades"][sym] = {
                    "entry_price": entry_price,
                    "coins": TRADE_SIZE_USD / entry_price,
                    "amount_usd": TRADE_SIZE_USD
                }
                VIRTUAL_BALANCE -= TRADE_SIZE_USD
                send_telegram_msg(f"🚀 *دخول صفقة*\n🎫 {sym}\n💵 السعر: {entry_price:.6f}\n🎯 الهدف: +1.5$")
                break 
    except: pass

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                
                # حساب الربح الصافي بالدولار
                profit_usd = (trade['coins'] * cp) - trade['amount_usd']
                
                # شرط الخروج عند تحقيق 1.5 دولار ربح
                if profit_usd >= PROFIT_TARGET_USD:
                    VIRTUAL_BALANCE += (trade['amount_usd'] + profit_usd)
                    closed_trades_history.append({"sym": sym, "pnl": profit_usd})
                    portfolio["open_trades"].pop(sym)
                    send_telegram_msg(f"🎯 *تم ضرب الهدف (+1.5$)*\n🎫 {sym}\n💰 الربح المحقق: ${profit_usd:.2f}")
            
            await asyncio.sleep(15) # فحص متكرر لضمان عدم فوات الهدف
        except: await asyncio.sleep(5)

# ======================== 4. التشغيل ========================

def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

app = Flask('')
@app.route('/')
def home(): return f"Snowball v11.8 Active - TP: 1.5 USD"

async def main_loop():
    send_telegram_msg("✅ *تم التحديث: الهدف الجديد 1.5$*")
    asyncio.create_task(manage_trades())
    threading.Thread(target=telegram_command_listener, daemon=True).start()
    while True:
        await scan_market()
        await asyncio.sleep(60)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_loop())
