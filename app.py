import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import os
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. الإعدادات والمعرفات ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'

# قائمة المستلمين: [معرفك، معرف الشخص الثاني، معرف القناة الخاصة]
DESTINATIONS = [
    '5067771509',         # معرفك الشخصي
            # استبدله بـ ID الشخص الثاني
    '-1003692815602'      # استبدله بـ ID القناة الخاصة (يبدأ بـ -100)
]

EXCHANGE = ccxt.binance({'enableRateLimit': True})

# متغيرات النظام الافتراضي
VIRTUAL_BALANCE = 1000.0
portfolio = {"open_trades": {}}
trade_history = {}
current_market_mode = "NORMAL"
daily_start_balance = 1000.0

# ======================== 2. وظيفة الإرسال الجماعي ========================

def send_telegram_msg(msg):
    """إرسال الرسالة إلى جميع الوجهات المحددة"""
    for chat_id in DESTINATIONS:
        # تخطي المعرفات غير المكتملة
        if 'XXXXXXXXXX' in str(chat_id) or 'ID_PERSON' in str(chat_id):
            continue
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "Markdown"
            }
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"⚠️ خطأ في الإرسال لـ {chat_id}: {e}")

# ======================== 3. تحليل السوق والذكاء الصناعي ========================

async def get_market_regime():
    global current_market_mode
    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s]
        top_50 = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'] if tickers[x]['quoteVolume'] else 0, reverse=True)[:50]
        up_count = sum(1 for sym in top_50 if tickers[sym].get('percentage', 0) > 0.5)
        
        if up_count <= 10:
            current_market_mode = "PROTECT"
            return {"mode": "PROTECT", "max_trades": 3, "mfi_limit": 70, "count": 50}
        elif up_count >= 35:
            current_market_mode = "ULTRA_BULL"
            return {"mode": "ULTRA_BULL", "max_trades": 20, "mfi_limit": 40, "count": 400}
        else:
            current_market_mode = "NORMAL"
            return {"mode": "NORMAL", "max_trades": 10, "mfi_limit": 50, "count": 250}
    except:
        return {"mode": "NORMAL", "max_trades": 10, "mfi_limit": 50, "count": 250}

# ======================== 4. منطق التداول الافتراضي ========================

async def scan_market():
    global VIRTUAL_BALANCE
    regime = await get_market_regime()
    
    if len(portfolio["open_trades"]) >= regime['max_trades']: return
    
    trade_amount = max(20, min(VIRTUAL_BALANCE * 0.05, 300))
    if VIRTUAL_BALANCE < trade_amount: return

    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s and (tickers[s]['quoteVolume'] or 0) > 1500000]
        top_symbols = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:regime['count']]
        
        for sym in top_symbols:
            if sym in portfolio["open_trades"]: continue
            if sym in trade_history and (datetime.now() - trade_history[sym]).total_seconds() < 14400: continue
            
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=100)
            df = calculate_indicators(pd.DataFrame(bars, columns=['ts','open','high','low','close','vol']))
            last = df.iloc[-1]
            
            # استراتيجية الدخول: EMA + RSI + MFI
            if last['close'] > last['ema9'] and last['rsi'] > 50 and last['mfi'] >= regime['mfi_limit']:
                entry_price = last['close']
                entry_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                portfolio["open_trades"][sym] = {
                    "entry_price": entry_price, 
                    "highest_p": entry_price, 
                    "amount": trade_amount, 
                    "time": entry_time
                }
                VIRTUAL_BALANCE -= trade_amount
                trade_history[sym] = datetime.now()

                msg = (
                    f"🧪 *دخول افتراضي جديد*\n"
                    f"---------------------------\n"
                    f"🎫 العملة: {sym}\n"
                    f"💰 السعر: {entry_price:.6f}\n"
                    f"📊 RSI: {last['rsi']:.1f} | MFI: {last['mfi']:.1f}\n"
                    f"🚀 الوضع: {current_market_mode}\n"
                    f"---------------------------"
                )
                send_telegram_msg(msg)
                
                if len(portfolio["open_trades"]) >= regime['max_trades']: break
                await asyncio.sleep(0.1)
    except Exception as e:
        print(f"Scan Error: {e}")

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

                reason = None
                if hours_passed >= 24 and profit < 0.03: reason = "⏰ انتهاء الوقت (24س)"
                elif profit >= 0.03: reason = "🎯 تحقيق الهدف 3%"
                elif profit <= -0.02: reason = "🛑 وقف الخسارة -2%"

                if reason:
                    final_amount = trade['amount'] * (1 + profit)
                    VIRTUAL_BALANCE += final_amount
                    profit_pct = profit * 100
                    
                    msg = (
                        f"🏁 *إغلاق صفقة افتراضية*\n"
                        f"---------------------------\n"
                        f"🎫 العملة: {sym}\n"
                        f"📈 الربح/الخسارة: {profit_pct:+.2f}%\n"
                        f"📝 السبب: {reason}\n"
                        f"💰 الرصيد الحالي: ${VIRTUAL_BALANCE:.2f}\n"
                        f"---------------------------"
                    )
                    send_telegram_msg(msg)
                    portfolio["open_trades"].pop(sym, None)

            await asyncio.sleep(30)
        except: await asyncio.sleep(10)

# ======================== 5. الأدوات المساعدة ========================

def calculate_indicators(df):
    close = df['close']
    df['ema9'] = close.ewm(span=9, adjust=False).mean()
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))
    tp = (df['high'] + df['low'] + close) / 3
    mf = tp * df['vol']
    pos_mf = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg_mf = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    df['mfi'] = 100 - (100 / (1 + (pos_mf / (neg_mf + 1e-9))))
    return df

app = Flask('')
@app.route('/')
def home(): 
    return f"Snowball Virtual Running... Balance: {VIRTUAL_BALANCE:.2f}"

async def main_loop():
    send_telegram_msg("🚀 *Snowball V11.5 Virtual* متصل الآن!\nيتم الإرسال لجميع المشتركين والقناة.")
    asyncio.create_task(manage_trades())
    while True:
        try:
            await scan_market()
            await asyncio.sleep(60)
        except: await asyncio.sleep(30)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_loop())
