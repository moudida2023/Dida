import os
import requests
import ccxt
import pandas as pd
import numpy as np
from flask import Flask
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

# ======================== 1. الإعدادات العامة ========================
# توكن البوت (تأكد من صحته)
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"

# قائمة الـ IDs للمشتركين
FRIENDS_IDS = [
    "5067771509", 
    "2107567005",
    "1003692815602"
]

# إعداد المنصة (بايننس)
EXCHANGE = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

app = Flask(__name__)

# ذاكرة الصفقات المفتوحة
portfolio = {"open_trades": {}}

# ======================== 2. وظائف التلجرام ========================

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
            print(f"خطأ في الإرسال لـ {chat_id}: {e}")

# ======================== 3. منطق فحص السوق ========================

def scan_for_explosion():
    print(f"🚀 فحص السوق: {datetime.now().strftime('%H:%M:%S')}")
    try:
        tickers = EXCHANGE.fetch_tickers()
        # اختيار العملات مقابل USDT التي لديها حجم تداول جيد
        symbols = [s for s in tickers if s.endswith('/USDT')]
        sorted_symbols = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:30]
        
        for symbol in sorted_symbols:
            bars = EXCHANGE.fetch_ohlcv(symbol, timeframe='15m', limit=50)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            
            # حساب RSI
            delta = df['c'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / (loss + 1e-9)
            df['RSI'] = 100 - (100 / (1 + rs))
            
            # حساب انضغاط البولنجر (Bollinger Band Width)
            df['MA20'] = df['c'].rolling(20).mean()
            df['STD'] = df['c'].rolling(20).std()
            df['Upper'] = df['MA20'] + (df['STD'] * 2)
            df['Lower'] = df['MA20'] - (df['STD'] * 2)
            df['Width'] = (df['Upper'] - df['Lower']) / df['MA20'] * 100
            
            last = df.iloc[-1]
            
            # شروط الاستراتيجية: ضغط سعري أقل من 2% و RSI بين 50 و 60
            if last['Width'] < 2.0 and 50 <= last['RSI'] <= 60:
                if symbol not in portfolio["open_trades"]:
                    entry = last['c']
                    target = entry * 1.06
                    stop = entry * 0.97
                    
                    name = symbol.replace('/USDT', '')
                    msg = (
                        f"⚡️ *توصية انفجار سعري جديدة*\n"
                        f"---------------------------\n"
                        f"🎫 العملة: #{name}\n"
                        f"📥 سعر الدخول: {entry:.4f}\n"
                        f"🎯 الهدف (+6%): {target:.4f}\n"
                        f"🛑 وقف الخسارة (-3%): {stop:.4f}\n"
                        f"📊 RSI: {last['RSI']:.2f} | الضغط: {last['Width']:.2f}%\n"
                        f"---------------------------"
                    )
                    send_to_all_friends(msg)
                    # إضافة الصفقة للذاكرة لتجنب التكرار
                    portfolio["open_trades"][symbol] = datetime.now()
                    
    except Exception as e:
        print(f"Scan Error: {e}")

# تنظيف الصفقات القديمة من الذاكرة كل 24 ساعة للسماح بتوصيات جديدة لنفس العملة
def cleanup_portfolio():
    portfolio["open_trades"] = {}

# ======================== 4. المجدول والتشغيل ========================

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(scan_for_explosion, 'interval', minutes=15)
scheduler.add_job(cleanup_portfolio, 'interval', hours=24)
scheduler.start()

@app.route('/')
def home():
    return f"<h1>البوت يعمل!</h1><p>عدد الصفقات في الذاكرة حالياً: {len(portfolio['open_trades'])}</p>"

if __name__ == "__main__":
    # إرسال رسالة ترحيب عند بدء التشغيل
    send_to_all_friends("🚀 *البوت بدأ العمل بنجاح!*\nسيتم فحص السوق كل 15 دقيقة وإرسال أقوى الفرص.")
    
    # تشغيل فحص أولي فوراً
    scan_for_explosion()
    
    # تشغيل سيرفر Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
