import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import time
import os
from flask import Flask

# ======================== 1. الإعدادات والتحكم ========================
# توكن البوت والـ Chat ID الخاص بك
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# إعداد المنصة (Binance)
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# إعدادات المحفظة الافتراضية
VIRTUAL_BALANCE = 1000.0
BASE_TRADE_USD = 100.0

# إعدادات الهدف (2% ملاحقة مع 0.5% تراجع)
TRAILING_TRIGGER = 0.02    
TRAILING_CALLBACK = 0.005  

portfolio = {"open_trades": {}}
closed_trades_history = []

# ======================== 2. أوامر تليجرام (التحكم عن بُعد) ========================

def handle_telegram_commands():
    global VIRTUAL_BALANCE
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=20"
            response = requests.get(url, timeout=25).json()
            
            if "result" in response:
                for update in response["result"]:
                    last_update_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"].lower().strip()
                        chat_id = str(update["message"]["chat_id"])
                        
                        if chat_id != TELEGRAM_CHAT_ID: continue

                        # /status - عرض الرصيد والارباح
                        if text == "/status":
                            pnl = sum([t['pnl'] for t in closed_trades_history])
                            msg = (f"💰 **الحالة الحالية:**\n"
                                   f"• الرصيد: `${VIRTUAL_BALANCE:.2f}`\n"
                                   f"• الأرباح المحققة: `${pnl:.2f}`\n"
                                   f"• صفقات نشطة: `{len(portfolio['open_trades'])}`")
                            send_telegram_msg(msg)

                        # /report - عرض العملات المفتوحة
                        elif text == "/report":
                            if not portfolio["open_trades"]:
                                send_telegram_msg("📭 لا توجد صفقات حالياً.")
                            else:
                                report = "📑 **تقرير الصفقات:**\n"
                                for sym, data in portfolio["open_trades"].items():
                                    report += f"• `{sym}`: @ {data['entry_price']:.5f}\n"
                                send_telegram_msg(report)

                        # /panic - إغلاق كل شيء فوراً
                        elif text == "/panic":
                            count = len(portfolio["open_trades"])
                            for sym in list(portfolio["open_trades"].keys()):
                                VIRTUAL_BALANCE += portfolio["open_trades"][sym]['amount_usd']
                                portfolio["open_trades"].pop(sym)
                            send_telegram_msg(f"⚠️ **PANIC:** تم إغلاق {count} صفقات بنجاح.")

                        # /close SYMBOL - إغلاق عملة محددة
                        elif text.startswith("/close "):
                            sym = text.split(" ")[1].upper()
                            if not sym.endswith("/USDT"): sym += "/USDT"
                            if sym in portfolio["open_trades"]:
                                VIRTUAL_BALANCE += portfolio["open_trades"][sym]['amount_usd']
                                portfolio["open_trades"].pop(sym)
                                send_telegram_msg(f"✅ تم إغلاق `{sym}` يدوياً.")

        except: pass
        time.sleep(1)

# ======================== 3. محرك التداول (السكور 8/8) ========================

def get_indicators(df):
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    basis = df['close'].rolling(window=20).mean()
    std = df['close'].rolling(window=20).std()
    df['bandwidth'] = (4 * std) / basis
    tp = (df['high'] + df['low'] + df['close']) / 3
    mf = tp * df['vol']
    pos = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    df['mfi'] = 100 - (100 / (1 + (pos / neg)))
    return df

async def scan_market():
    global VIRTUAL_BALANCE
    if len(portfolio["open_trades"]) >= 5 or VIRTUAL_BALANCE < BASE_TRADE_USD: return
    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s and tickers[s]['quoteVolume'] > 2000000]
        
        for sym in sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:30]:
            if sym in portfolio["open_trades"] or 'UP/' in sym or 'DOWN/' in sym: continue
            
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=50)
            df = get_indicators(pd.DataFrame(bars, columns=['ts','open','high','low','close','vol']))
            last = df.iloc[-1]
            
            # شرط دخول 8/8 مع انفجار فوليوم
            if last['close'] > last['ema9'] and last['mfi'] > 60 and last['vol'] > df['vol'].tail(10).mean() * 1.8:
                portfolio["open_trades"][sym] = {
                    "entry_price": last['close'], "highest_price": last['close'],
                    "coins": BASE_TRADE_USD / last['close'], "amount_usd": BASE_TRADE_USD, "trailing_active": False
                }
                VIRTUAL_BALANCE -= BASE_TRADE_USD
                send_telegram_msg(f"🚀 **دخول:** `{sym}` @ {last['close']:.6f}")
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
                
                if cp > trade['highest_price']: trade['highest_price'] = cp
                profit_pct = (cp - trade['entry_price']) / trade['entry_price']
                
                if profit_pct >= TRAILING_TRIGGER: trade['trailing_active'] = True
                
                if trade['trailing_active']:
                    if (trade['highest_price'] - cp) / trade['highest_price'] >= TRAILING_CALLBACK:
                        pnl = (trade['coins'] * cp) - trade['amount_usd']
                        VIRTUAL_BALANCE += (trade['amount_usd'] + pnl)
                        closed_trades_history.append({"pnl": pnl})
                        portfolio["open_trades"].pop(sym)
                        send_telegram_msg(f"💰 **إغلاق ربح:** `{sym}` | +${pnl:.2f}")
                elif profit_pct <= -0.03:
                    VIRTUAL_BALANCE += (trade['coins'] * cp)
                    portfolio["open_trades"].pop(sym)
                    send_telegram_msg(f"🛑 **وقف خسارة:** `{sym}`")
            await asyncio.sleep(15)
        except: await asyncio.sleep(5)

# ======================== 4. تشغيل السيرفر والبوت ========================

def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

app = Flask('')
@app.route('/')
def home(): return f"Bot is running - Virtual Balance: ${VIRTUAL_BALANCE:.2f}"

async def main_loop():
    send_telegram_msg("✅ **تم تشغيل البوت على Railway بنجاح!**\nالبوت الآن يراقب السوق 24/24.")
    asyncio.create_task(manage_trades())
    while True:
        await scan_market()
        await asyncio.sleep(45)

if __name__ == "__main__":
    # Railway يطلب PORT متغير، الكود يسحب القيمة تلقائياً
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=handle_telegram_commands, daemon=True).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_loop())
