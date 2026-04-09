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
    return "🚀 Elite List Radar is Active | Every 5 Mins"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

current_index = 0
BATCH_SIZE = 100 

# ======================== 2. محرك التحليل (قوة الانفجار) ========================

def calculate_elite_metrics(df):
    close = df['close']
    high = df['high']
    low = df['low']
    vol = df['vol']
    
    # حساب الانخناق
    sma = close.rolling(20).mean()
    std = close.rolling(20).std()
    df['width'] = (4 * std) / (sma + 1e-9)
    
    # حساب MFI (تدفق السيولة)
    tp = (high + low + close) / 3
    mf = tp * vol
    pos_f = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg_f = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    df['mfi'] = 100 - (100 / (1 + (pos_f / (neg_f + 1e-9))))
    
    # السيولة النسبية
    df['rel_vol'] = vol / (vol.rolling(24).mean() + 1e-9)
    
    return df

def get_coin_score(df):
    last = df.iloc[-1]
    score = 0
    if last['width'] < 0.05: score += 50
    if last['mfi'] > 55: score += 25
    if last['rel_vol'] > 1.5: score += 25
    return score

# ======================== 3. دورة المسح والتقرير المنظم ========================

async def run_list_radar():
    global current_index
    
    while True:
        start_time = datetime.now()
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s 
                       and s not in ['BTC/USDT', 'ETH/USDT', 'USDC/USDT', 'FDUSD/USDT']]
            
            end_index = current_index + BATCH_SIZE
            batch = symbols[current_index:end_index]
            current_index = 0 if end_index >= len(symbols) else end_index

            found_opportunities = []

            for sym in batch:
                try:
                    # فريم 4 ساعات للاستقرار كما طلبنا
                    bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='4h', limit=50)
                    df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
                    df = calculate_elite_metrics(df)
                    score = get_coin_score(df)
                    
                    if score >= 60:
                        found_opportunities.append({
                            'symbol': sym,
                            'score': score,
                            'price': df.iloc[-1]['close'],
                            'width': round(df.iloc[-1]['width'] * 100, 1)
                        })
                except: continue
                await asyncio.sleep(0.01)

            # ترتيب واختيار أفضل 5
            top_5 = sorted(found_opportunities, key=lambda x: x['score'], reverse=True)[:5]

            if top_5:
                # تصميم الرسالة على شكل قائمة احترافية
                header = f"🏆 *قائمة النخبة | أفضل 5 فرص حالية*\n"
                header += f"⏰ {start_time.strftime('%H:%M')} | فريم 4H | هدف +6%\n"
                header += "───────────────────\n"
                
                list_body = ""
                for i, c in enumerate(top_5, 1):
                    # حساب الأهداف تلقائياً للعرض
                    tp = c['price'] * 1.06
                    list_body += f"{i}️⃣ *{c['symbol']}*\n"
                    list_body += f"   💰 السعر: `{c['price']:.6f}`\n"
                    list_body += f"   📊 القوة: `{c['score']}/100` | الضيق: `{c['width']}%`\n"
                    list_body += f"   🎯 الهدف: `{tp:.6f}`\n"
                    list_body += "───────────────────\n"
                
                send_telegram(header + list_body)

        except Exception as e:
            print(f"Error: {e}")
        
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
    loop.run_until_complete(run_list_radar())
