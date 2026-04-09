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
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# إعدادات المحفظة
INITIAL_BALANCE = 500.0
CURRENT_BALANCE = 500.0
MAX_TRADES = 10
TRADE_AMOUNT = 50.0 
OPEN_TRADES = {}     
CLOSED_TRADES = []   
PREVIOUS_SIGNALS = set()

# ======================== 2. محرك التحليل المطور (نقطة الدخول) ========================

def calculate_advanced_metrics(df):
    close = df['close']
    # 1. البولنجر باند والضيق
    sma = close.rolling(20).mean()
    std = close.rolling(20).std()
    df['upper_bb'] = sma + (2 * std)
    df['width'] = (4 * std) / (sma + 1e-9)
    
    # 2. فلتر الاتجاه العام (EMA 200)
    df['ema_200'] = close.ewm(span=200, adjust=False).mean()
    
    # 3. فلتر حجم التداول (Volume Spike)
    df['vol_avg_10'] = df['vol'].rolling(window=10).mean()
    
    # 4. تدفق السيولة (MFI)
    tp = (df['high'] + df['low'] + close) / 3
    mf = tp * df['vol']
    pos_f = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg_f = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    df['mfi'] = 100 - (100 / (1 + (pos_f / (neg_f + 1e-9))))
    
    return df

def check_entry_signal(df):
    """تحديد ما إذا كانت الشمعة الحالية هي نقطة دخول مثالية"""
    last = df.iloc[-1]
    
    # الشروط الفنية للدخول:
    is_uptrend = last['close'] > last['ema_200']             # فوق متوسط 200
    is_squeezed = last['width'] < 0.05                      # حالة انضغاط
    has_volume = last['vol'] > (last['vol_avg_10'] * 1.2)   # حجم تداول أعلى بـ 20% من المتوسط
    has_money_flow = last['mfi'] > 55                       # سيولة داخلة
    
    if is_uptrend and is_squeezed and has_volume and has_money_flow:
        return True, last['close']
    return False, None

# ======================== 3. منطق التداول والتقارير ========================

async def scan_and_enter():
    global PREVIOUS_SIGNALS, CURRENT_BALANCE
    current_index = 0
    while True:
        start_time = datetime.now()
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and s not in ['BTC/USDT', 'ETH/USDT']]
            
            batch = symbols[current_index : current_index + 100]
            current_index = 0 if current_index + 100 >= len(symbols) else current_index + 100
            
            current_cycle_signals = []
            for sym in batch:
                if len(OPEN_TRADES) >= MAX_TRADES: break
                if sym in OPEN_TRADES: continue
                
                try:
                    bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='4h', limit=200)
                    df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
                    df = calculate_advanced_metrics(df)
                    
                    can_enter, entry_price = check_entry_signal(df)
                    
                    if can_enter:
                        # التأكد من ثبات الإشارة (Persistence)
                        if sym in PREVIOUS_SIGNALS:
                            # تنفيذ نقطة الدخول
                            OPEN_TRADES[sym] = {'entry': entry_price, 'current': entry_price, 'time': datetime.now()}
                            CURRENT_BALANCE -= TRADE_AMOUNT
                            send_telegram(f"🚀 *تم الدخول في صفقة (نقطة دخول مؤكدة)*\n💎 العملة: `{sym}`\n💰 السعر: `{entry_price:.6f}`\n📈 الاتجاه: `صاعد (فوق EMA200)`\n📍 الرصيد المتبقي: `{CURRENT_BALANCE:.2f}$`")
                        current_cycle_signals.append(sym)
                except: continue
                await asyncio.sleep(0.01)
            PREVIOUS_SIGNALS = set(current_cycle_signals)
        except: pass
        await asyncio.sleep(300)

# (تكملة الكود من دوال المراقبة والتقارير السابقة تبقى كما هي)
# ... [دوال trade_monitor و generate_hourly_report و send_telegram]
