import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import os
import gc
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. الإعدادات (تليجرام فقط) ========================
TELEGRAM_TOKEN = 'YOUR_BOT_TOKEN'
TELEGRAM_CHAT_ID = 'YOUR_CHAT_ID'

# الربط العام لجلب الأسعار فقط (بدون مفاتيح API)
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# إعدادات المحفظة الافتراضية
VIRTUAL_BALANCE = 1000.0  # رصيد وهمي للبداية
portfolio = {"open_trades": {}}
trade_history = {}
closed_trades_history = []
current_market_mode = "NORMAL"
daily_start_balance = 1000.0

# ======================== 2. وحدة ذكاء السوق ========================

async def get_market_regime():
    global current_market_mode
    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s]
        top_50 = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:50]
        up_count = sum(1 for sym in top_50 if tickers[sym]['percentage'] > 0.5)
        
        if up_count <= 10:
            current_market_mode = "PROTECT"
            return {"mode": "PROTECT", "max_trades": 3, "vol_mult": 6.0, "mfi_limit": 70, "count": 50}
        elif up_count >= 35:
            current_market_mode = "ULTRA_BULL"
            return {"mode": "ULTRA_BULL", "max_trades": 20, "vol_mult": 1.8, "mfi_limit": 40, "count": 400}
        else:
            current_market_mode = "NORMAL"
            return {"mode": "NORMAL", "max_trades": 10, "vol_mult": 3.0, "mfi_limit": 50, "count": 250}
    except:
        return {"mode": "NORMAL", "max_trades": 10, "vol_mult": 3.0, "mfi_limit": 50, "count": 250}

# ======================== 3. مسح السوق والدخول الافتراضي ========================

async def scan_market():
    global VIRTUAL_BALANCE
    regime = await get_market_regime()
    if len(portfolio["open_trades"]) >= regime['max_trades']: return
    
    # حساب قيمة الصفقة (5% من الرصيد الوهمي)
    trade_amount = max(20, min(VIRTUAL_BALANCE * 0.05, 300))
    
    # التأكد من توفر رصيد وهمي كافٍ
    if VIRTUAL_BALANCE < trade_amount: return

    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s and tickers[s]['quoteVolume'] > 1200000]
        top_symbols = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[10:10+regime['count']]
        
        for sym in top_symbols:
            if sym in portfolio["open_trades"]: continue
            if sym in trade_history and (datetime.now() - trade_history[sym]).total_seconds() < 14400: continue
            
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=100)
            df = calculate_indicators(pd.DataFrame(bars, columns=['ts','open','high','low','close','vol']))
            last = df.iloc[-1]
            
            # فلاتر الدخول
            upper_shadow = last['high'] - max(last['open'], last['close'])
            if upper_shadow > (abs(last['close'] - last['open']) * 0.8): continue
            if last['close'] <= last['ema9'] or last['rsi'] <= 50 or last['mfi'] < regime['mfi_limit']: continue
            
            # تنفيذ "شراء" وهمي
            entry_price = last['close']
            entry_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            portfolio["open_trades"][sym] = {
                "entry_price": entry_price, 
                "highest_p": entry_price, 
                "amount": trade_amount, 
                "time": entry_time
            }
            VIRTUAL_BALANCE -= trade_amount # خصم من الرصيد الوهمي
            trade_history[sym] = datetime.now()

            msg = (
                f"🧪 *دخول افتراضي (Paper)*\n"
                f"🎫 {sym} | ${trade_amount:.1f}\n"
                f"💰 السعر: {entry_price:.6f}\n"
                f"⏰ الوقت: {entry_time}"
            )
            send_telegram_msg(msg)
            
            if len(portfolio["open_trades"]) >= regime['max_trades']: break
            await asyncio.sleep(0.1)
    except: pass

# ======================== 4. إدارة الصفقات والخروج الوهمي ========================

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                profit = (cp - trade['entry_price']) / trade['entry_price']
                
                entry_dt = datetime.strptime(trade['time'], '%Y-%m-%d %H:%M:%S')
                hours_passed = (datetime.now() - entry_dt).total_seconds() / 3600

                # شروط الخروج
                reason = None
                if hours_passed >= 24 and profit < 0.03: reason = "⏰ الزمن (24س)"
                elif current_market_mode == "ULTRA_BULL":
                    portfolio["open_trades"][sym]["highest_p"] = max(trade.get("highest_p", 0), cp)
                    hp = portfolio["open_trades"][sym]["highest_p"]
                    if profit >= 0.03 and ((hp - cp) / hp) >= 0.01: reason = "📈 تتبع الربح"
                elif profit >= 0.03: reason = "🎯 هدف 3%"
                elif profit <= -0.02: reason = "🛑 وقف خسارة -2%"

                if reason:
                    # إعادة المبلغ + الربح/الخسارة للرصيد الوهمي
                    final_amount = trade['amount'] * (1 + profit)
                    VIRTUAL_BALANCE += final_amount
                    
                    profit_pct = profit * 100
                    closed_trades_history.append({"sym": sym, "profit": profit_pct, "exit_time": datetime.now()})
                    portfolio["open_trades"].pop(sym, None)
                    
                    msg = (
                        f"🏁 *إغلاق افتراضي*\n"
                        f"🎫 {sym} | {profit_pct:+.2f}%\n"
                        f"📝 السبب: {reason}\n"
                        f"💰 الرصيد الوهمي الحالي: ${VIRTUAL_BALANCE:.2f}"
                    )
                    send_telegram_msg(msg)

            await asyncio.sleep(20)
        except: await asyncio.sleep(5)

# ======================== 5. التقارير الدورية (وهمي) ========================

async def periodic_reports():
    global daily_start_balance
    last_4h = datetime.now()
    last_24h = datetime.now()
    
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        
        if now - last_4h >= timedelta(hours=4):
            report = f"🕒 *تقرير 4س (افتراضي)*\n📂 مفتوح: {len(portfolio['open_trades'])}\n💰 الرصيد المتوفر: ${VIRTUAL_BALANCE:.2f}"
            send_telegram_msg(report)
            last_4h = now

        if now - last_24h >= timedelta(hours=24):
            growth = ((VIRTUAL_BALANCE - daily_start_balance) / daily_start_balance * 100)
            report = f"📅 *تقرير يومي (افتراضي)*\n💰 الرصيد: ${VIRTUAL_BALANCE:.2f}\n🚀 النمو: {growth:+.2f}%"
            send_telegram_msg(report)
            daily_start_balance = VIRTUAL_BALANCE
            last_24h = now

# ======================== 6. الدوال المساعدة والتشغيل ========================

def calculate_indicators(df):
    close = df['close']
    df['ema9'] = close.ewm(span=9, adjust=False).mean()
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    tp = (df['high'] + df['low'] + close) / 3
    mf = tp * df['vol']
    df['mfi'] = 100 - (100 / (1 + (mf.where(close > close.shift(1), 0).rolling(14).sum() / 
                                  mf.where(close < close.shift(1), 0).rolling(14).sum())))
    return df

def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

app = Flask('')
@app.route('/')
def home(): return f"Snowball Virtual: {VIRTUAL_BALANCE:.2f} USDT"

async def main_loop():
    send_telegram_msg("🧪 *Snowball V11.5 Virtual* بدأ بنجاح.\nالرصيد الافتراضي: 1000 USDT.")
    asyncio.create_task(manage_trades())
    asyncio.create_task(periodic_reports())
    while True:
        try:
            await scan_market()
            await asyncio.sleep(60)
        except: await asyncio.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000))), daemon=True).start()
    asyncio.run(main_loop())
