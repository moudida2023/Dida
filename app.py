import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import os
import gc
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. الإعدادات والذاكرة المحسنة ========================
TELEGRAM_TOKEN = '8603477836:AAGG6Outg3Z9vBI-NjWQ3ALJroh_Cye3l2c'
TELEGRAM_CHAT_ID = '-1003692815602'

> Dream Agency:
import os
import requests
import ccxt
import pandas as pd
import numpy as np
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(name)

# --- إعدادات التلجرام للمجموعة ---
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"

# أضف هنا أرقام الـ ID الخاصة بأصدقائك (تأكد أن كل صديق قد ضغط Start للبوت)
FRIENDS_IDS = [
    "5067771509", # الـ ID الخاص بك
    "2107567005"# الـ ID الصديق الأول

]

def send_to_all_friends(message):
    """إرسال الرسالة لكل شخص في القائمة"""
    for chat_id in FRIENDS_IDS:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"Error sending to {chat_id}: {e}")

def scan_for_explosion():
    print("🚀 جاري فحص السوق وإرسال الصفقات للأصدقاء...")
    try:
        exchange = ccxt.binance()
        tickers = exchange.fetch_tickers()
        symbols = [s for s in tickers if s.endswith('/USDT')]
        sorted_symbols = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:30]
        
        for symbol in sorted_symbols:
            bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            
            # حساب RSI
            delta = df['c'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / (loss + 1e-9)
            df['RSI'] = 100 - (100 / (1 + rs))
            
            # حساب انضغاط البولنجر
            df['MA20'] = df['c'].rolling(20).mean()
            df['STD'] = df['c'].rolling(20).std()
            df['Upper'] = df['MA20'] + (df['STD'] * 2)
            df['Lower'] = df['MA20'] - (df['STD'] * 2)
            df['Width'] = (df['Upper'] - df['Lower']) / df['MA20'] * 100
            
            last = df.iloc[-1]
            
            # شروط الصفقة (RSI 50-60 وانضغاط < 2%)
            if last['Width'] < 2.0 and 50 <= last['RSI'] <= 60:
                entry = last['c']
                target = entry * 1.06
                stop = entry * 0.97
                
                name = symbol.replace('/USDT', '')
                msg = (
                    f"⚡️ توصية انفجار سعري جديدة\n"
                    f"العملة: #{name}\n\n"
                    f"📥 سعر الدخول: {entry:.4f}\n"
                    f"🎯 الهدف (6%+): {target:.4f}\n"
                    f"🛑 وقف الخسارة (3%-): {stop:.4f}\n\n"
                    f"📊 RSI: {last['RSI']:.2f} | الضغط: {last['Width']:.2f}%"
                )
                send_to_all_friends(msg)
                
    except Exception as e:
        print(f"Scan Error: {e}")

# المجدول الزمني كل 15 دقيقة
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(scan_for_explosion, 'interval', minutes=15)
scheduler.start()

@app.route('/')
def home():
    return "<h1>البوت يرسل الصفقات لجميع الأصدقاء المضافين!</h1>"

if name == "main":
    send_to_all_friends("🚀 البوت يعمل الآن!\nسيتم إرسال الصفقات لجميع المشتركين في هذه القائمة.")
    scan_market = scan_for_explosion()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


> Dream Agency:
import os
import requests
import ccxt
import pandas as pd
import numpy as np
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(name)

# --- إعدادات التلجرام للمجموعة ---
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"

# أضف هنا أرقام الـ ID الخاصة بأصدقائك (تأكد أن كل صديق قد ضغط Start للبوت)
FRIENDS_IDS = [
    "5067771509", # الـ ID الخاص بك
    "2107567005"# الـ ID الصديق الأول

]

def send_to_all_friends(message):
    """إرسال الرسالة لكل شخص في القائمة"""
    for chat_id in FRIENDS_IDS:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"Error sending to {chat_id}: {e}")

def scan_for_explosion():
    print("🚀 جاري فحص السوق وإرسال الصفقات للأصدقاء...")
    try:
        exchange = ccxt.binance()
        tickers = exchange.fetch_tickers()
        symbols = [s for s in tickers if s.endswith('/USDT')]
        sorted_symbols = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:30]
        
        for symbol in sorted_symbols:
            bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            
            # حساب RSI
            delta = df['c'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / (loss + 1e-9)
            df['RSI'] = 100 - (100 / (1 + rs))
            
            # حساب انضغاط البولنجر
            df['MA20'] = df['c'].rolling(20).mean()
            df['STD'] = df['c'].rolling(20).std()
            df['Upper'] = df['MA20'] + (df['STD'] * 2)
            df['Lower'] = df['MA20'] - (df['STD'] * 2)
            df['Width'] = (df['Upper'] - df['Lower']) / df['MA20'] * 100
            
            last = df.iloc[-1]
            
            # شروط الصفقة (RSI 50-60 وانضغاط < 2%)
            if last['Width'] < 2.0 and 50 <= last['RSI'] <= 60:
                entry = last['c']
                target = entry * 1.06
                stop = entry * 0.97
                
                name = symbol.replace('/USDT', '')
                msg = (
                    f"⚡️ توصية انفجار سعري جديدة\n"
                    f"العملة: #{name}\n\n"
                    f"📥 سعر الدخول: {entry:.4f}\n"
                    f"🎯 الهدف (6%+): {target:.4f}\n"
                    f"🛑 وقف الخسارة (3%-): {stop:.4f}\n\n"
                    f"📊 RSI: {last['RSI']:.2f} | الضغط: {last['Width']:.2f}%"
                )
                send_to_all_friends(msg)
                
    except Exception as e:
        print(f"Scan Error: {e}")

# المجدول الزمني كل 15 دقيقة
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(scan_for_explosion, 'interval', minutes=15)
scheduler.start()

@app.route('/')
def home():
    return "<h1>البوت يرسل الصفقات لجميع الأصدقاء المضافين!</h1>"

if name == "main":
    send_to_all_friends("🚀 البوت يعمل الآن!\nسيتم إرسال الصفقات لجميع المشتركين في هذه القائمة.")
    scan_market = scan_for_explosion()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
'
EXCHANGE = ccxt.binance({'enableRateLimit': True, 'apiKey': 'API_KEY', 'secret': 'SECRET_KEY'})

portfolio = {"open_trades": {}}
closed_trades_history = [] # سجل الصفقات المغلقة للتقارير
daily_start_balance = 0.0

# ======================== 2. نظام الإشعارات والتقارير المطور ========================

def calculate_duration(start_time):
    """حساب المدة الزمنية بين الدخول والآن"""
    fmt = '%Y-%m-%d %H:%M:%S'
    tdelta = datetime.now() - datetime.strptime(start_time, fmt)
    hours, remainder = divmod(tdelta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{tdelta.days}d {hours}h {minutes}m"

async def send_exit_notification(sym, price, profit_pct, start_time, reason):
    """إشعار خروج تفصيلي"""
    duration = calculate_duration(start_time)
    msg = (
        f"🏁 *إشعار خروج من صفقة*\n"
        f"---------------------------\n"
        f"🎫 *العملة:* {sym}\n"
        f"💰 *سعر الإغلاق:* {price:.6f}\n"
        f"📈 *النتيجة:* {profit_pct:+.2f}%\n"
        f"⏳ *المدة:* {duration}\n"
        f"📝 *السبب:* {reason}\n"
        f"---------------------------"
    )
    send_telegram_msg(msg)

async def four_hour_report():
    """تقرير كل 4 ساعات عن الصفقات المفتوحة والمغلقة مؤخراً"""
    while True:
        await asyncio.sleep(14400) # 4 ساعات
        open_list = "\n".join([f"• {s}: {((await EXCHANGE.fetch_ticker(s))['last'] - v['entry_price'])/v['entry_price']*100:+.2f}%" for s, v in portfolio["open_trades"].items()]) or "لا يوجد"
        
        recent_closed = [t for t in closed_trades_history if (datetime.now() - t['exit_time']) < timedelta(hours=4)]
        closed_msg = "\n".join([f"• {t['sym']}: {t['profit']:+.2f}%" for t in recent_closed]) or "لا يوجد"

        report = (
            f"🕒 *تقرير الـ 4 ساعات*\n"
            f"---------------------------\n"
            f"📂 *صفقات مفتوحة حالياً:*\n{open_list}\n\n"
            f"✅ *صفقات أُغلقت مؤخراً:*\n{closed_msg}\n"
            f"---------------------------"
        )
        send_telegram_msg(report)

async def daily_performance_report():
    """تقرير يومي شامل وتطور المحفظة"""
    global daily_start_balance
    while True:
        await asyncio.sleep(86400) # 24 ساعة
        try:
            balance = await EXCHANGE.fetch_balance()
            current_bal = balance['total']['USDT']
            growth = ((current_bal - daily_start_balance) / daily_start_balance * 100) if daily_start_balance > 0 else 0
            
            daily_closed = [t for t in closed_trades_history if (datetime.now() - t['exit_time']) < timedelta(hours=24)]
            total_p = sum([t['profit'] for t in daily_closed])
            
            report = (
                f"📅 *التقرير اليومي للمحفظة*\n"
                f"---------------------------\n"
                f"💰 *الرصيد الحالي:* ${current_bal:,.2f}\n"
                f"📈 *نمو المحفظة اليومي:* {growth:+.2f}%\n"
                f"📊 *صافي أرباح الصفقات:* {total_p:+.2f}%\n"
                f"✅ *عدد الصفقات المكتملة:* {len(daily_closed)}\n"
                f"---------------------------\n"
                f"🚀 استمر في ملاحقة الأهداف!"
            )
            send_telegram_msg(report)
            daily_start_balance = current_bal # إعادة تعيين الرصيد لبداية يوم جديد
        except: pass

# ======================== 3. إدارة الصفقات مع الإغلاق الزمني ========================

async def manage_trades():
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                profit = (cp - trade['entry_price']) / trade['entry_price']
                
                # حساب وقت البقاء في الصفقة
                fmt = '%Y-%m-%d %H:%M:%S'
                entry_dt = datetime.strptime(trade['time'], fmt)
                hours_passed = (datetime.now() - entry_dt).total_seconds() / 3600

                # 1. شرط الإغلاق الزمني (تجاوز 24 ساعة دون تحقيق 3%)
                if hours_passed >= 24 and profit < 0.03:
                    await close_and_notify(sym, cp, trade, "⏰ Time Limit Exceeded (24h)")
                    continue

                # 2. جني الأرباح (تتبع أو هدف قار)
                if profit >= 0.03:
                    await close_and_notify(sym, cp, trade, "🎯 Target Reached")
                    continue
                
                # 3. وقف الخسارة
                if profit <= -0.02:
                    await close_and_notify(sym, cp, trade, "🛑 Stop Loss Hit")
                    continue

            await asyncio.sleep(30)
        except: await asyncio.sleep(10)

async def close_and_notify(sym, price, trade, reason):
    """تنفيذ الإغلاق، تسجيل التاريخ، وإرسال الإشعار"""
    profit_pct = (price - trade['entry_price']) / trade['entry_price'] * 100
    
    # تسجيل في التاريخ للتقارير
    closed_trades_history.append({
        "sym": sym, 
        "profit": profit_pct, 
        "exit_time": datetime.now()
    })
    
    # حذف من المحفظة النشطة
    portfolio["open_trades"].pop(sym, None)
    
    # إرسال الإشعار التفصيلي
    await send_exit_notification(sym, price, profit_pct, trade['time'], reason)

# ======================== 4. التشغيل الرئيسي ========================

async def main_loop():
    global daily_start_balance
    await asyncio.sleep(5)
    
    # جلب الرصيد الأولي للتقرير اليومي
    bal = await EXCHANGE.fetch_balance()
    daily_start_balance = bal['total']['USDT']
    
    send_telegram_msg("🏗️ *Snowball V11.0 Enterprise* جاهز.\nالتقارير الدورية والإغلاق الزمني مفعلة.")
    
    asyncio.create_task(manage_trades())
    asyncio.create_task(four_hour_report())
    asyncio.create_task(daily_performance_report())
    
    while True:
        try:
            # هنا تستدعي دالة scan_market (من النسخة السابقة V10.2)
            # await scan_market() 
            await asyncio.sleep(60)
        except: await asyncio.sleep(30)

def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                       json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

# ... (بقية دوال الفلاسك والتشغيل)
