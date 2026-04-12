import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import time
import os
from flask import Flask

# ======================== 1. الإعدادات ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509' 

EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0   
BASE_TRADE_USD = 100.0     
MAX_OPEN_TRADES = 10       
TRAILING_TRIGGER = 0.02    
TRAILING_CALLBACK = 0.005  

portfolio = {"open_trades": {}}
closed_trades_history = []

# ======================== 2. محرك التحليل ========================
def get_indicators(df):
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    tp = (df['high'] + df['low'] + df['close']) / 3
    mf = tp * df['vol']
    pos = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    df['mfi'] = 100 - (100 / (1 + (pos / neg)))
    return df

# ======================== 3. مستمع الأوامر (الإصلاح النهائي) ========================
def handle_telegram_commands():
    global VIRTUAL_BALANCE
    last_update_id = 0
    print("📡 نظام الاستماع للأوامر نشط الآن...")
    
    while True:
        try:
            # استخدام timeout طويل لمنع تعليق الخيط
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=20"
            res = requests.get(url, timeout=25).json()
            
            if "result" in res:
                for update in res["result"]:
                    last_update_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"].lower().strip()
                        chat_id = str(update["message"]["chat_id"])
                        
                        if chat_id != TELEGRAM_CHAT_ID: continue

                        if text == "/start":
                            send_telegram_msg("🚀 **تم تفعيل الرادار الشامل!**\nالرصيد: 1000$\nالأوامر المتاحة:\n/status - حالة المحفظة\n/report - الصفقات الحالية\n/panic - إغلاق كل شيء")
                        
                        elif text == "/status":
                            pnl = sum([t['pnl'] for t in closed_trades_history])
                            msg = (f"📊 **تقرير الحساب:**\n"
                                   f"💰 الرصيد: `${VIRTUAL_BALANCE:.2f}`\n"
                                   f"📈 الأرباح: `${pnl:.2f}`\n"
                                   f"🔄 صفقات نشطة: `{len(portfolio['open_trades'])}`")
                            send_telegram_msg(msg)

                        elif text == "/report":
                            if not portfolio["open_trades"]:
                                send_telegram_msg("📭 لا توجد صفقات مفتوحة حالياً.")
                            else:
                                report = "📑 **قائمة الصفقات المفتوحة:**\n"
                                for sym, data in portfolio["open_trades"].items():
                                    report += f"• `{sym}`: @ {data['entry_price']:.5f}\n"
                                send_telegram_msg(report)

                        elif text == "/panic":
                            count = len(portfolio["open_trades"])
                            for s in list(portfolio["open_trades"].keys()):
                                VIRTUAL_BALANCE += portfolio["open_trades"][s]['amount_usd']
                                portfolio["open_trades"].pop(s)
                            send_telegram_msg(f"🚨 **Panic Mode!** تم إغلاق {count} صفقات.")

        except Exception as e:
            print(f"Telegram Thread Error: {e}")
            time.sleep(2)

# ======================== 4. منطق التداول والمسح (500 عملة) ========================
async def scan_market():
    global VIRTUAL_BALANCE
    if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES: return 
    
    try:
        tickers = await EXCHANGE.fetch_tickers()
        all_symbols = [s for s in tickers.keys() if '/USDT' in s and tickers[s]['quoteVolume'] > 500000]
        top_500 = sorted(all_symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:500]
        
        batch_size = 100
        for i in range(0, len(top_500), batch_size):
            batch = top_500[i:i + batch_size]
            for sym in batch:
                if sym in portfolio["open_trades"] or VIRTUAL_BALANCE < BASE_TRADE_USD: continue
                try:
                    bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=40)
                    df = get_indicators(pd.DataFrame(bars, columns=['ts','open','high','low','close','vol']))
                    last = df.iloc[-1]
                    
                    if last['close'] > last['ema9'] and last['mfi'] > 50 and last['vol'] > df['vol'].tail(10).mean() * 1.2:
                        portfolio["open_trades"][sym] = {
                            "entry_price": last['close'], "highest_price": last['close'],
                            "coins": BASE_TRADE_USD / last['close'], "amount_usd": BASE_TRADE_USD, "trailing_active": False
                        }
                        VIRTUAL_BALANCE -= BASE_TRADE_USD
                        send_telegram_msg(f"🎯 **قنص:** `{sym}`\n💰 الرصيد المتاح: `${VIRTUAL_BALANCE:.2f}`")
                        if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES: return
                except: continue
            await asyncio.sleep(1) 
    except: pass

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                if cp > trade['highest_price']: trade['highest_price'] = cp
                profit_pct = (cp - trade['entry_price']) / trade['entry_price']
                
                if profit_pct >= TRAILING_TRIGGER: trade['trailing_active'] = True
                if trade['trailing_active'] and (trade['highest_price'] - cp) / trade['highest_price'] >= TRAILING_CALLBACK:
                    pnl = (trade['coins'] * cp) - trade['amount_usd']
                    VIRTUAL_BALANCE += (trade['amount_usd'] + pnl)
                    closed_trades_history.append({"pnl": pnl})
                    portfolio["open_trades"].pop(sym)
                    send_telegram_msg(f"💰 **ربح:** `{sym}` | +${pnl:.2f}")
                elif profit_pct <= -0.04:
                    VIRTUAL_BALANCE += (trade['coins'] * cp)
                    portfolio["open_trades"].pop(sym)
                    send_telegram_msg(f"🛑 **وقف خسارة:** `{sym}`")
            await asyncio.sleep(10)
        except: await asyncio.sleep(5)

# ======================== 5. التشغيل النهائي ========================
def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

app = Flask('')
@app.route('/')
def home(): return "FINAL VERSION ACTIVE"

async def main_loop():
    send_telegram_msg("✅ **البوت يعمل الآن بكامل طاقته!**")
    asyncio.create_task(manage_trades())
    while True:
        await scan_market()
        await asyncio.sleep(20)

if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", 8080))
    # تشغيل مستمع الأوامر في خيط مستقل تماماً
    cmd_thread = threading.Thread(target=handle_telegram_commands)
    cmd_thread.daemon = True
    cmd_thread.start()
    
    # تشغيل محرك التداول في خيط مستقل
    logic_thread = threading.Thread(target=lambda: asyncio.run(main_loop()))
    logic_thread.daemon = True
    logic_thread.start()
    
    # السيرفر الرئيسي
    print(f"🚀 البوت يعمل على المنفذ {port}")
    serve(app, host='0.0.0.0', port=port)
