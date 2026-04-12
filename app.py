import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
from flask import Flask

# ======================== 1. الإعدادات والتحكم ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0
BASE_TRADE_USD = 100.0
TRAILING_TRIGGER = 0.02
TRAILING_CALLBACK = 0.005

portfolio = {"open_trades": {}}
closed_trades_history = []

# ======================== 2. نظام أوامر تليجرام (Commands) ========================

def handle_telegram_commands():
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=30"
            response = requests.get(url).json()
            
            if "result" in response:
                for update in response["result"]:
                    last_update_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"].lower()
                        chat_id = str(update["message"]["chat_id"])
                        
                        if chat_id != TELEGRAM_CHAT_ID: continue

                        # 1. أمر التقرير /report
                        if text == "/report":
                            if not portfolio["open_trades"]:
                                send_telegram_msg("📭 لا توجد صفقات مفتوحة حالياً.")
                            else:
                                report = "📑 **تقرير الصفقات المفتوحة:**\n"
                                for sym, data in portfolio["open_trades"].items():
                                    report += f"• `{sym}`: دخول {data['entry_price']:.4f}\n"
                                send_telegram_msg(report)

                        # 2. أمر الحالة /status
                        elif text == "/status":
                            total_pnl = sum([t['pnl'] for t in closed_trades_history])
                            status = (f"💰 **حالة المحفظة:**\n"
                                      f"• الرصيد الحالي: ${VIRTUAL_BALANCE:.2f}\n"
                                      f"• إجمالي الأرباح المحققة: ${total_pnl:.2f}\n"
                                      f"• صفقات مفتوحة: {len(portfolio['open_trades'])}")
                            send_telegram_msg(status)

                        # 3. أمر الطوارئ /panic
                        elif text == "/panic":
                            global VIRTUAL_BALANCE
                            for sym in list(portfolio["open_trades"].keys()):
                                trade = portfolio["open_trades"][sym]
                                # في الحقيقي سننفذ أمر بيع ماركت، هنا سنغلق افتراضياً
                                VIRTUAL_BALANCE += trade['amount_usd'] 
                                portfolio["open_trades"].pop(sym)
                            send_telegram_msg("⚠️ **PANIC:** تم إغلاق جميع الصفقات فوراً!")

                        # 4. أمر إغلاق عملة معينة /close SYMBOL
                        elif text.startswith("/close "):
                            sym_to_close = text.split(" ")[1].upper()
                            if not sym_to_close.endswith("/USDT"): sym_to_close += "/USDT"
                            
                            if sym_to_close in portfolio["open_trades"]:
                                trade = portfolio["open_trades"][sym_to_close]
                                VIRTUAL_BALANCE += trade['amount_usd']
                                portfolio["open_trades"].pop(sym_to_close)
                                send_telegram_msg(f"✅ تم إغلاق `{sym_to_close}` يدوياً.")
                            else:
                                send_telegram_msg(f"❌ العملة `{sym_to_close}` غير موجودة في الصفقات.")

        except Exception as e:
            print(f"Telegram Command Error: {e}")
        time.sleep(2)

# ======================== 3. محرك التحليل والإدارة (الكود السابق) ========================

def get_indicators(df):
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    basis = df['close'].rolling(window=20).mean()
    std = df['close'].rolling(window=20).std()
    df['bandwidth'] = ((basis + (std * 2)) - (basis - (std * 2))) / basis
    tp = (df['high'] + df['low'] + df['close']) / 3
    mf = tp * df['vol']
    pos = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    df['mfi'] = 100 - (100 / (1 + (pos / neg)))
    return df

async def scan_market():
    global VIRTUAL_BALANCE
    if len(portfolio["open_trades"]) >= 10: return
    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s and tickers[s]['quoteVolume'] > 2000000]
        for sym in sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:30]:
            if sym in portfolio["open_trades"]: continue
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=50)
            df = get_indicators(pd.DataFrame(bars, columns=['ts','open','high','low','close','vol']))
            last, prev = df.iloc[-1], df.iloc[-2]
            
            # سكور 8/8 مبسط للسرعة
            if last['close'] > last['ema9'] and last['mfi'] > 60 and last['vol'] > df['vol'].tail(10).mean() * 1.5:
                entry_price = last['close']
                portfolio["open_trades"][sym] = {
                    "entry_price": entry_price, "highest_price": entry_price,
                    "coins": BASE_TRADE_USD / entry_price, "amount_usd": BASE_TRADE_USD, "trailing_active": False
                }
                VIRTUAL_BALANCE -= BASE_TRADE_USD
                send_telegram_msg(f"🚀 دخول: `{sym}` @ {entry_price:.6f}")
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
                if cp > trade['highest_price']: portfolio["open_trades"][sym]['highest_price'] = cp
                profit_pct = (cp - trade['entry_price']) / trade['entry_price']
                
                if profit_pct >= TRAILING_TRIGGER: trade['trailing_active'] = True
                
                if trade['trailing_active']:
                    if (trade['highest_price'] - cp) / trade['highest_price'] >= TRAILING_CALLBACK:
                        pnl = (trade['coins'] * cp) - trade['amount_usd']
                        VIRTUAL_BALANCE += (trade['amount_usd'] + pnl)
                        closed_trades_history.append({"pnl": pnl})
                        portfolio["open_trades"].pop(sym)
                        send_telegram_msg(f"💰 ربح: `{sym}` | ${pnl:.2f}")
                elif profit_pct <= -0.03:
                    VIRTUAL_BALANCE += (trade['coins'] * cp)
                    portfolio["open_trades"].pop(sym)
                    send_telegram_msg(f"🛑 وقف خسارة: `{sym}`")
            await asyncio.sleep(10)
        except: await asyncio.sleep(5)

# ======================== 4. التشغيل النهائي ========================

def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

app = Flask('')
@app.route('/')
def home(): return f"Active - Trades: {len(portfolio['open_trades'])}"

async def main_loop():
    asyncio.create_task(manage_trades())
    while True:
        await scan_market()
        await asyncio.sleep(30)

if __name__ == "__main__":
    # تشغيل مستمع الأوامر في Thread منفصل
    threading.Thread(target=handle_telegram_commands, daemon=True).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    asyncio.run(main_loop())
    
