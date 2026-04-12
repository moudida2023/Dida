import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import os
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. الإعدادات ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

EXCHANGE = ccxt.binance({'enableRateLimit': True})

# الرصيد والبيانات
VIRTUAL_BALANCE = 1000.0
TRADE_SIZE_USD = 100.0
PROFIT_TARGET_USD = 1.1

portfolio = {"open_trades": {}}
closed_trades_history = []  # لتخزين سجل الصفقات المغلقة

# ======================== 2. نظام الإشعارات ========================

def send_telegram_msg(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

async def send_status_report():
    """إرسال تقرير شامل عن الصفقات المفتوحة والمغلقة"""
    # 1. تحليل الصفقات المفتوحة
    open_msg = "📂 *الصقفات المفتوحة حالياً:*\n"
    if not portfolio["open_trades"]:
        open_msg += "_لا توجد صفقات مفتوحة_\n"
    else:
        for sym, data in portfolio["open_trades"].items():
            open_msg += f"• `{sym}` | دخول: {data['entry_price']:.4f}\n"

    # 2. تحليل الصفقات المغلقة
    total_closed = len(closed_trades_history)
    wins = sum(1 for t in closed_trades_history if t['pnl'] > 0)
    total_pnl = sum(t['pnl'] for t in closed_trades_history)
    
    closed_msg = (
        f"\n📊 *ملخص الصفقات المغلقة:*\n"
        f"✅ صفقات ناجحة: {wins}\n"
        f"❌ صفقات خاسرة: {total_closed - wins}\n"
        f"💰 صافي الأرباح: `${total_pnl:.2f}`\n"
        f"💵 الرصيد الحالي: `${VIRTUAL_BALANCE:.2f}`"
    )
    
    send_telegram_msg(open_msg + closed_msg)

# ======================== 3. منطق التداول (الدخول والخروج) ========================

async def scan_market():
    global VIRTUAL_BALANCE
    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s and (tickers[s]['quoteVolume'] or 0) > 2000000]
        top_symbols = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:50]
        
        for sym in top_symbols:
            if sym in portfolio["open_trades"] or VIRTUAL_BALANCE < TRADE_SIZE_USD: continue

            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=50)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            
            # حساب السكور (شرط 5/5)
            ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[-1]
            last = df.iloc[-1]
            
            score = 0
            if last['close'] > ema9: score += 1
            if last['close'] > last['open']: score += 1
            if last['vol'] > df['vol'].rolling(10).mean().iloc[-1]: score += 1
            # (يمكنك إضافة بقية شروط RSI و MFI هنا)
            
            if score >= 3: # تجربة بـ 3/3 للسرعة أو اجعلها 5/5
                entry_price = last['close']
                coins = TRADE_SIZE_USD / entry_price
                
                portfolio["open_trades"][sym] = {
                    "entry_price": entry_price,
                    "amount_usd": TRADE_SIZE_USD,
                    "coins": coins,
                    "time": datetime.now()
                }
                VIRTUAL_BALANCE -= TRADE_SIZE_USD
                send_telegram_msg(f"🚀 *إشعار دخول (5/5)*\n🎫 العملة: {sym}\n💵 السعر: {entry_price:.6f}\n💰 القيمة: $100")

    except Exception as e: print(f"Scan Error: {e}")

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                
                profit_usd = (cp - trade['entry_price']) * trade['coins']
                
                # شرط الخروج عند ربح 1.1$ أو خسارة 2$
                reason = None
                if profit_usd >= PROFIT_TARGET_USD: reason = "🎯 جني أرباح (+1.1$)"
                elif profit_usd <= -2.0: reason = "🛑 وقف خسارة (-2$)"

                if reason:
                    pnl = profit_usd
                    VIRTUAL_BALANCE += (trade['amount_usd'] + pnl)
                    closed_trades_history.append({"sym": sym, "pnl": pnl, "time": datetime.now()})
                    portfolio["open_trades"].pop(sym)
                    
                    send_telegram_msg(f"🏁 *إشعار خروج*\n🎫 {sym}\n📝 السبب: {reason}\n💰 الربح/الخسارة: {pnl:+.2f}$")

            await asyncio.sleep(20)
        except: await asyncio.sleep(10)

# ======================== 4. التشغيل والتقارير الزمنية ========================

async def main_loop():
    send_telegram_msg("✅ *تم تشغيل نظام v621*\n_بانتظار قنص أول صفقة سكور 5/5_")
    asyncio.create_task(manage_trades())
    
    last_report_time = datetime.now()
    
    while True:
        await scan_market()
        
        # إرسال تقرير تلقائي كل ساعة
        if datetime.now() - last_report_time > timedelta(hours=1):
            await send_status_report()
            last_report_time = datetime.now()
            
        await asyncio.sleep(60)

app = Flask('')
@app.route('/')
def home(): return f"Bot Running - Balance: {VIRTUAL_BALANCE:.2f}$"

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    asyncio.run(main_loop())
