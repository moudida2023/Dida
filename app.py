import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import time
import os
from flask import Flask

# ======================== 1. الإعدادات والتحكم ========================
# تأكد أن هذا هو الـ ID الخاص بك (يمكنك الحصول عليه من بوت @userinfobot)
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509' 

EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0
BASE_TRADE_USD = 100.0
TRAILING_TRIGGER = 0.02    
TRAILING_CALLBACK = 0.005  

portfolio = {"open_trades": {}}
closed_trades_history = []

# ======================== 2. نظام الأوامر (تحديث: مع نظام تشخيص) ========================

def handle_telegram_commands():
    global VIRTUAL_BALANCE
    last_update_id = 0
    print("🤖 مستمع أوامر تليجرام بدأ العمل...")
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=30"
            response = requests.get(url, timeout=35).json()
            
            if "result" in response:
                for update in response["result"]:
                    last_update_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"].lower().strip()
                        chat_id = str(update["message"]["chat_id"])
                        
                        # سطر للتشخيص يظهر في Logs موقع Railway
                        print(f"📩 رسالة مستلمة: {text} من ID: {chat_id}")

                        if chat_id != TELEGRAM_CHAT_ID:
                            print("⚠️ رسالة من مستخدم غير مصرح له، تم التجاهل.")
                            continue

                        if text == "/status":
                            total_pnl = sum([t['pnl'] for t in closed_trades_history])
                            msg = (f"💰 **حالة المحفظة:**\n"
                                   f"• الرصيد الحالي: `${VIRTUAL_BALANCE:.2f}`\n"
                                   f"• الأرباح المحققة: `${total_pnl:.2f}`\n"
                                   f"• صفقات مفتوحة: `{len(portfolio['open_trades'])}`")
                            send_telegram_msg(msg)

                        elif text == "/report":
                            if not portfolio["open_trades"]:
                                send_telegram_msg("📭 لا توجد صفقات مفتوحة حالياً.")
                            else:
                                report = "📑 **تقرير الصفقات:**\n"
                                for sym, data in portfolio["open_trades"].items():
                                    report += f"• `{sym}`: دخول @ {data['entry_price']:.4f}\n"
                                send_telegram_msg(report)

                        elif text == "/panic":
                            count = len(portfolio["open_trades"])
                            for sym in list(portfolio["open_trades"].keys()):
                                trade = portfolio["open_trades"][sym]
                                VIRTUAL_BALANCE += trade['amount_usd']
                                portfolio["open_trades"].pop(sym)
                            send_telegram_msg(f"⚠️ **PANIC:** تم إغلاق {count} صفقات فوراً!")

                        elif text.startswith("/close "):
                            sym = text.split(" ")[1].upper()
                            if not sym.endswith("/USDT"): sym += "/USDT"
                            if sym in portfolio["open_trades"]:
                                VIRTUAL_BALANCE += portfolio["open_trades"][sym]['amount_usd']
                                portfolio["open_trades"].pop(sym)
                                send_telegram_msg(f"✅ تم إغلاق `{sym}` يدوياً.")
                            else:
                                send_telegram_msg(f"❌ العملة `{sym}` غير موجودة.")

        except Exception as e:
            print(f"❌ خطأ في تليجرام: {e}")
        time.sleep(1)

# ======================== 3. محرك التداول (8/8) ========================

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
    if len(portfolio["open_trades"]) >= 5: return
    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s and tickers[s]['quoteVolume'] > 3000000]
        for sym in sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:30]:
            if sym in portfolio["open_trades"]: continue
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=50)
            df = get_indicators(pd.DataFrame(bars, columns=['ts','open','high','low','close','vol']))
            last = df.iloc[-1]
            
            # شرط دخول 8/8 سكالبينج
            if last['close'] > last['ema9'] and last['mfi'] > 60 and last['vol'] > df['vol'].tail(10).mean() * 1.5:
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
                        send_telegram_msg(f"💰 **جني أرباح:** `{sym}` | +${pnl:.2f}")
                elif profit_pct <= -0.03:
                    VIRTUAL_BALANCE += (trade['coins'] * cp)
                    portfolio["open_trades"].pop(sym)
                    send_telegram_msg(f"🛑 **وقف خسارة:** `{sym}`")
            await asyncio.sleep(10)
        except: await asyncio.sleep(5)

# ======================== 4. تشغيل السيرفر ========================

def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

app = Flask('')
@app.route('/')
def home():
