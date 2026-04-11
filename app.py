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

# إعدادات التداول
TP_ACTIVATE = 3.0
TRAILING_DROP = 0.5
SL_VAL = -3.0
TRADE_INVESTMENT = 50.0
EXCLUDE_LIST = ['USDT', 'USDC', 'BUSD', 'DAI', 'BEAR', 'BULL', '3L', '5L', '3S', '5S']

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram: {e}")

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

# --- MOTEUR DE TRADING ---
async def monitor_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    send_telegram_msg("🚀 *Bot v614 Redémarré*\nCorrection des erreurs de syntaxe effectuée.")

    while True:
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            # 1. Gestion des positions
            cur.execute("SELECT * FROM trades")
            active_trades = cur.fetchall()
            
            for t in active_trades:
                try:
                    ticker = exchange.fetch_ticker(t['symbol'])
                    curr_p = float(ticker['last'])
                    entry_p = float(t['entry_price'])
                    pnl = ((curr_p - entry_p) / entry_p) * 100
                    
                    # Trailing TP Logic
                    highest_p = max(float(t['highest_price'] or curr_p), curr_p)
                    cur.execute("UPDATE trades SET current_price=%s, highest_price=%s WHERE symbol=%s", 
                                (curr_p, highest_p, t['symbol']))
                    
                    if pnl <= SL_VAL:
                        terminate_trade(cur, t, curr_p, pnl, "❌ Stop Loss")
                    elif ((highest_p - entry_p) / entry_p) * 100 >= TP_ACTIVATE:
                        if ((highest_p - curr_p) / highest_p) * 100 >= TRAILING_DROP:
                            terminate_trade(cur, t, curr_p, pnl, "💰 Trailing TP")
                except Exception as e:
                    print(f"Error updating {t['symbol']}: {e}")

            # 2. Scanning (Logique simplifiée pour éviter les erreurs)
            # [يمكنك إضافة منطق السكور هنا لاحقاً]
            
            conn.commit()
            cur.close()
            conn.close()
            await asyncio.sleep(60)
            
        except Exception as e:
            print(f"Main Loop Error: {e}")
            await asyncio.sleep(30)

def terminate_trade(cur, t, exit_p, pnl, reason):
    profit_usd = (pnl / 100) * TRADE_INVESTMENT
    cur.execute("INSERT INTO closed_trades (symbol, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s)",
                (t['symbol'], profit_usd, reason, datetime.now()))
    cur.execute("DELETE FROM trades WHERE symbol = %s", (t['symbol'],))
    send_telegram_msg(f"✅ *Ordre Fermé ({reason})*\n🪙 {t['symbol']}\n📈 PnL: {pnl:.2f}%")

@app.route('/')
def home():
    return "Bot v614 is Running"

if __name__ == "__main__":
    # تأكد من تشغيل المحرك في خيط منفصل
    t = threading.Thread(target=lambda: asyncio.run(monitor_engine()))
    t.daemon = True
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
