import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime

# ======================== 1. إعدادات السيرفر والتلجرام ========================
app = Flask('')

@app.route('/')
def home():
    return "🚀 High-Frequency Round Robin Radar | Active"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# متغيرات للتحكم في المناوبة
current_index = 0
BATCH_SIZE = 100 # عدد العملات المفحوصة في كل 5 دقائق لضمان الدقة العالية

# ======================== 2. محرك التحليل (Elite Metrics) ========================

def calculate_metrics(df):
    close = df['close']
    high = df['high']
    low = df['low']
    vol = df['vol']
    
    # الانخناق (Squeeze)
    sma = close.rolling(20).mean()
    std = close.rolling(20).std()
    df['width'] = (4 * std) / (sma + 1e-9)
    
    # RSI
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
    
    # MFI
    tp = (high + low + close) / 3
    mf = tp * vol
    pos_f = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg_f = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    df['mfi'] = 100 - (100 / (1 + (pos_f / (neg_f + 1e-9))))
    
    # السيولة النسبية
    df['rel_vol'] = vol / (vol.rolling(24).mean() + 1e-9)
    
    return df

def evaluate_coin(df):
    last = df.iloc[-1]
    score = 0
    
    if last['width'] < 0.05: score += 50 # ضغط سعري
    if last['mfi'] > 60: score += 25    # دخول سيولة
    if last['rel_vol'] > 2.0: score += 25 # نشاط غير عادي
    if last['rsi'] > 70: score -= 40    # استبعاد المتضخم
    
    return score

# ======================== 3. دورة المسح بنظام المناوبة ========================

async def round_robin_radar():
    global current_index
    
    while True:
        start_time = datetime.now()
        print(f"🔄 دورة مسح جديدة بدأت: {start_time.strftime('%H:%M:%S')}")
        
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s 
                       and s not in ['BTC/USDT', 'ETH/USDT', 'USDC/USDT', 'FDUSD/USDT']]
            
            # اختيار المجموعة الحالية للفحص
            end_index = current_index + BATCH_SIZE
            batch = symbols[current_index:end_index]
            
            # إذا وصلنا لنهاية القائمة، نعود للبداية في الدورة القادمة
            if end_index >= len(symbols):
                current_index = 0
            else:
                current_index = end_index

            all_signals = []

            for sym in batch:
                try:
                    bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=40)
                    df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
                    df = calculate_metrics(df)
                    score = evaluate_coin(df)
                    
                    if score >= 60:
                        all_signals.append({
                            'symbol': sym,
                            'score': score,
                            'price': df.iloc[-1]['close'],
                            'rel_vol': round(df.iloc[-1]['rel_vol'], 1),
                            'width': round(df.iloc[-1]['width'] * 100, 1)
                        })
                except: continue
                await asyncio.sleep(0.02)

            # إرسال أفضل 5 فرص في هذه المجموعة
            top_5 = sorted(all_signals, key=lambda x: x['score'], reverse=True)[:5]

            if top_5:
                report = f"🔥 *أفضل 5 فرص (مجموعة {current_index//BATCH_SIZE})*\n"
                report += f"🕒 {start_time.strftime('%H:%M')} | تحديث 5 دقائق\n\n"
                for i, c in enumerate(top_5, 1):
                    report += (f"{i}. 🚀 *{c['symbol']}*\n"
                               f"   ∟ القوة: `{c['score']}/100` | الضيق: `{c['width']}%`\n"
                               f"   ∟ السعر: `{c['price']:.6f}` | السيولة: `{c['rel_vol']}x`\n\n")
                send_telegram(report)

        except Exception as e:
            print(f"Radar Error: {e}")
        
        # الانتظار لضمان دورة كل 5 دقائق بالضبط
        elapsed = (datetime.now() - start_time).total_seconds()
        await asyncio.sleep(max(0, 300 - elapsed))

def send_telegram(text):
    for cid in DESTINATIONS:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": cid, "text": text, "parse_mode": "Markdown"}, timeout=5)
        except: pass

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(round_robin_radar())
