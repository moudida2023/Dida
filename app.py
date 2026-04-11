import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
import requests
from flask import Flask, render_template_string
from datetime import datetime

app = Flask(__name__)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"

MAX_VIRTUAL_TRADES = 10
TRADE_INVESTMENT = 50.0
TP_VAL = 3.0
SL_VAL = -2.0
EXCLUDE_LIST = ['USDT', 'USDC', 'BUSD', 'DAI', 'BEAR', 'BULL', '3L', '3S']

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=5)
    except: pass

def get_db_connection():
    try:
        return psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=10)
    except: return None

def calculate_score(ticker):
    score = 0
    try:
        change = float(ticker.get('percentage', 0) or 0)
        vol = float(ticker.get('quoteVolume', 0) or 0)
        last = float(ticker.get('last', 0) or 0)
        high = float(ticker.get('high', 0) or 1)
        if 2.0 <= change <= 8.0: score += 40
        if vol > 50000: score += 30
        if last >= high * 0.98: score += 30
    except: pass
    return score

# --- MOTEUR DE RECHERCHE ET TRADING ---
async def monitor_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            all_tickers = await exchange.fetch_tickers()
            valid_symbols = [s for s, t in all_tickers.items() if '/USDT' in s and not any(ex in s for ex in EXCLUDE_LIST)]
            valid_symbols = valid_symbols[:500]
            
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute("SELECT * FROM trades")
                active_trades = cur.fetchall()
                active_list = [t['symbol'] for t in active_trades]
                
                for t in active_trades:
                    sym = t['symbol']
                    if sym in all_tickers:
                        curr_p = float(all_tickers[sym]['last'])
                        pnl = ((curr_p - float(t['entry_price'])) / float(t['entry_price'])) * 100
                        cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (curr_p, sym))
                        
                        if pnl >= TP_VAL or pnl <= SL_VAL:
                            reason = "✅ TP" if pnl >= TP_VAL else "❌ SL"
                            p_val = (pnl/100)*TRADE_INVESTMENT
                            cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                                           VALUES (%s,%s,%s,%s,%s,%s)""", 
                                        (sym, float(t['entry_price']), curr_p, p_val, reason, datetime.now()))
                            cur.execute("DELETE FROM trades WHERE symbol = %s", (sym,))
                            send_telegram_msg(f"💰 *Fermeture:* {sym} ({reason}) | PnL: {pnl:.2f}%")

                for i in range(0, len(valid_symbols), 100):
                    for sym in valid_symbols[i:i+100]:
                        if calculate_score(all_tickers[sym]) == 100:
                            if len(active_list) < MAX_VIRTUAL_TRADES and sym not in active_list:
                                price = float(all_tickers[sym]['last'])
                                cur.execute("INSERT INTO trades (symbol, entry_price, current_price, investment, open_time) VALUES (%s,%s,%s,%s,%s)",
                                            (sym, price, price, TRADE_INVESTMENT, datetime.now()))
                                active_list.append(sym)
                                send_telegram_msg(f"🚀 *Nouveau Score 100:* {sym}\n✅ Enregistré en BD")

                conn.commit()
                cur.close(); conn.close()
            await asyncio.sleep(20)
        except: await asyncio.sleep(30)

# --- INTERFACE WEB (FLASK) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Trading Bot Dashboard</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #0f0f0f; color: #e0e0e0; text-align: center; margin: 0; padding: 20px; }
        .container { max-width: 1100px; margin: auto; }
        h1, h2 { color: #00ffcc; text-transform: uppercase; letter-spacing: 2px; }
        table { width: 100%; margin: 20px 0; border-collapse: collapse; background: #1a1a1a; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        th, td { padding: 15px; border-bottom: 1px solid #333; text-align: center; }
        th { background: #252525; color: #00ffcc; font-size: 0.9em; }
        tr:hover { background: #222; }
        .profit { color: #00ff66; font-weight: bold; }
        .loss { color: #ff3366; font-weight: bold; }
        .badge { padding: 4px 8px; border-radius: 4px; font-size: 0.8em; font-family: monospace; }
        .tp { background: #004d26; color: #00ff66; border: 1px solid #00ff66; }
        .sl { background: #4d0019; color: #ff3366; border: 1px solid #ff3366; }
        .status-bar { display: flex; justify-content: space-around; background: #1a1a1a; padding: 15px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #333; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 Crypto Bot Dashboard</h1>
        
        <div class="status-bar">
            <div>🟢 Status: <b>Active</b></div>
            <div>💰 Invest/Order: <b>${{ trade_amount }}</b></div>
            <div>🎯 Target: <b class="profit">+3%</b> /
