import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. إعدادات السيرفر (Render Fix) ========================
app = Flask('')

@app.route('/')
def home():
    return "Bot is running and healthy! 🚀"

def run_flask():
    # Render يطلب ربط الخدمة ببورت معين، نقوم بجلب البورت من إعدادات البيئة
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ======================== 2. الإعدادات العامة ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0
portfolio = {"open_trades": {}}
closed_trades_log = []

# ======================== 3. منطق التداول المطور ========================

def calculate_exit_points(df):
    recent_peak = df['high'].max()
    recent_low = df['low'].min()
    entry_price = df.iloc[-1]['close']
    
    target_price = recent_peak - (recent_peak - recent_low) * 0.5 # فيبوناتشي 50%
    stop_loss = recent_peak * 1.015 # وقف 1.5% فوق القمة
    
    expected_drop_pct = ((entry_price - target_price) / entry_price) * 100
    return target_price, stop_loss, expected_drop_pct

async def scan_market():
    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s 
                   and (tickers[s]['percentage'] or 0) > 10 
                   and (tickers[s]['quoteVolume'] or 0) > 5000000]
        
        for sym in symbols:
            if sym in portfolio["open_trades"]: continue
            
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=40)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            
            # شرط الانعكاس (تأكيد الشمعة والحجم)
            prev = df.iloc[-2]
            last = df.iloc[-1]
            body = abs(prev['close'] - prev['open'])
            upper_wick = prev['high'] - max(prev['open'], prev['close'])
            
            if upper_wick > (1.8 * body) and last['close'] < prev['low']:
                tp, sl, drop_pct = calculate_exit_points(df)
                
                # الفلتر المطلوب: الحد الأدنى للربح 5%
                if drop_pct >= 5.0:
                    entry_p = last['close']
                    portfolio["open_trades"][sym] = {
                        "entry_price": entry_p,
                        "target": tp,
                        "stop_loss": sl,
                        "entry_time": datetime.now()
                    }
                    send_telegram_msg(f"🚀 *دخول مؤكد (Short)*\n🎫 {sym}\n📉 نزول متوقع: {drop_pct:.2f}%\n💰 سعر: {entry_p:.6f}")
    except Exception as e:
        print(f"Scan Error: {e}")

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        for sym in list(portfolio["open_trades"].keys()):
            try:
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                pnl = (trade['entry_price'] - cp) / trade['entry_price'] * 100
                duration = datetime.now() - trade['entry_time']

                if cp <= trade['target'] or cp >= trade['stop_loss'] or duration > timedelta(hours=4):
                    res = "✅" if pnl > 0 else "❌"
                    VIRTUAL_BALANCE += 100 * (1 + (pnl/100))
                    send_telegram_msg(f"🏁 *إغلاق صفقة*\n🎫 {sym}\n📊 النتيجة: {res} ({pnl:+.2f}%)\n💰 الرصيد: ${VIRTUAL_BALANCE:.2f}")
                    del portfolio["open_trades"][sym]
            except: continue
        await asyncio.sleep(30)

# ======================== 4. الوظائف المساعدة والتشغيل ========================

def send_telegram_msg(msg):
    for chat_id in DESTINATIONS:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}, timeout=5)
        except: pass

async def main_loop():
    send_telegram_msg("🏗️ *البوت يعمل الآن على Render*\nتم حل مشكلة الـ Port Binding بنجاح.")
    while True:
        await scan_market()
        await asyncio.sleep(60)

if __name__ == "__main__":
    # تشغيل Flask في خيط منفصل (Thread) لإرضاء سيرفر Render
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # تشغيل محرك البوت الأساسي
    loop = asyncio.get_event_loop()
    loop.create_task(manage_trades())
    loop.run_until_complete(main_loop())
