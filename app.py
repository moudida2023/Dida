import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
import pandas as pd
import pandas_ta as ta
import requests
import time
from flask import Flask, render_template_string
from datetime import datetime, timedelta

app = Flask(__name__)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
RENDER_APP_URL = os.environ.get("RENDER_EXTERNAL_URL")

MAX_VIRTUAL_TRADES = 10
TRADE_INVESTMENT = 50.0
TP_VAL, SL_VAL = 3.0, -3.0
EXCLUDE_LIST = ['USDT', 'USDC', 'BUSD', 'DAI', 'BEAR', 'BULL', '3L', '3S']

# --- TECHNICAL ANALYSIS ENGINE ---
def analyze_indicators(symbol, exchange):
    try:
        # جلب البيانات التاريخية (1H لفلترة الاتجاه و 15M للدخول)
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # 1. EMAs
        df['ema9'] = ta.ema(df['close'], length=9)
        df['ema21'] = ta.ema(df['close'], length=21)
        df['ema200'] = ta.ema(df['close'], length=200)
        
        # 2. Bollinger Bands (20, 2)
        bb = ta.bbands(df['close'], length=20, std=2)
        df = pd.concat([df, bb], axis=1)
        
        # 3. ADX
        adx = ta.adx(df['high'], df['low'], df['close'], length=14)
        df = pd.concat([df, adx], axis=1)
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # --- شروط الدخول (Strategy Logic) ---
        # أ. السعر فوق EMA 200 (اتجاه صاعد)
        condition_trend = last['close'] > last['ema200']
        
        # ب. تقاطع EMA 9 فوق EMA 21
        condition_ema_cross = last['ema9'] > last['ema21'] and prev['ema9'] <= prev['ema21']
        
        # ج. اختراق البولينجر العلوي (Bollinger Breakout)
        condition_bb = last['close'] > last['BBU_20_2.0']
        
        # د. قوة الترند (ADX > 25)
        condition_adx = last['ADX_14'] > 25
        
        # هـ. زيادة الحجم (أكبر من متوسط آخر 10 شموع)
        condition_vol = last['vol'] > df['vol'].tail(10).mean()

        if condition_trend and condition_ema_cross and condition_adx and condition_vol:
            return True, last['close']
        return False, 0
    except:
        return False, 0

# --- MOTEUR DE TRADING ---
async def monitor_engine():
    # استخدام CCXT العادي للتحليل الفني (REST API أسرع لجلب البيانات التاريخية)
    exchange = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            markets = exchange.load_markets()
            valid_symbols = [s for s in markets if '/USDT' in s and not any(ex in s for ex in EXCLUDE_LIST)]
            valid_symbols = valid_symbols[:200] # تقليل العدد لضمان سرعة جلب الـ OHLCV
            
            conn = psycopg2.connect(DB_URL, sslmode='require')
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            # 1. تحديث الصفقات الحالية (Real-time Prices)
            cur.execute("SELECT * FROM trades")
            active_trades = cur.fetchall()
            for t in active_trades:
                ticker = exchange.fetch_ticker(t['symbol'])
                curr_p = float(ticker['last'])
                pnl = ((curr_p - float(t['entry_price'])) / float(t['entry_price'])) * 100
                cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (curr_p, t['symbol']))
                
                if pnl >= TP_VAL or pnl <= SL_VAL:
                    # منطق الإغلاق (كما في النسخ السابقة)
                    close_trade(cur, t, curr_p, pnl)

            # 2. المسح الفني لفتح صفقات جديدة
            active_list = [t['symbol'] for t in active_trades]
            found_opportunities = []

            for sym in valid_symbols:
                is_ready, price = analyze_indicators(sym, exchange)
                if is_ready:
                    found_opportunities.append(sym)
                    if len(active_list) < MAX_VIRTUAL_TRADES and sym not in active_list:
                        open_trade(cur, sym, price)
                        active_list.append(sym)

            if found_opportunities:
                send_telegram_msg(f"🔍 *Signal Détecté (BB + EMA + ADX):*\n" + "\n".join([f"• `{s}`" for s in found_opportunities]))

            conn.commit()
            cur.close(); conn.close()
            await asyncio.sleep(60) # التحليل الفني يحتاج وقت (مرة كل دقيقة)
        except Exception as e:
            print(f"Engine Error: {e}")
            await asyncio.sleep(30)

def open_trade(cur, sym, price):
    cur.execute("INSERT INTO trades (symbol, entry_price, current_price, investment, open_time) VALUES (%s,%s,%s,%s,%s)",
                (sym, price, price, TRADE_INVESTMENT, datetime.now()))
    send_telegram_msg(f"🚀 *Achat (Filtre Technique)*\n🪙 {sym}\n💵 Prix: {price:.6f}\n📊 Strat: Trend-Following")

def close_trade(cur, t, curr_p, pnl):
    reason = "✅ TP" if pnl >= TP_VAL else "❌ SL"
    p_val = (pnl/100)*TRADE_INVESTMENT
    cur.execute("INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s,%s,%s)", 
                (t['symbol'], float(t['entry_price']), curr_p, p_val, reason, datetime.now()))
    cur.execute("DELETE FROM trades WHERE symbol = %s", (t['symbol'],))
    send_telegram_msg(f"💰 *Fermeture:* {t['symbol']}\n📈 PnL: {pnl:.2f}% ({reason})")

def send_telegram_msg(message):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                       json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})
    except: pass

# --- (Flask & Self-Ping as before) ---
if __name__ == "__main__":
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
