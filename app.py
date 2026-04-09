import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. إعدادات السيرفر (حل مشكلة توقف Render) ========================
app = Flask('')

@app.route('/')
def home():
    return "🚀 Snowball Bot is Active | Mode: Aggressive | Max 5 Trades"

def run_flask():
    # Render يمرر البورت تلقائياً عبر متغيرات البيئة
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ======================== 2. الإعدادات والمعرفات ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# إعدادات المحفظة وإدارة المخاطر
VIRTUAL_BALANCE = 500.0        # الرصيد الافتراضي الابتدائي
START_DAY_BALANCE = 500.0      # لتعقب النمو اليومي
TRADE_AMOUNT = 50.0            # قيمة الدخول في كل صفقة
MAX_OPEN_TRADES = 5            # الحد الأقصى للصفقات المتزامنة
portfolio = {"open_trades": {}}
closed_trades_history = []
MIN_VOLUME_24H = 3000000       # الحد الأدنى للسيولة (3 مليون دولار)

# ======================== 3. منطق التحليل والاستراتيجية ========================

async def is_market_safe():
    """فلتر البيتكوين: يسمح بالعمل إذا كان صعود BTC أقل من 2.5%"""
    try:
        btc = await EXCHANGE.fetch_ticker('BTC/USDT')
        return (btc['percentage'] or 0) < 2.5 
    except: return True

def get_targets(df):
    """حساب الأهداف بناءً على فيبوناتشي 50%"""
    peak = df['high'].max()
    low = df['low'].min()
    entry = df.iloc[-1]['close']
    
    target = peak - (peak - low) * 0.5 
    stop_loss = peak * 1.015 
    
    expected_profit = ((entry - target) / entry) * 100
    return target, stop_loss, expected_profit

def detect_reversal(df):
    """اكتشاف شمعة الشهاب مع تأكيد الإغلاق"""
    prev = df.iloc[-2] # شمعة الإشارة
    last = df.iloc[-1] # شمعة التأكيد
    
    body = abs(prev['close'] - prev['open'])
    upper_wick = prev['high'] - max(prev['open'], prev['close'])
    
    # الشرط: ذيل علوي طويل + إغلاق تحت قاع شمعة الإشارة
    if upper_wick > (1.5 * body) and last['close'] < prev['low']:
        return True
    return False

# ======================== 4. إدارة المسح والصفقات ========================

async def scan_market():
    global VIRTUAL_BALANCE
    if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES: return
    if not await is_market_safe(): return
    
    try:
        tickers = await EXCHANGE.fetch_tickers()
        # شروط مخففة: صعود > 5% وسيولة جيدة
        symbols = [s for s in tickers.keys() if '/USDT' in s 
                   and (tickers[s]['percentage'] or 0) > 5.0 
                   and (tickers[s]['quoteVolume'] or 0) > MIN_VOLUME_24H]
        
        for sym in symbols:
            if len(portfolio["open_trades"]) >= MAX_OPEN_TRADES: break
            if sym in portfolio["open_trades"]: continue
            if VIRTUAL_BALANCE < TRADE_AMOUNT: continue 

            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=40)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            
            if detect_reversal(df):
                tp, sl, profit_pct = get_targets(df)
                
                # شرط الربح الأدنى 3% لزيادة عدد الصفقات
                if profit_pct >= 3.0:
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
                    
                    msg = (f"⚡ *إشارة دخول (SHORT)*\n"
                           f"🎫 العملة: {sym}\n"
                           f"💰 السعر: {entry_p:.6f}\n"
                           f"🎯 الهدف: {tp:.6f}\n"
                           f"📉 ربح متوقع: {profit_pct:.2f}%\n"
                           f"📦 المراكز: {len(portfolio['open_trades'])}/{MAX_OPEN_TRADES}")
                    send_telegram_msg(msg)
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
                duration = datetime.now() - trade['entry_time']
                
                # --- تفعيل وتحديث التتبع السعري ---
                if pnl_pct >= 1.5: trade["trailing_active"] = True
                if trade["trailing_active"]:
                    new_sl = cp * 1.012 # ملاحقة السعر بمسافة 1.2%
                    if new_sl < trade["trailing_sl"]:
                        trade["trailing_sl"] = new_sl

                # --- شروط الخروج ---
                reason = None
                if cp <= trade['target']: reason = "🎯 تم تحقيق الهدف"
                elif cp >= trade['trailing_sl']: reason = "🛡️ خروج (تتبع/وقف)"
                elif duration > timedelta(hours=4): reason = "⏰ خروج زمني (4س)"
                
                if reason:
                    VIRTUAL_BALANCE += trade['amount'] * (1 + pnl_ratio)
                    closed_trades_history.append({"sym": sym, "pnl": pnl_pct, "time": datetime.now()})
                    icon = "✅" if pnl_pct > 0 else "❌"
                    send_telegram_msg(f"🏁 *إغلاق صفقة*\n🎫 {sym}\n📊 النتيجة: {icon} {pnl_pct:+.2f}%\n💵 الرصيد: ${VIRTUAL_BALANCE:.2f}")
                    del portfolio["open_trades"][sym]
            except: continue
        await asyncio.sleep(15) # مراقبة السعر كل 15 ثانية

# ======================== 5. نظام التقارير الدورية ========================

async def hourly_report():
    while True:
        await asyncio.sleep(3600)
        open_list = "".join([f"• {s}: {( (t['entry_price'] - (await EXCHANGE.fetch_ticker(s))['last']) / t['entry_price'] * 100):+.2f}%\n" for s, t in portfolio["open_trades"].items()])
        msg = (f"📊 *التقرير الساعي*\n"
               f"💰 الرصيد الحالي: ${VIRTUAL_BALANCE:.2f}\n"
               f"📦 الصفقات المفتوحة:\n{open_list if open_list else 'لا يوجد'}")
        send_telegram_msg(msg)

async def daily_report():
    global START_DAY_BALANCE
    while True:
        await asyncio.sleep(86400)
        day_trades = [t for t in closed_trades_history if t['time'] > (datetime.now() - timedelta(days=1))]
        if day_trades:
            wins = len([t for t in day_trades if t['pnl'] > 0])
            msg = (f"📅 *التقرير اليومي*\n"
                   f"💰 الرصيد: ${VIRTUAL_BALANCE:.2f}\n"
                   f"📈 النمو: ${VIRTUAL_BALANCE - START_DAY_BALANCE:+.2f}\n"
                   f"🏆 نسبة النجاح: {(wins/len(day_trades)*100):.1f}%")
            send_telegram_msg(msg)
            START_DAY_BALANCE = VIRTUAL_BALANCE

# ======================== 6. الوظائف العامة والتشغيل ========================

def send_telegram_msg(msg):
    for chat_id in DESTINATIONS:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}, timeout=5)
        except: pass

async def main_loop():
    send_telegram_msg("🚀 *تم بدء التشغيل بالنسخة المكثفة*\nالبوت يبحث عن صعود > 5% وأهداف > 3%.")
    while True:
        await scan_market()
        await asyncio.sleep(60)

if __name__ == "__main__":
    # تشغيل Flask في خيط منفصل لفتح البورت
    threading.Thread(target=run_flask, daemon=True).start()
    
    # تشغيل مهام البوت الأساسية
    loop = asyncio.get_event_loop()
    loop.create_task(manage_trades())
    loop.create_task(hourly_report())
    loop.create_task(daily_report())
    loop.run_until_complete(main_loop())
