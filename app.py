import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import time
import os
from flask import Flask

# ======================== 1. الإعدادات الأساسية ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509' 

EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0   # الرصيد الافتراضي المطلوب
BASE_TRADE_USD = 100.0     # قيمة كل صفقة
MAX_OPEN_TRADES = 10       # الحد الأقصى للصفقات المتزامنة
TRAILING_TRIGGER = 0.02    # بدء الملاحقة عند ربح 2%
TRAILING_CALLBACK = 0.005  # الإغلاق عند تراجع 0.5% من القمة

portfolio = {"open_trades": {}}
closed_trades_history = []

# ======================== 2. محرك التحليل الفني ========================

def get_indicators(df):
    # حساب المتوسط المتحرك EMA 9
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    # حساب مؤشر تدفق الأموال MFI
    tp = (df['high'] + df['low'] + df['close']) / 3
    mf = tp * df['vol']
    pos = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    df['mfi'] = 100 - (100 / (1 + (pos / neg)))
    return df

# ======================== 3. نظام المسح (500 عملة) ========================

async def scan_market():
    global VIRTUAL_BALANCE
    if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES: return 
    
    try:
        tickers = await EXCHANGE.fetch_tickers()
        # تصفية العملات التي تملك سيولة معقولة (أكثر من 500 ألف دولار)
        all_symbols = [s for s in tickers.keys() if '/USDT' in s and tickers[s]['quoteVolume'] > 500000]
        # اختيار أفضل 500 عملة حسب حجم التداول
        top_500 = sorted(all_symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:500]
        
        # تقسيم العملات لمجموعات من 100 لتجنب ضغط السيرفر
        batch_size = 100
        for i in range(0, len(top_500), batch_size):
            batch = top_500[i:i + batch_size]
            for sym in batch:
                if sym in portfolio["open_trades"] or VIRTUAL_BALANCE < BASE_TRADE_USD: continue

                try:
                    bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=40)
                    df = get_indicators(pd.DataFrame(bars, columns=['ts','open','high','low','close','vol']))
                    last = df.iloc[-1]
                    
                    # الشروط الهجومية المخففة لفتح صفقات أكثر
                    if last['close'] > last['ema9'] and last['mfi'] > 50 and last['vol'] > df['vol'].tail(10).mean() * 1.2:
                        portfolio["open_trades"][sym] = {
                            "entry_price": last['close'], "highest_price": last['close'],
                            "coins": BASE_TRADE_USD / last['close'], "amount_usd": BASE_TRADE_USD, "trailing_active": False
                        }
                        VIRTUAL_BALANCE -= BASE_TRADE_USD
                        send_telegram_msg(f"🎯 **قنص:** `{sym}` @ {last['close']:.6f}\n💰 الرصيد المتاح: `${VIRTUAL_BALANCE:.2f}`")
                        
                        if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES: return
                except: continue
            await asyncio.sleep(1) # راحة قصيرة بين المجموعات
    except Exception as e: print(f"Scan Error: {e}")

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                
                # تحديث أعلى سعر للملاحقة
                if cp > trade['highest_price']: trade['highest_price'] = cp
                
                profit_pct = (cp - trade['entry_price']) / trade['entry_price']
                
                # تفعيل الملاحقة
                if profit_pct >= TRAILING_TRIGGER: trade['trailing_active'] = True
                
                # شرط الخروج بربح (Trailing Stop)
                if trade['trailing_active'] and (trade['highest_price'] - cp) / trade['highest_price'] >= TRAILING_CALLBACK:
                    pnl = (trade['coins'] * cp) - trade['amount_usd']
                    VIRTUAL_BALANCE += (trade['amount_usd'] + pnl)
                    closed_trades_history.append({"pnl": pnl})
                    portfolio["open_trades"].pop(sym)
                    send_telegram_msg(f"💰 **جني أرباح:** `{sym}` | +${pnl:.2f}\n💵 الرصيد الحالي: `${VIRTUAL_BALANCE:.2f}`")
                
                # شرط وقف الخسارة (4%)
                elif profit_pct <= -0.04:
                    pnl = (trade['coins'] * cp) - trade['amount_usd']
                    VIRTUAL_BALANCE += (trade['amount_usd'] + pnl)
                    portfolio["open_trades"].pop(sym)
                    send_telegram_msg(f"🛑 **وقف خسارة:** `{sym}` | ${pnl:.2f}")
            
            await asyncio.sleep(10)
        except Exception as e: 
            print(f"Manage Error: {e}")
            await asyncio.sleep(5)

# ======================== 4. نظام التحكم والأوامر ========================

def send_telegram_msg(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

def handle_telegram_commands():
    global VIRTUAL_BALANCE
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=30"
            res = requests.get(url).json()
            if "result" in res:
                for update in res["result"]:
                    last_update_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"].lower().strip()
                        if str(update["message"]["chat_id"]) != TELEGRAM_CHAT_ID: continue
                        
                        if text == "/start":
                            send_telegram_msg("👋 **أهلاً بك!** البوت يعمل بماسح 500 عملة ورصيد 1000$.\nالأوامر: /status, /report, /panic")
                        elif text == "/status":
                            pnl = sum([t['pnl'] for t in closed_trades_history])
                            send_telegram_msg(f"📊 **الحالة:**\n• الرصيد: `${VIRTUAL_BALANCE:.2f}`\n• الأرباح: `${pnl:.2f}`\n• صفقات مفتوحة: `{len(portfolio['open_trades'])}`")
                        elif text == "/report":
                            if not portfolio["open_trades"]: send_telegram_msg("📭 لا توجد صفقات.")
                            else:
                                report = "📑 **الصفقات المفتوحة:**\n"
                                for sym, data in portfolio["open_trades"].items():
                                    report += f"• `{sym}`: @ {data['entry_price']:.5f}\n"
                                send_telegram_msg(report)
                        elif text == "/panic":
                            for s in list(portfolio["open_trades"].keys()):
                                VIRTUAL_BALANCE += portfolio["open_trades"][s]['amount_usd']
                                portfolio["open_trades"].pop(s)
                            send_telegram_msg("🚨 تم إغلاق كل الصفقات واستعادة الرصيد.")
                        elif text.startswith("/close "):
                            sym = text.split(" ")[1].upper()
                            if not sym.endswith("/USDT"): sym += "/USDT"
                            if sym in portfolio["open_trades"]:
                                VIRTUAL_BALANCE += portfolio["open_trades"][sym]['amount_usd']
                                portfolio["open_trades"].pop(sym)
                                send_telegram_msg(f"✅ تم إغلاق `{sym}`.")
        except: pass
        time.sleep(1)

# ======================== 5. تشغيل السيرفر الإنتاجي ========================

app = Flask('')
@app.route('/')
def home(): return "Bot Final Version - Online"

async def main_loop():
    send_telegram_msg("🚀 **تم تشغيل النسخة النهائية!**\nالرصيد: 1000$ | المسح: 500 عملة.")
    asyncio.create_task(manage_trades())
    while True:
        await scan_market()
        await asyncio.sleep(20)

if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", 8080))
    # تشغيل مستمع الأوامر
    threading.Thread(target=handle_telegram_commands, daemon=True).start()
    # تشغيل محرك التداول
    threading.Thread(target=lambda: asyncio.run(main_loop()), daemon=True).start()
    # تشغيل سيرفر الويب (الواجهة)
    serve(app, host='0.0.0.0', port=port)
