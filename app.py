import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
import numpy as np
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. إعدادات السيرفر والتلجرام ========================
app = Flask('')

@app.route('/')
def home():
    return "🚀 Crypto Squeeze & Divergence Bot is Active"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# ======================== 2. الحسابات الفنية (بدون pandas_ta) ========================

def get_indicators(df):
    """حساب RSI والبولنجر باند يدوياً"""
    close = df['close']
    
    # 1. حساب البولنجر باند (20, 2)
    sma = close.rolling(window=20).mean()
    std = close.rolling(window=20).std()
    upper_bb = sma + (2 * std)
    lower_bb = sma - (2 * std)
    bandwidth = (upper_bb - lower_bb) / sma
    
    # 2. حساب RSI يدوياً
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    df['rsi'] = rsi
    df['bb_width'] = bandwidth
    df['upper_bb'] = upper_bb
    return df

def detect_squeeze_and_div(df):
    """اكتشاف الانخناق والدايفرجنس"""
    last = df.iloc[-1]
    
    # أ- فحص انخناق البولنجر (أقل من 6%)
    is_squeezed = last['bb_width'] < 0.06
    
    # ب- فحص الدايفرجنس الصعودي
    curr_low, curr_rsi = df['low'].iloc[-1], df['rsi'].iloc[-1]
    prev_low = df['low'].iloc[-20:-5].min()
    prev_rsi_low = df['rsi'].iloc[-20:-5].min()
    has_div = curr_low < prev_low and curr_rsi > prev_rsi_low
    
    # ج- شمعة تأكيد (ابتلاعية)
    prev = df.iloc[-2]
    is_engulfing = last['close'] > prev['open'] and last['open'] < prev['close'] and last['close'] > last['open']

    return is_squeezed, has_div, is_engulfing

# ======================== 3. منطق التداول والمسح الدوري ========================

async def scan_market():
    send_telegram_msg("🔍 *بدء دورة المسح الدوري (كل 15 دقيقة)*")
    try:
        tickers = await EXCHANGE.fetch_tickers()
        # تصفية العملات الصغير والمتوسطة (تجنب BTC/ETH والمستقرة)
        symbols = [s for s in tickers.keys() if '/USDT' in s 
                   and s not in ['BTC/USDT', 'ETH/USDT', 'USDC/USDT', 'FDUSD/USDT']]
        
        found_signals = []

        for sym in symbols[:300]: # فحص أول 300 عملة لتوفير الوقت
            try:
                bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=50)
                df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
                df = get_indicators(df)
                
                squeezed, div, confirm = detect_squeeze_and_div(df)
                
                # ترتيب القوة (نقاط)
                score = 0
                if squeezed: score += 50
                if div: score += 30
                if confirm: score += 20
                
                if score >= 70:
                    found_signals.append({
                        'sym': sym, 
                        'price': df.iloc[-1]['close'], 
                        'score': score,
                        'width': df.iloc[-1]['bb_width'] * 100
                    })
            except: continue
            await asyncio.sleep(0.05) # حماية API

        # إرسال أفضل 10 فرص
        if found_signals:
            top_10 = sorted(found_signals, key=lambda x: x['score'], reverse=True)[:10]
            report = "🚀 *أفضل 10 فرص (بداية صعود):*\n\n"
            for sig in top_10:
                report += f"• `{sig['sym']}` | قوة: {sig['score']} | ضيق: {sig['width']:.1f}%\n"
            send_telegram_msg(report)
        else:
            send_telegram_msg("⚠️ لم يتم العثور على انفجارات وشيكة حالياً.")

    except Exception as e:
        print(f"Error: {e}")

# ======================== 4. الوظائف العامة والتشغيل ========================

def send_telegram_msg(msg):
    for chat_id in DESTINATIONS:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}, timeout=5)
        except: pass

async def main_loop():
    while True:
        await scan_market()
        await asyncio.sleep(900) # الانتظار 15 دقيقة (15 * 60)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main_loop())
