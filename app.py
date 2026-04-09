import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. إعدادات السيرفر (حل مشكلة Render) ========================
app = Flask('')

@app.route('/')
def home():
    return "🚀 Bot is Running and Healthy!"

def run_flask():
    # Render يمرر البوت عبر متغير البيئة PORT تلقائياً
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ======================== 2. الإعدادات والمعرفات ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# إعدادات الاستراتيجية
VIRTUAL_BALANCE = 1000.0
portfolio = {"open_trades": {}}
closed_trades_log = []
MIN_VOLUME_24H = 5000000 # 5 مليون دولار

# ======================== 3. أدوات التحليل والمؤشرات ========================

async def is_market_safe():
    """فلتر البيتكوين: هل السوق يسمح بالـ Short؟"""
    try:
        btc = await EXCHANGE.fetch_ticker('BTC/USDT')
        return (btc['percentage'] or 0) < 1.5 # لا ندخل لو البيتكوين صاعد بقوة
    except: return True

def get_targets(df):
    """حساب الأهداف بناءً على فيبوناتشي ووقف الخسارة"""
    peak = df['high'].max()
    low = df['low'].min()
    entry = df.iloc[-1]['close']
    
    target = peak - (peak - low) * 0.5 # هدف 50% فيبوناتشي
    stop_loss = peak * 1.015 # وقف 1.5% فوق القمة
    
    expected_profit = ((entry - target) / entry) * 100
    return target, stop_loss, expected_profit

def detect_reversal(df):
    """اكتشاف شمعة الشهاب مع تأكيد الإغلاق والحجم"""
    prev = df.iloc[-2] # شمعة الإشارة
    last = df.iloc[-1] # شمعة التأكيد
    
    body = abs(prev['close'] - prev['open'])
    upper_wick = prev['high'] - max(prev['open'], prev['close'])
    avg_vol = df['vol'].rolling(10).mean().iloc[-2]
    
    # الشروط: ذيل طويل + إغلاق تحت القاع السابق + حجم عالي
    if upper_wick > (1.8 * body) and last['close'] < prev['low'] and prev['vol'] > avg_vol:
        return True
    return False

# ======================== 4. منطق المسح وإدارة الصفقات ========================

async def scan_market():
    if not await is_market_safe(): return
    
    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s 
                   and (tickers[s]['percentage'] or 0) > 10 
                   and (tickers[s]['quoteVolume'] or 0) > MIN_VOLUME_24H]
        
        for sym in symbols:
            if sym in portfolio["open_trades"]: continue
            
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=40)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            
            if detect_reversal(df):
                tp, sl, profit_pct = get_targets(df)
                
                # فلتر الـ 5% المطلوب
                if profit_pct >= 5.0:
                    entry_p = df.iloc[-1]['close']
                    portfolio["open_trades"][sym] = {
                        "entry_price": entry_p,
                        "target": tp,
                        "stop_loss": sl,
                        "entry_time": datetime.now()
                    }
                    send_telegram_msg(f"🛡️ *إشارة دخول مؤكدة*\n🎫 {sym}\n💰 السعر: {entry_p:.6f}\n🎯 الهدف: {tp:.6f}\n📈 ربح متوقع: {profit_pct:.2f}%")
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
                
                reason = None
                if cp <= trade['target']: reason = "🎯 Target Hit"
                elif cp >= trade['stop_loss']: reason = "🛑 Stop Loss Hit"
                elif duration > timedelta(hours=4): reason = "⏰ Time Exit (4h)"
                
                if reason:
                    VIRTUAL_BALANCE += 100 * (1 + (pnl/100))
                    closed_trades_log.append(pnl)
                    icon = "✅" if pnl > 0 else "❌"
                    send_telegram_msg(f"🏁 *إغلاق صفقة*\n🎫 {sym}\n📊 النتيجة: {icon} {pnl:+.2f}%\n📝 السبب: {reason}\n💰 الرصيد: ${VIRTUAL_BALANCE:.2f}")
                    del portfolio["open_trades"][sym]
            except: continue
        await asyncio.sleep(30)

async def hourly_report():
    while True:
        await asyncio.sleep(3600)
        report = (f"📊 *تقرير الأداء الساعي*\n---------------------------\n"
                  f"💰 الرصيد: ${VIRTUAL_BALANCE:.2f}\n"
                  f"📦 صفقات مفتوحة: {len(portfolio['open_trades'])}\n"
                  f"✅ صفقات مغلقة: {len(closed_trades_log)}")
        send_telegram_msg(report)

# ======================== 5. الوظائف العامة والتشغيل ========================

def send_telegram_msg(msg):
    for chat_id in DESTINATIONS:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}, timeout=5)
        except: pass

async def main_loop():
    send_telegram_msg("🚀 *النظام يعمل الآن بنجاح على Render!*")
    while True:
        await scan_market()
        await asyncio.sleep(60)

if __name__ == "__main__":
    # تشغيل Flask كخلفية لفتح البورت
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # تشغيل مهام البوت
    loop = asyncio.get_event_loop()
    loop.create_task(manage_trades())
    loop.create_task(hourly_report())
    loop.run_until_complete(main_loop())
