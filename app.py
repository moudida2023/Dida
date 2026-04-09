import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
import numpy as np
from flask import Flask
from datetime import datetime

# ======================== 1. إعدادات السيرفر والتلجرام ========================
app = Flask('')

@app.route('/')
def home():
    return "🚀 Snowball Elite Radar | Top 5 Mode Active"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# ======================== 2. محرك التحليل الفني (بدون مكتبات خارجية) ========================

def calculate_metrics(df):
    """حساب المقاييس الفنية بدقة عالية"""
    close = df['close']
    high = df['high']
    low = df['low']
    vol = df['vol']
    
    # حساب الانخناق (Squeeze)
    sma = close.rolling(20).mean()
    std = close.rolling(20).std()
    df['width'] = (4 * std) / sma # عرض البولنجر
    
    # حساب RSI
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    
    # حساب تدفق الأموال (MFI)
    tp = (high + low + close) / 3
    mf = tp * vol
    pos_f = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg_f = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    df['mfi'] = 100 - (100 / (1 + (pos_f / neg_f)))
    
    # السيولة النسبية (Relative Volume)
    df['rel_vol'] = vol / vol.rolling(24).mean()
    
    return df

def evaluate_opportunity(df):
    """تقييم الفرصة بناءً على تلاقي المؤشرات"""
    last = df.iloc[-1]
    score = 0
    
    # 1. قوة الانخناق (كلما ضاق النطاق زادت النقاط)
    if last['width'] < 0.04: score += 45
    elif last['width'] < 0.06: score += 25
    
    # 2. قوة السيولة الداخلة (MFI + Rel Vol)
    if last['mfi'] > 60: score += 30
    if last['rel_vol'] > 2.0: score += 25
    
    # 3. فلتر الأمان (تجنب العملات المتضخمة جداً)
    if last['rsi'] > 75: score -= 40 
    
    return score

# ======================== 3. إدارة المسح الدوري (كل 15 دقيقة) ========================

async def start_radar():
    while True:
        try:
            print(f"🔄 جاري المسح الشامل: {datetime.now().strftime('%H:%M')}")
            tickers = await EXCHANGE.fetch_tickers()
            # تصفية أزواج USDT في السبوت
            symbols = [s for s in tickers.keys() if '/USDT' in s 
                       and s not in ['BTC/USDT', 'ETH/USDT', 'USDC/USDT', 'FDUSD/USDT', 'BNB/USDT']]
            
            all_opportunities = []

            for sym in symbols[:350]: # فحص أكثر 350 عملة نشاطاً
                try:
                    bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=50)
                    df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
                    df = calculate_metrics(df)
                    score = evaluate_opportunity(df)
                    
                    if score > 50:
                        all_opportunities.append({
                            'symbol': sym,
                            'score': score,
                            'price': df.iloc[-1]['close'],
                            'vol_spike': round(df.iloc[-1]['rel_vol'], 1),
                            'mfi': round(df.iloc[-1]['mfi'], 1)
                        })
                except: continue
                await asyncio.sleep(0.01)

            # فرز واختيار أفضل 5 عملات فقط
            top_5 = sorted(all_opportunities, key=lambda x: x['score'], reverse=True)[:5]

            if top_5:
                message = f"🌟 *أفضل 5 فرص انفجار (Spot)*\n"
                message += f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                for i, coin in enumerate(top_5, 1):
                    message += (f"{i}. 🔥 *{coin['symbol']}*\n"
                                f"   ∟ القوة: `{coin['score']}/100`\n"
                                f"   ∟ السيولة: `{coin['vol_spike']}x` | MFI: `{coin['mfi']}`\n"
                                f"   ∟ السعر: `{coin['price']:.6f}`\n\n")
                send_msg(message)
            else:
                print("No strong signals found this cycle.")

        except Exception as e:
            print(f"Radar Error: {e}")
        
        await asyncio.sleep(900) # انتظار 15 دقيقة

def send_msg(text):
    for cid in DESTINATIONS:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": cid, "text": text, "parse_mode": "Markdown"}, timeout=5)
        except: pass

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_radar())
