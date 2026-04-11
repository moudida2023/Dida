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
from datetime import datetime

app = Flask(__name__)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except: pass

# --- وظيفة التحقق من الاتصال بالخدمات ---
def check_connectivity():
    status_report = "⚙️ *Vérification des Connexions...*\n━━━━━━━━━━━━━━━\n"
    
    # 1. التحقق من Gate.io
    try:
        exchange = ccxt.gateio()
        exchange.fetch_status()
        status_report += "✅ Gate.io : *Connecté*\n"
    except Exception as e:
        status_report += f"❌ Gate.io : *Erreur* ({str(e)[:30]})\n"

    # 2. التحقق من قاعدة البيانات
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require', connect_timeout=5)
        conn.close()
        status_report += "✅ Database : *Connectée*\n"
    except Exception as e:
        status_report += f"❌ Database : *Erreur* ({str(e)[:30]})\n"

    status_report += "━━━━━━━━━━━━━━━\n🚀 *Démarrage du Scan Technique...*"
    send_telegram_msg(status_report)

# --- (نفس وظائف الحساب اليدوي للمؤشرات من v598) ---
def calculate_ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def calculate_adx(df, length=14):
    # (العملية الرياضية كما في النسخة السابقة)
    plus_dm = df['high'].diff(); minus_dm = df['low'].diff()
    plus_dm[plus_dm < 0] = 0; minus_dm[minus_dm > 0] = 0
    tr = pd.concat([(df['high'] - df['low']), 
                    abs(df['high'] - df['close'].shift(1)), 
                    abs(df['low'] - df['close'].shift(1))], axis=1).max(axis=1)
    atr = tr.rolling(length).mean()
    plus_di = 100 * (plus_dm.rolling(length).mean() / atr)
    minus_di = 100 * (abs(minus_dm).rolling(length).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    return dx.rolling(length).mean()

async def monitor_engine():
    # فحص الاتصال قبل البدء
    check_connectivity()
    
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            # منطق البحث والتحليل (EMA + BB + ADX)
            # ...
            await asyncio.sleep(60)
        except Exception as e:
            print(f"Loop Error: {e}")
            await asyncio.sleep(30)

@app.route('/')
def index():
    return f"Bot v600 Active - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

if __name__ == "__main__":
    # تشغيل المحرك
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    
    # تشغيل Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
