import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import os
from flask import Flask
from datetime import datetime, timedelta

# ======================== 1. الإعدادات ========================
# ملاحظة: تأكد من مراسلة البوت أولاً بـ /start لتتمكن من استقبال الرسائل
TELEGRAM_TOKEN = '8603477836:AAGG6Outg3Z9vBI-NjWQ3ALJroh_Cye3l2c'
TELEGRAM_CHAT_ID = '5067771509'

# الربط العام
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# إعدادات المحفظة الافتراضية
VIRTUAL_BALANCE = 1000.0
portfolio = {"open_trades": {}}
trade_history = {}
closed_trades_history = []
current_market_mode = "NORMAL"
daily_start_balance = 1000.0

# ======================== 2. دالة الإرسال (المحسنة) ========================
def send_telegram_msg(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"Telegram Error: {response.text}")
    except Exception as e:
        print(f"Connection Error to Telegram: {e}")

# ======================== 3. وحدة ذكاء السوق ========================
async def get_market_regime():
    global current_market_mode
    try:
        tickers = await EXCHANGE.fetch_tickers()
        symbols = [s for s in tickers.keys() if '/USDT' in s]
        top_50 = sorted(symbols, key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:50]
        up_count = sum(1 for sym in top_50 if tickers[sym].get('percentage', 0) > 0.5)
        
        if up_count <= 10:
            current_market_mode = "PROTECT"
            return {"mode": "PROTECT", "max_trades": 3, "vol_mult": 6.0, "mfi_limit": 70, "count": 50}
        elif up_count >= 35:
            current_market_mode = "ULTRA_BULL"
            return {"mode": "ULTRA_BULL", "max_trades": 20, "vol_mult": 1.8, "mfi_limit": 40, "count": 400}
        else:
            current_market_mode = "NORMAL"
            return {"mode": "NORMAL", "max_trades": 10, "vol_mult": 3.0, "mfi_limit": 50, "count": 250}
    except Exception as e:
        print(f"Market Regime Error: {e}")
        return {"mode": "NORMAL", "max_trades": 10, "vol_mult": 3.0, "mfi_limit": 50, "count": 250}

# ======================== 4. المؤشرات الفنية ========================
def calculate_indicators(df):
    close = df['close']
    df['ema9'] = close.ewm(span=9, adjust=False).mean()
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    tp = (df['high'] + df['low'] + close) / 3
    mf = tp * df['vol']
    positive_mf = mf.where(close > close.shift(1), 0).rolling(14).sum()
    negative_mf = mf.where(close < close.shift(1), 0).rolling(14).sum()
    df['mfi'] = 100 - (100 / (1 + (positive_mf / negative_mf)))
    return df

# ======================== 5. مسح السوق والدخول ========================
async def scan_market():
    global VIRTUAL_BALANCE
    regime = await get_market_reg
