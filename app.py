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
EXCLUDE_LIST = ['USDT', 'USDC', 'BUSD', 'DAI', 'BEAR', 'BULL', '3L', '3S']

# --- UTILS ---
def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except: pass

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

# --- CALCUL DES INDICATEURS (Version Stable) ---
def analyze_indicators(symbol, exchange):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        # Bollinger
        sma20 = df['close'].rolling(20).mean()
        std20 = df['close'].rolling(20).std()
        df['bb_upper'] = sma20 + (std20 * 2)

        last, prev = df.iloc[-1], df.iloc[-2]
        
        # شروط الدخول (تم تخفيفها قليلاً للتجربة)
        c1 = last['close'] > last['ema200']
        c2 = last['ema9'] > last['ema21']
        c3 = last['close'] > last['bb_upper']
        
        if c1 and c2 and c3:
            return True, last['close']
        return False, 0
    except: return False, 0

# --- RAPPORT HORAIRE AUTOMATIQUE ---
def hourly_report_loop():
    while True:
        try:
            time.sleep(3600) # كل ساعة
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            # الصفقات المفتوحة
            cur.execute("SELECT symbol, entry_price, current_price FROM trades")
            rows = cur.fetchall()
            
            report = "📊 *Rapport de Situation (Horaire)*\n"
            report += "━━━━━━━━━━━━━━━\n"
            report += "*Positions Ouvertes :*\n"
            if not rows:
                report += "_Aucune position active._\n"
            for r in rows:
                pnl = ((float(r['current_price']) - float(r['entry_price'])) / float(r['entry_price'])) * 100
                report += f"• `{r['symbol']}` : {pnl:+.2f}%\n"
            
            send_telegram_msg(report)
            cur.close(); conn.close()
        except: pass

# --- MOTEUR PRINCIPAL ---
async def monitor_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    send_telegram_msg("🚀 *Bot v603 en ligne*\nSurveillance et Rapports activés.")

    while True:
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            # 1. تحديث أسعار الصفقات المفتوحة فوراً
            cur.execute("SELECT * FROM trades")
            active_trades = cur.fetchall()
            for t in active_trades:
                ticker = exchange.fetch_ticker(t['symbol'])
                current_p = float(ticker['last'])
                pnl = ((current_p - float(t['entry_price'])) / float(t['entry_price'])) * 100
                
                # تحديث السعر في القاعدة
                cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (current_p, t['symbol']))
                
                # فحص الإغلاق (TP/SL)
                if pnl >= TP_VAL or pnl <= SL_VAL:
                    reason = "✅ TP" if pnl >= TP_VAL else "❌ SL"
                    cur.execute("INSERT INTO closed_trades (symbol, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s)",
                                (t['symbol'], (pnl/100)*TRADE_INVESTMENT, reason, datetime.now()))
                    cur.execute("DELETE FROM trades WHERE symbol = %s", (t['symbol'],))
                    send_telegram_msg(f"💰 *Ordre Fermé:* {t['symbol']} ({reason}) | PnL: {pnl:.2f}%")
            
            # 2. البحث عن فرص جديدة
            markets = exchange.load_markets()
            symbols = [s for s in markets if '/USDT' in s and not any(ex in s for ex in EXCLUDE_LIST)][:100]
            
            active_symbols = [t['symbol'] for t in active_trades]
            for sym in symbols:
                ready, price = analyze_indicators(sym, exchange)
                if ready and sym not in active_symbols and len(active_symbols) < MAX_VIRTUAL_TRADES:
                    cur.execute("INSERT INTO trades (symbol, entry_price, current_price, investment, open_time) VALUES (%s,%s,%s,%s,%s)",
                                (sym, price, price, TRADE_INVESTMENT, datetime.now()))
                    active_symbols.append(sym)
                    send_telegram_msg(f"🚀 *Nouvel Ordre:* {sym}\n💵 Prix: {price:.6f}")

            conn.commit()
            cur.close(); conn.close()
            await asyncio.sleep(300) # فحص كل 5 دقائق
        except Exception as e:
            print(f"Erreur: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=hourly_report_loop, daemon=True).start()
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
