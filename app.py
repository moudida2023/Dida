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
    return "🚀 Snowball Bot is Active | Balance: $500 | Max 5 Trades"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ======================== 2. الإعدادات والمعرفات ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# إعدادات المحفظة
VIRTUAL_BALANCE = 500.0
START_DAY_BALANCE = 500.0
TRADE_AMOUNT = 50.0      
MAX_OPEN_TRADES = 5      
portfolio = {"open_trades": {}}
closed_trades_history = []
MIN_VOLUME_24H = 5000000 

# ======================== 3. منطق التحليل والمؤشرات ========================

async def is_market_safe():
    """فلتر البيتكوين لمنع البيع في سوق صاعد بقوة"""
    try:
        btc = await EXCHANGE.fetch_ticker('BTC/USDT')
        return (btc['percentage'] or 0) < 1.5 
    except: return True

def get_targets(df):
    """حساب مستويات الخروج بناءً على فيبوناتشي 50%"""
    peak = df['high'].max()
    low = df['low'].min()
    entry = df.iloc[-1]['close']
    target = peak - (peak - low) * 0.5 
    stop_loss = peak * 1.015 
    expected_profit = ((entry - target) / entry) * 100
    return target, stop_loss, expected_profit

def detect_reversal(df):
    """اكتشاف شمعة الشهاب مع تأكيد الإغلاق والحجم"""
    prev = df.iloc[-2] 
    last = df.iloc[-1] 
    body = abs(prev['close'] - prev['open'])
    upper_wick = prev['high'] - max(prev['open'], prev['close'])
    avg_vol = df['vol'].rolling(10).mean().iloc[-2]
    
    if upper_wick > (1.8 * body) and last['close'] < prev['low'] and prev['vol'] > avg_vol:
        return True
    return False

# ======================== 4. إدارة العمليات والصفقات ========================

async def scan_market():
    global VIRTUAL_BALANCE
    if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES: return
    if not await is_market_safe(): return
    
    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s 
                   and (tickers[s]['percentage'] or 0) > 10 
                   and (tickers[s]['quoteVolume'] or 0) > MIN_VOLUME_24H]
        
        for sym in symbols:
            if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES: break
            if sym in portfolio["open_trades"]: continue
            if VIRTUAL_BALANCE < TRADE_AMOUNT: continue 

            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=40)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            
            if detect_reversal(df):
                tp, sl, profit_pct = get_targets(df)
                if profit_pct >= 5.0:
                    entry_p = df.iloc[-1]['close']
                    VIRTUAL_BALANCE -= TRADE_AMOUNT
                    portfolio["open_trades"][sym] = {
                        "entry_price": entry_p,
                        "target": tp,
                        "stop_loss": sl,
                        "trailing_sl": sl,
                        "amount": TRADE_AMOUNT,
                        "entry_time": datetime.now(),
                        "trailing_active": False
                    }
                    send_telegram_msg(f"🛡️ *دخول جديد (Short)*\n🎫 {sym}\n💰 السعر: {entry_p:.6f}\n🎯 الهدف: {tp:.6f}\n📦 الصفقات: {len(portfolio['open_trades'])}/5")
    except: pass

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        for sym in list(portfolio["open_trades"].keys()):
            try:
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                pnl_ratio = (trade['entry_price'] - cp) / trade['entry_price']
                pnl_pct = pnl_ratio * 100
                
                # تحديث التتبع السعري (Trailing)
                if pnl_pct >= 2.0: trade["trailing_active"] = True
                if trade["trailing_active"]:
                    new_sl = cp * 1.015
                    if new_sl < trade["trailing_sl"]: trade["trailing_sl"] = new_sl

                # منطق الخروج
                reason = None
                if cp <= trade['target']: reason = "🎯 الهدف الثابت"
                elif cp >= trade['trailing_sl']: reason = "🛡️ التتبع/الوقف"
                elif (datetime.now() - trade['entry_time']) > timedelta(hours=4): reason = "⏰ الوقت (4س)"
                
                if reason:
                    final_ret = trade['amount'] * (1 + pnl_ratio)
                    VIRTUAL_BALANCE += final_ret
                    closed_trades_history.append({"sym": sym, "pnl": pnl_pct, "time": datetime.now()})
                    icon = "✅" if pnl_pct > 0 else "❌"
                    send_telegram_msg(f"🏁 *إغلاق صفقة*\n🎫 {sym}\n📊 النتيجة: {icon} {pnl_pct:+.2f}%\n📝 السبب: {reason}\n💵 الرصيد: ${VIRTUAL_BALANCE:.2f}")
                    del portfolio["open_trades"][sym]
            except: continue
        await asyncio.sleep(15) # تحديث كل 15 ثانية بناءً على طلبك

# ======================== 5. نظام التقارير (ساعي ويومي) ========================

async def hourly_report():
    while True:
        await asyncio.sleep(3600)
        open_list = "".join([f"• {s}: {( (t['entry_price'] - (await EXCHANGE.fetch_ticker(s))['last']) / t['entry_price'] * 100):+.2f}%\n" for s, t in portfolio["open_trades"].items()])
        msg = f"📊 *تقرير الساعة*\n-------------------\n💵 الرصيد: ${VIRTUAL_BALANCE:.2f}\n📦 المفتوح:\n{open_list if open_list else 'لا يوجد'}"
        send_telegram_msg(msg)

async def daily_report():
    global START_DAY_BALANCE
    while True:
        await asyncio.sleep(86400)
        day_trades = [t for t in closed_trades_history if t['time'] > (datetime.now() - timedelta(days=1))]
        if day_trades:
            wins = len([t for t in day_trades if t['pnl'] > 0])
            total_pnl = sum([t['pnl'] for t in day_trades])
            msg = (f"📅 *التقرير اليومي*\n-------------------\n💰 الرصيد: ${VIRTUAL_BALANCE:.2f}\n"
                   f"📈 التطور: ${VIRTUAL_BALANCE - START_DAY_BALANCE:+.2f}\n✅ صفقات ناجحة: {wins}/{len(day_trades)}\n"
                   f"🏆 Win Rate: {(wins/len(day_trades)*100):.1f}%")
            send_telegram_msg(msg)
            START_DAY_BALANCE = VIRTUAL_BALANCE

# ======================== 6. التشغيل ========================

def send_telegram_msg(msg):
    for chat_id in DESTINATIONS:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}, timeout=5)
        except: pass

async def main_loop():
    send_telegram_msg("🚀 *تم تشغيل النظام بالكامل*\nرصيد: $500 | دخول: $50 | تتبع: نشط")
    while True:
        await scan_market()
        await asyncio.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    loop = asyncio.get_event_loop()
    loop.create_task(manage_trades())
    loop.create_task(hourly_report())
    loop.create_task(daily_report())
    loop.run_until_complete(main_loop())
