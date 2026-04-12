import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import os
import time
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات الأساسية ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0
TRADE_SIZE_USD = 100.0      # دخول ثابت بـ 100 دولار
PROFIT_TARGET_USD = 1.5     # هدف الربح (بدون وقف خسارة)

portfolio = {"open_trades": {}}
closed_trades_history = []

# ======================== 2. وحدة الأوامر التفاعلية ========================

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
                                send_telegram_msg("🚀 *نظام Fast-Entry v12.7*\nوضع المسح: دخول فوري عند الاكتشاف 5/5.")
                            elif text in ["/report", "تقرير"]:
                                report = f"💰 الأرباح: `${sum(t['pnl'] for t in closed_trades_history):.2f}`\n📂 صفقات: {len(portfolio['open_trades'])}"
                                send_telegram_msg(report)
        except: time.sleep(5)
        time.sleep(1)

# ======================== 3. المسح والدخول المباشر المسرّع ========================

async def scan_market():
    global VIRTUAL_BALANCE
    
    # استبعاد العملات المستقرة والكبيرة جداً
    BLACKLIST = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'USDC/USDT', 'FDUSD/USDT', 'DAI/USDT']

    # التأكد من وجود رصيد وعدم تجاوز 10 صفقات مفتوحة
    if len(portfolio["open_trades"]) >= 10 or VIRTUAL_BALANCE < TRADE_SIZE_USD: return

    try:
        tickers = await EXCHANGE.fetch_tickers()
        # تصفية العملات المناسبة للتذبذب
        symbols = [s for s in tickers.keys() if '/USDT' in s and s not in BLACKLIST and tickers[s]['quoteVolume'] > 1200000]
        top_symbols = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:40]
        
        for sym in top_symbols:
            # التحقق من أن العملة ليست مفتوحة حالياً
            if sym in portfolio["open_trades"]: continue
            
            # جلب البيانات وبدء التحليل فوراً
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=50)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            
            last = df.iloc[-1]
            prev = df.iloc[-2]
            ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[-1]
            
            # نظام السكور 5/5 الصارم
            score = 0
            if last['close'] > ema9: score += 1               # 1. السعر فوق المتوسط
            if last['close'] > last['open']: score += 1       # 2. شمعة خضراء
            if last['vol'] > df['vol'].tail(10).mean(): score += 1 # 3. فوليوم عالي
            if last['close'] > prev['high']: score += 1      # 4. اختراق القمة السابقة
            if last['close'] > df['close'].shift(1).iloc[-1]: score += 1 # 5. زخم سعري صاعد

            # الدخول المباشر عند الاكتشاف
            if score == 5:
                entry_price = last['close']
                # إضافة الصفقة للمحفظة فوراً
                portfolio["open_trades"][sym] = {
                    "entry_price": entry_price,
                    "coins": TRADE_SIZE_USD / entry_price,
                    "amount_usd": TRADE_SIZE_USD,
                    "time": datetime.now()
                }
                VIRTUAL_BALANCE -= TRADE_SIZE_USD
                
                # إرسال إشعار فوري
                send_telegram_msg(f"⚡ *دخول فوري (اكتشاف 5/5)*\n🎫 {sym}\n💵 السعر: {entry_price:.6f}")
                
                # الاستمرار في المسح أو التوقف مؤقتاً لضمان عدم استهلاك الرصيد دفعة واحدة
                if len(portfolio["open_trades"]) >= 10 or VIRTUAL_BALANCE < TRADE_SIZE_USD:
                    break
    except: pass

# ======================== 4. إدارة الصفقات (البيع عند الربح فقط) ========================

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                profit_usd = (trade['coins'] * cp) - trade['amount_usd']
                
                # الإغلاق فقط عند تحقيق الهدف 1.5$ (No SL)
                if profit_usd >= PROFIT_TARGET_USD:
                    VIRTUAL_BALANCE += (trade['amount_usd'] + profit_usd)
                    closed_trades_history.append({"pnl": profit_usd})
                    portfolio["open_trades"].pop(sym)
                    send_telegram_msg(f"🎯 *تم ضرب الهدف (+1.5$)*\n🎫 {sym}\n💰 الرصيد: ${VIRTUAL_BALANCE:.2f}")
            
            await asyncio.sleep(10) # فحص الأسعار كل 10 ثوانٍ لسرعة الخروج
        except: await asyncio.sleep(5)

# ======================== 5. تشغيل النظام ========================

def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

app = Flask('')
@app.route('/')
def home(): return f"Snowball Fast-Entry v12.7 - Balance: {VIRTUAL_BALANCE:.2f}"

async def main_loop():
    send_telegram_msg("✅ *نظام الدخول المباشر نشط الآن*")
    asyncio.create_task(manage_trades())
    threading.Thread(target=telegram_command_listener, daemon=True).start()
    while True:
        await scan_market()
        await asyncio.sleep(30) # فحص السوق كل 30 ثانية بحثاً عن فرص جديدة

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_loop())
