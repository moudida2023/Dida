import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt
import pandas as pd
import numpy as np
import requests
import time
from flask import Flask
from datetime import datetime, timedelta

app = Flask(__name__)

# --- CONFIGURATION GLOBALE ---
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"

# إعدادات الاستراتيجية
SQUEEZE_THRESHOLD = 0.025 # عتبة ضيق البولنجر
RSI_MAX = 70              # سقف القوة النسبية
VOL_MULTIPLIER = 1.5      # مضاعف حجم التداول
TP_ACTIVATE = 3.0         # تفعيل الملاحقة
TRAILING_DROP = 0.5       # تراجع الإغلاق
SL_VAL = -3.0             # وقف الخسارة
TRADE_INVESTMENT = 50.0
EXCLUDE_LIST = ['USDT', 'USDC', 'BUSD', 'DAI', 'BEAR', 'BULL', '3L', '5L', '3S', '5S']

# --- FUNCTIONS TECHNIQUES ---
def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except: pass

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analyze_full_strategy(symbol, exchange):
    try:
        # جلب بيانات 15 دقيقة
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # المتوسطات والبولنجر
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        sma20 = df['close'].rolling(20).mean()
        std20 = df['close'].rolling(20).std()
        df['bb_upper'] = sma20 + (std20 * 2)
        df['bb_lower'] = sma20 - (std20 * 2)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / sma20
        
        # RSI وحجم التداول
        df['rsi'] = calculate_rsi(df['close'])
        df['vol_avg'] = df['vol'].rolling(window=20).mean()
        
        last, prev = df.iloc[-1], df.iloc[-2]
        score = 0
        
        # 1. الاتجاه (40 نقطة)
        if last['close'] > last['ema200']: score += 40
        
        # 2. الزخم (30 نقطة)
        if last['ema9'] > last['ema21'] and prev['ema9'] <= prev['ema21']: score += 30
        
        # 3. الانفجار (30 نقطة)
        is_sqz = last['bb_width'] < SQUEEZE_THRESHOLD
        is_vol = last['vol'] > (last['vol_avg'] * VOL_MULTIPLIER)
        if last['close'] > last['bb_upper'] and is_vol: score += 30
        
        # فلاتر الأمان
        if last['rsi'] > RSI_MAX: score = 0
        
        return score, last['close'], last['rsi'], last['bb_width']
    except: return 0, 0, 0, 0

# --- ENGINE ---
async def monitor_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    send_telegram_msg("🚀 *Bot v613 Full Strategy Online*\n_Squeeze + RSI + Multi-Scoring_")

    while True:
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            # (إدارة الصفقات المفتوحة مع Trailing TP كما في v610)
            # ...
            
            #
