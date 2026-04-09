import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. الإعدادات والذاكرة ========================
app = Flask('')

# إعدادات التلجرام وباينانس
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# رابط التطبيق على رندر (تأكد من تحديثه بعد الرفع لإبقاء البوت حياً)
RENDER_URL = "https://your-app-name.onrender.com/" 

# إعدادات المحفظة الافتراضية
INITIAL_BALANCE = 500.0
CURRENT_BALANCE = 500.0
MAX_TRADES = 10
TRADE_AMOUNT = 50.0  # توزيع 500$ على 10 صفقات
OPEN_TRADES = {}     # الصفقات المفتوحة حالياً
CLOSED_TRADES = []   # سجل الصفقات المغلقة
PREVIOUS_SIGNALS = set() # ذاكرة لتأكيد استمرارية الإشارة

@app.route('/')
def home():
    return f"🚀 Sniper Bot Active | Balance: {CURRENT_BALANCE:.2f}$ | Open Trades: {len(OPEN_TRADES)}"

# ======================== 2. محرك التحليل الفني المطور ========================

def calculate_advanced_metrics(df):
    try:
        close = df['close']
        # 1. البولنجر باند والضيق (Squeeze)
        sma = close.rolling(20).mean()
        std = close.rolling(20).std()
        df['width'] = (4 * std) / (sma + 1e-9)
        
        # 2. فلتر الاتجاه العام (EMA 200) لضمان الدخول مع التيار
        df['ema_200'] = close.ewm(span=200, adjust=False).mean()
        
        # 3. فلتر حجم التداول (Volume Spike) للتأكد من وجود زخم
        df['vol_avg_10'] = df['vol'].rolling(window=10).mean()
        
        # 4. تدفق السيولة (MFI) لمعرفة دخول الأموال الذكية
        tp = (df['high'] + df['low'] + close) / 3
        mf = tp * df['vol']
        pos_f = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
        neg_f = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
        df['mfi'] = 100 - (100 / (1 + (pos_f / (neg_f + 1e-9))))
        
        return df
    except:
        return df

def check_entry_signal(df):
    if df.empty or len(df) < 200: return False, None
    last = df.iloc[-1]
    
    # شروط الدخول الذهبية لربح 6% باستقرار
    is_uptrend = last['close'] > last['ema_200']             # السعر فوق EMA 200
    is_squeezed = last['width'] < 0.05                      # انضغاط سعري أقل من 5%
    has_volume = last['vol'] > (last['vol_avg_10'] * 1.2)   # انفجار في حجم التداول
    has_money_flow = last['mfi'] > 55                       # سيولة شرائية واضحة
    
    if is_uptrend and is_squeezed and has_volume and has_money_flow:
        return True, last['close']
    return False, None

# ======================== 3. نظام التنبيهات والتقارير ========================

def send_telegram(msg):
    for cid in DESTINATIONS:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        except: pass

def get_status_report():
    report = f"📊 *تقرير المحفظة المباشر*\n"
    report += f"💰 الرصيد المتوفر: `{CURRENT_BALANCE:.2f}$`\n"
    report += f"📍 صفقات نشطة: `{len(OPEN_TRADES)}/{MAX_TRADES}`\n"
    report += "───────────────────\n"
    if OPEN_TRADES:
        for sym, data in OPEN_TRADES.items():
            pnl_pct = ((data['current'] - data['entry']) / data['entry']) * 100
            report += f"• *{sym}*: `{pnl_pct:+.2f}%` | دخول: `{data['entry']:.4f}`\n"
    else:
        report += "_لا توجد صفقات مفتوحة حالياً._\n"
    return report

# ======================== 4. المهام الآلية (Async Tasks) ========================

async def scan_and_trade():
    global PREVIOUS_SIGNALS, CURRENT_BALANCE
    current_index = 0
    BATCH_SIZE = 50 

    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s 
                       and s not in ['BTC/USDT', 'ETH/USDT', 'USDC/USDT', 'FDUSD/USDT']]
            
            batch = symbols[current_index : current_index + BATCH_SIZE]
            current_index = 0 if current_index + BATCH_SIZE >= len(symbols) else current_index + BATCH_SIZE
            
            current_cycle_signals = []
            for sym in batch:
                if len(OPEN_TRADES) >= MAX_TRADES: break
                if sym in OPEN_TRADES: continue
                
                try:
                    bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='4h', limit=210)
                    df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
                    df = calculate_advanced_metrics(df)
                    can_enter, entry_price = check_entry_signal(df)
                    
                    if can_enter:
                        if sym in PREVIOUS_SIGNALS: # تأكيد الاستمرارية للدورة الثانية
                            OPEN_TRADES[sym] = {'entry': entry_price, 'current': entry_price, 'time': datetime.now()}
                            CURRENT_BALANCE -= TRADE_AMOUNT
                            send_telegram(f"🚀 *دخول صفقة جديدة*\n💎 العملة: `{sym}`\n💰 السعر: `{entry_price:.6f}`\n📈 الاتجاه: `صاعد 4H`")
                        current_cycle_signals.append(sym)
                except: continue
                await asyncio.sleep(0.02)
            
            PREVIOUS_SIGNALS = set(current_cycle_signals)
        except Exception as e: print(f"Scan Error: {e}")
        await asyncio.sleep(300)

async def monitor_pnl():
    global CURRENT_BALANCE, OPEN_TRADES, CLOSED_TRADES
    while True:
        try:
            if OPEN_TRADES:
                tickers = await EXCHANGE.fetch_tickers(list(OPEN_TRADES.keys()))
                for sym in list(OPEN_TRADES.keys()):
                    curr_price = tickers[sym]['last']
                    OPEN_TRADES[sym]['current'] = curr_price
                    change = (curr_price - OPEN_TRADES[sym]['entry']) / OPEN_TRADES[sym]['entry']
                    
                    # الخروج: ربح 6% أو خسارة 3%
                    if change >= 0.06 or change <= -0.03:
                        pnl = TRADE_AMOUNT * change
                        CURRENT_BALANCE += (TRADE_AMOUNT + pnl)
                        result = "✅ هدف (+6%)" if change >= 0.06 else "❌ وقف (-3%)"
                        send_telegram(f"🔔 *إغلاق صفقة*\n💎 العملة: `{sym}`\n📢 النتيجة: `{result}`\n💰 الربح/الخسارة: `{pnl:+.2f}$`")
                        CLOSED_TRADES.append({'pnl': pnl, 'time': datetime.now()})
                        del OPEN_TRADES[sym]
        except: pass
        await asyncio.sleep(20)

async def keep_alive():
    """هذه الدالة تمنع رندر من إغلاق البوت (Keep-Alive)"""
    while True:
        try:
            requests.get(RENDER_URL, timeout=10)
        except: pass
        await asyncio.sleep(600) # كل 10 دقائق

async def report_scheduler():
    next_hour = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while True:
        now = datetime.now()
        if now >= next_hour:
            send_telegram(get_status_report())
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        await asyncio.sleep(60)

# ======================== 5. الانطلاق ========================

def run_flask():
    app.run(host='0.0.0.0', port=8080, use_reloader=False)

if __name__ == "__main__":
    # تشغيل Flask للسيرفر في الخلفية
    threading.Thread(target=run_flask, daemon=True).start()
    
    # تشغيل المحركات الأساسية
    loop = asyncio.get_event_loop()
    loop.create_task(scan_and_trade())
    loop.create_task(monitor_pnl())
    loop.create_task(report_scheduler())
    loop.create_task(keep_alive())
    
    try:
        loop.run_forever()
    except Exception as e:
        print(f"Bot Crashed: {e}")
