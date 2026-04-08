import os
import requests
import ccxt
import pandas as pd
import numpy as np
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# --- إعدادات التلجرام للمجموعة ---
TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"

# أضف هنا أرقام الـ ID الخاصة بأصدقائك (تأكد أن كل صديق قد ضغط Start للبوت)
FRIENDS_IDS = [
    "5067771509", # الـ ID الخاص بك
    "2107567005", # الـ ID الصديق الأول

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
                    f"⚡️ **توصية انفجار سعري جديدة**\n"
                    f"العملة: #{name}\n\n"
                    f"📥 **سعر الدخول:** `{entry:.4f}`\n"
                    f"🎯 **الهدف (6%+):** `{target:.4f}`\n"
                    f"🛑 **وقف الخسارة (3%-):** `{stop:.4f}`\n\n"
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

if __name__ == "__main__":
    send_to_all_friends("🚀 **البوت يعمل الآن!**\nسيتم إرسال الصفقات لجميع المشتركين في هذه القائمة.")
    scan_market = scan_for_explosion()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

