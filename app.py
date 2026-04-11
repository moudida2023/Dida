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

# --- CONFIGURATION ---
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"

MAX_VIRTUAL_TRADES = 10
TRADE_INVESTMENT = 50.0
TP_VAL, SL_VAL = 3.0, -3.0
# قائمة الاستبعاد المحسنة (v605)
EXCLUDE_LIST = ['USDT', 'USDC', 'BUSD', 'DAI', 'BEAR', 'BULL', '3L', '5L', '3S', '5S']

# --- UTILS ---
def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except: pass

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

# --- CALCUL DES INDICATEURS (Version Stable sans pandas_ta) ---
def analyze_indicators(symbol, exchange):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # EMA 9, 21, 200
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        # Bollinger Bands
        sma20 = df['close'].rolling(20).mean()
        std20 = df['close'].rolling(20).std()
        df['bb_upper'] = sma20 + (std20 * 2)

        last, prev = df.iloc[-1], df.iloc[-2]
        
        # استراتيجية الدخول
        c1 = last['close'] > last['ema200'] # ترند صاعد
        c2 = last['ema9'] > last['ema21'] and prev['ema9'] <= prev['ema21'] # تقاطع ذهبي
        c3 = last['close'] > last['bb_upper'] # انفجار سعري
        
        if c1 and c2 and c3:
            return True, last['close']
        return False, 0
    except: return False, 0

# --- RAPPORT HORAIRE ---
def hourly_report_loop():
    while True:
        try:
            time.sleep(3600) # كل ساعة
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            # جلب الصفقات المفتوحة
            cur.execute("SELECT symbol, entry_price, current_price FROM trades")
            open_rows = cur.fetchall()
            
            # جلب ملخص آخر ساعة من الصفقات المغلقة
            last_hour = datetime.now() - timedelta(hours=1)
            cur.execute("SELECT symbol, pnl FROM closed_trades WHERE close_time >= %s", (last_hour,))
            closed_rows = cur.fetchall()
            
            msg = "📊 *RAPPORT HORAIRE COMPLET*\n━━━━━━━━━━━━━━━\n"
            msg += "*Positions Actives :*\n"
            if not open_rows: msg += "_Aucune_\n"
            for r in open_rows:
                pnl = ((float(r['current_price']) - float(r['entry_price'])) / float(r['entry_price'])) * 100
                msg += f"• `{r['symbol']}` : {pnl:+.2f}%\n"
            
            msg += "\n*Fermées (Dernière Heure) :*\n"
            if not closed_
