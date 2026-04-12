import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import os
import time
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. الإعدادات الأساسية ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0
TRADE_SIZE_USD = 100.0      # حجم الصفقة ثابت
PROFIT_TARGET_USD = 1.5     # هدف الربح بالدولار

portfolio = {"open_trades": {}}
trade_history = {}
closed_trades_history = []
current_market_mode = "NORMAL"

# ======================== 2. وحدة استقبال الأوامر التفاعلية ========================

def telegram_command_listener():
    """الاستماع للأوامر والرد الفوري"""
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
                                    "🚀 *نظام Snowball v12.0 جاهز!*\n\n"
                                    "✅ سكور صارم: 5/5\n"
                                    "✅ مبلغ الدخول: $100\n"
                                    "✅ الهدف: +$1.5\n"
                                    "🚫 مستبعد: العملات الكبيرة والمستقرة\n\n"
                                    "أرسل /report لمتابعة النتائج."
                                )
                                send_telegram_msg(msg)
                            
                            elif text in ["/report", "تقرير"]:
                                report = generate_report_text()
                                send_telegram_msg(f"📊 *تقرير الأداء:*\n{report}")
                            
                            elif text == "/status":
                                status = f"🌐 الحالة: متصل\n🤖 الوضع: {current_market_mode}\n📂 صفقات: {len(portfolio['open_trades'])}"
                                send_telegram_msg(status)
        except:
            time.sleep(5)
        time.sleep(1)

def generate_report_text():
    total_pnl = sum(t['pnl'] for t in closed_trades_history)
    wins = len(closed_trades_history)
    msg = (
        f"💰 الرصيد الحالي: `${VIRTUAL_BALANCE:.2f}`\n"
        f"✅ صفقات مغلقة: {wins}\n"
        f"📈 إجمالي الأرباح: `${total_pnl:.2f}`\n"
        f"📂 صفقات مفتوحة حالياً: {len(portfolio['open_trades'])}"
    )
    return msg

# ======================== 3. منطق تحليل السوق والسكور ========================

async def scan_market():
    global VIRTUAL_BALANCE, current_market_mode
    
    # استبعاد العملات المستقرة والكبيرة
    BLACKLIST = [
        'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'USDC/USDT', 
        'FDUSD/USDT', 'TUSD/USDT', 'DAI/USDT', 'USDP/USDT'
    ]

    if len(portfolio["open_trades"]) >= 10 or VIRTUAL_BALANCE < TRADE_SIZE_USD: return

    try:
        tickers = await EXCHANGE.fetch_tickers()
        # تصفية العملات بناءً على السيولة والقائمة السوداء
        symbols = [s for s in tickers.keys() if '/USDT' in s and s not in BLACKLIST and tickers[s]['quoteVolume'] > 1200000]
        top_symbols = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:100]
        
        for sym in top_symbols:
            if sym in portfolio["open_trades"]: continue
            
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=50)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            
            # حساب المؤشرات
            ema9 = df['close'].ewm(span=9, adjust=False).mean()
            rsi = calculate_rsi(df)
            last = df.iloc[-1]
            prev = df.iloc[-2]

            # --- نظام سكور 5/5 الصارم ---
            score = 0
            if last['close'] > ema9.iloc[-1]: score += 1      # 1. فوق المتوسط
            if last['close'] > last['open']: score += 1      # 2. شمعة خضراء
            if last['vol'] > df['vol'].tail(10).mean(): score += 1 # 3. حجم تداول متزايد
            if last['close'] > prev['high']: score += 1     # 4. اختراق القمة السابقة
            if rsi.iloc[-1] > 50: score += 1                # 5. القوة النسبية إيجابية

            if score == 5:
                entry_price = last['close']
                portfolio["open_trades"][sym] = {
                    "entry_price": entry_price,
                    "coins": TRADE_SIZE_USD / entry_price,
                    "amount_usd": TRADE_SIZE_USD,
                    "time": datetime.now()
                }
                VIRTUAL_BALANCE -= TRADE_SIZE_USD
                send_telegram_msg(f"🚀 *دخول صفقة (5/5)*\n🎫 {sym}\n💵 السعر: {entry_price:.6f}\n💰 القيمة: $100")
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
                
                profit_usd = (trade['coins'] * cp) - trade['amount_usd']
                
                # إغلاق فقط عند تحقيق 1.5 دولار ربح (بدون وقف خسارة)
                if profit_usd >= PROFIT_TARGET_USD:
                    VIRTUAL_BALANCE += (trade['amount_usd'] + profit_usd)
                    closed_trades_history.append({"sym": sym, "pnl": profit_usd})
                    portfolio["open_trades"].pop(sym)
                    send_telegram_msg(f"🎯 *تم تحقيق الهدف (+1.5$)*\n🎫 {sym}\n💰 الربح: ${profit_usd:.2f}\n💵 الرصيد: ${VIRTUAL_BALANCE:.2f}")
            
            await asyncio.sleep(15)
        except: await asyncio.sleep(5)

# ======================== 4. الدوال المساعدة والتشغيل ========================

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

app = Flask('')
@app.route('/')
def home(): return f"Snowball PRO v12.0 - Balance: {VIRTUAL_BALANCE:.2f} USDT"

async def main_loop():
    send_telegram_msg("✅ *تم تشغيل النسخة النهائية v12.0 بنجاح*")
    asyncio.create_task(manage_trades())
    threading.Thread(target=telegram_command_listener, daemon=True).start()
    while True:
        await scan_market()
        await asyncio.sleep(60)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_loop())
