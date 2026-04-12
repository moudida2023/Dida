import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
from flask import Flask
from waitress import serve

# ======================== الإعدادات ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 5000.0
MAX_OPEN_TRADES = 50
TRADE_AMOUNT_USD = 20.0
ENTRY_SCORE_THRESHOLD = 110 # تقليل السكور لضمان الدخول السريع في البداية للتجربة

portfolio = {"open_trades": {}}
stats = {"win": 0, "loss": 0}

# ======================== دالة الإرسال مع فحص الأخطاء ========================
def send_telegram_msg(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"Telegram Error: {response.text}")
        return response
    except Exception as e:
        print(f"Connection Error: {e}")

# ======================== وظائف التحليل (مبسطة للسرعة) ========================
async def calculate_score(symbol):
    try:
        bars = await EXCHANGE.fetch_ohlcv(symbol, timeframe='15m', limit=50)
        df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
        # منطق سكور سريع للتجربة
        last_close = df['close'].iloc[-1]
        ema200 = df['close'].ewm(span=200).mean().iloc[-1]
        
        score = 0
        if last_close > ema200: score += 60
        if df['vol'].iloc[-1] > df['vol'].mean(): score += 50
        
        return score, last_close
    except: return 0, 0

async def try_entry(symbol):
    global VIRTUAL_BALANCE
    if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES: return
    score, price = await calculate_score(symbol)
    if score >= ENTRY_SCORE_THRESHOLD:
        portfolio["open_trades"][symbol] = {"price": price}
        VIRTUAL_BALANCE -= TRADE_AMOUNT_USD
        send_telegram_msg(f"🚀 تم الدخول في: {symbol}\n📊 السكور: {score}")

async def scanner():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s][:100] # فحص أول 100 عملة للسرعة
            tasks = [try_entry(s) for s in symbols if s not in portfolio["open_trades"]]
            await asyncio.gather(*tasks)
            await asyncio.sleep(30)
        except: await asyncio.sleep(10)

# ======================== التشغيل والسيرفر ========================
app = Flask('')
@app.route('/')
def home(): return "Bot is Running"

async def main():
    # 📢 رسالة نبض القلب - ستصلك فوراً عند نجاح الرفع على Railway
    print("Sending Startup Message...")
    test_res = send_telegram_msg("✅ **Snowball Sniper V23**\nتم التشغيل بنجاح على Railway!\nجاري بدء مسح السوق...")
    
    if test_res and test_res.status_code == 200:
        print("Telegram Link Verified!")
    else:
        print("Telegram Link FAILED. Check Token/ChatID.")

    asyncio.create_task(scanner())
    while True: await asyncio.sleep(1)

if __name__ == "__main__":
    # تشغيل Flask في خيط منفصل لـ Railway Health Check
    threading.Thread(target=lambda: serve(app, host='0.0.0.0', port=10000), daemon=True).start()
    asyncio.run(main())
