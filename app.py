import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import os
import time
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات المتقدمة ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0
BASE_TRADE_USD = 100.0      # مبلغ الدخول الأول
DCA_TRADE_USD = 50.0       # مبلغ التعزيز (DCA)
PROFIT_TARGET_USD = 1.5     # الهدف الصافي بالدولار لكل صفقة
DCA_THRESHOLD = -0.05       # تعزيز عند هبوط 5%

portfolio = {"open_trades": {}}
closed_trades_history = []
emergency_stop = False      # مفتاح الطوارئ

# ======================== 2. وحدة الأوامر المطورة ========================

def telegram_command_listener():
    global emergency_stop
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
                                send_telegram_msg("🚀 *نظام Snowball v13.0 PRO*\nالوضع: نشط\nنظام التعزيز (DCA): مفعل")
                            elif text == "/panic":
                                emergency_stop = True
                                send_telegram_msg("⚠️ *تم تفعيل وضع الطوارئ!* لن يتم فتح صفقات جديدة.")
                            elif text == "/resume":
                                emergency_stop = False
                                send_telegram_msg("✅ *تم استئناف العمل بنجاح.*")
                            elif text in ["/report", "تقرير"]:
                                send_telegram_msg(generate_report_text())
        except: time.sleep(5)
        time.sleep(1)

def generate_report_text():
    total_pnl = sum(t['pnl'] for t in closed_trades_history)
    return (f"📊 *تقرير الأداء:*\n"
            f"💰 الرصيد: `${VIRTUAL_BALANCE:.2f}`\n"
            f"✅ صفقات منتهية: {len(closed_trades_history)}\n"
            f"📈 أرباح: `${total_pnl:.2f}`\n"
            f"📂 صفقات معلقة: {len(portfolio['open_trades'])}")

# ======================== 3. منطق الفحص مع فلتر الاتجاه ========================

async def scan_market():
    global VIRTUAL_BALANCE, emergency_stop
    if emergency_stop or len(portfolio["open_trades"]) >= 10 or VIRTUAL_BALANCE < BASE_TRADE_USD: return

    BLACKLIST = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'USDC/USDT', 'FDUSD/USDT']

    try:
        # فحص حالة البيتكوين كفلتر للسوق
        btc_ticker = await EXCHANGE.fetch_ticker('BTC/USDT')
        if btc_ticker['percentage'] < -3.0: # إذا البيتكوين يهبط بقوة، نتوقف
            return

        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s and s not in BLACKLIST and tickers[s]['quoteVolume'] > 1500000]
        top_symbols = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:40]
        
        for sym in top_symbols:
            if sym in portfolio["open_trades"]: continue
            
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=50)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            
            # حساب سكور 5/5
            ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[-1]
            last = df.iloc[-1]
            
            score = 0
            if last['close'] > ema9: score += 1
            if last['close'] > last['open']: score += 1
            if last['vol'] > df['vol'].tail(10).mean(): score += 1
            if last['close'] > df.iloc[-2]['high']: score += 1
            if last['close'] > df['close'].shift(1).iloc[-1]: score += 1

            if score == 5:
                # شراء أولي
                entry_price = last['close']
                portfolio["open_trades"][sym] = {
                    "entry_price": entry_price,
                    "avg_price": entry_price,
                    "coins": BASE_TRADE_USD / entry_price,
                    "amount_usd": BASE_TRADE_USD,
                    "dca_count": 0
                }
                VIRTUAL_BALANCE -= BASE_TRADE_USD
                send_telegram_msg(f"🚀 *دخول ذكي*\n🎫 {sym}\n💵 السعر: {entry_price:.6f}")
                break 
    except: pass

# ======================== 4. إدارة الصفقات + نظام التعزيز DCA ========================

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                
                # حساب الربح بناءً على متوسط السعر
                profit_usd = (trade['coins'] * cp) - trade['amount_usd']
                profit_pct = (cp - trade['avg_price']) / trade['avg_price']
                
                # 1. الخروج عند الربح
                if profit_usd >= PROFIT_TARGET_USD:
                    VIRTUAL_BALANCE += (trade['amount_usd'] + profit_usd)
                    closed_trades_history.append({"pnl": profit_usd})
                    portfolio["open_trades"].pop(sym)
                    send_telegram_msg(f"🎯 *هدف محقق (+1.5$)*\n🎫 {sym}\n💰 الربح الكلي: {profit_usd:.2f}")

                # 2. نظام التعزيز (DCA) عند الهبوط
                elif profit_pct <= DCA_THRESHOLD and trade['dca_count'] < 1: # تعزيز لمرة واحدة
                    if VIRTUAL_BALANCE >= DCA_TRADE_USD:
                        new_coins = DCA_TRADE_USD / cp
                        trade['coins'] += new_coins
                        trade['amount_usd'] += DCA_TRADE_USD
                        trade['avg_price'] = trade['amount_usd'] / trade['coins'] # تحديث متوسط السعر
                        trade['dca_count'] += 1
                        VIRTUAL_BALANCE -= DCA_TRADE_USD
                        send_telegram_msg(f"🛠 *تعزيز (DCA)*\n🎫 {sym}\n📉 السعر الجديد: {trade['avg_price']:.6f}")

            await asyncio.sleep(15)
        except: await asyncio.sleep(5)

# ======================== 5. تشغيل النظام ========================

def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

app = Flask('')
@app.route('/')
def home(): return f"Snowball PRO v13.0 - Balance: {VIRTUAL_BALANCE:.2f}"

async def main_loop():
    send_telegram_msg("✅ *البوت المطور v13.0 يعمل الآن بنظام DCA وفلترة BTC*")
    asyncio.create_task(manage_trades())
    threading.Thread(target=telegram_command_listener, daemon=True).start()
    while True:
        await scan_market()
        await asyncio.sleep(45)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_loop())
