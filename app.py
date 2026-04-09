import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. الإعدادات والبيانات الأساسية ========================
app = Flask('')
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# ملاحظة: ضع رابط تطبيقك بعد الرفع هنا لضمان استمرار العمل
RENDER_URL = "https://your-app-name.onrender.com/" 

# إعدادات المحفظة الافتراضية
INITIAL_BALANCE = 500.0
CURRENT_BALANCE = 500.0
MAX_TRADES = 10
TRADE_AMOUNT = 50.0 
OPEN_TRADES = {}     
CLOSED_TRADES = []   

@app.route('/')
def home():
    return f"🚀 Sniper Elite Bot Active | Balance: {CURRENT_BALANCE:.2f}$ | Open: {len(OPEN_TRADES)}"

# ======================== 2. محرك التقييم الفني (Scoring) ========================

def calculate_advanced_score(df):
    try:
        if len(df) < 200: return 0
        close = df['close']
        
        # --- حساب المؤشرات الفنية ---
        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        
        # MFI (تدفق السيولة)
        tp = (df['high'] + df['low'] + close) / 3
        mf = tp * df['vol']
        pos_f = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
        neg_f = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
        mfi = 100 - (100 / (1 + (pos_f / (neg_f + 1e-9))))
        
        # Bollinger Width (الانضغاط)
        sma = close.rolling(20).mean()
        std = close.rolling(20).std()
        width = (4 * std) / (sma + 1e-9)
        
        # EMA 200 (الاتجاه العام)
        ema200 = close.ewm(span=200, adjust=False).mean()

        # --- توزيع الدرجات (Score out of 100) ---
        score = 0
        last = -1
        
        if close.iloc[last] > ema200.iloc[last]: score += 20    # فوق متوسط 200 (+20)
        if width.iloc[last] < 0.035: score += 40               # انضغاط قوي جداً (+40)
        elif width.iloc[last] < 0.05: score += 20              # انضغاط متوسط (+20)
        if 50 < rsi.iloc[last] < 65: score += 20               # منطقة انطلاق (+20)
        if mfi.iloc[last] > 60: score += 20                    # دخول سيولة حقيقية (+20)
        
        return score
    except: return 0

# ======================== 3. دورة القنص والمراقبة ========================

async def sniper_cycle():
    global CURRENT_BALANCE
    while True:
        try:
            start_time = datetime.now()
            send_telegram("🔍 *بدء دورة المسح الشامل (500 عملة)...*")
            
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s 
                       and s not in ['BTC/USDT', 'ETH/USDT', 'USDC/USDT', 'FDUSD/USDT']]
            
            candidates = []
            
            # مسح العملات واحدة تلو الأخرى
            for sym in symbols:
                if sym in OPEN_TRADES: continue
                try:
                    bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='4h', limit=205)
                    df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
                    score = calculate_advanced_score(df)
                    
                    if score >= 80: # الدخول فقط في النخبة
                        candidates.append({'symbol': sym, 'score': score, 'price': df['close'].iloc[-1]})
                except: continue
                await asyncio.sleep(0.01) # حماية من حظر API

            # اختيار الأفضل والدخول
            if candidates and len(OPEN_TRADES) < MAX_TRADES:
                best = sorted(candidates, key=lambda x: x['score'], reverse=True)[0]
                sym, price, scr = best['symbol'], best['price'], best['score']
                
                OPEN_TRADES[sym] = {'entry': price, 'current': price, 'time': datetime.now()}
                CURRENT_BALANCE -= TRADE_AMOUNT
                
                send_telegram(f"🎯 *قنص أفضل عملة لهذه الدورة*\n💎 العملة: `{sym}`\n🏆 السكور: `{scr}/100`\n💰 السعر: `{price:.6f}`\n📍 المتبقي: `{CURRENT_BALANCE:.2f}$`")
            else:
                send_telegram("⚠️ *انتهى المسح: لم توجد فرص بسكور مرتفع حالياً.*")

            # ضبط الدورة لتتكرر كل 30 دقيقة بالضبط
            elapsed = (datetime.now() - start_time).total_seconds()
            await asyncio.sleep(max(0, 1800 - elapsed))

        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(60)

async def monitor_pnl():
    global CURRENT_BALANCE
    while True:
        try:
            if OPEN_TRADES:
                tickers = await EXCHANGE.fetch_tickers(list(OPEN_TRADES.keys()))
                for sym in list(OPEN_TRADES.keys()):
                    curr_price = tickers[sym]['last']
                    entry = OPEN_TRADES[sym]['entry']
                    change = (curr_price - entry) / entry
                    
                    # الخروج بربح 6% أو خسارة 3%
                    if change >= 0.06 or change <= -0.03:
                        pnl = TRADE_AMOUNT * change
                        CURRENT_BALANCE += (TRADE_AMOUNT + pnl)
                        status = "✅ هدف +6%" if change >= 0.06 else "❌ وقف -3%"
                        send_telegram(f"🔔 *إغلاق صفقة*\n💎 `{sym}` | {status}\n💰 الربح/الخسارة: `{pnl:+.2f}$`\n💵 الرصيد الحالي: `{CURRENT_BALANCE:.2f}$`")
                        del OPEN_TRADES[sym]
        except: pass
        await asyncio.sleep(20)

async def keep_alive():
    while True:
        try: requests.get(RENDER_URL, timeout=10)
        except: pass
        await asyncio.sleep(600)

def send_telegram(msg):
    for cid in DESTINATIONS:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                          json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        except: pass

# ======================== 4. التشغيل النهائي ========================

if __name__ == "__main__":
    # تشغيل سيرفر ويب صغير في الخلفية
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080, use_reloader=False), daemon=True).start()
    
    loop = asyncio.get_event_loop()
    loop.create_task(sniper_cycle())
    loop.create_task(monitor_pnl())
    loop.create_task(keep_alive())
    loop.run_forever()
