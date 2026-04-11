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

# Paramètres de Trading
TP_ACTIVATE = 3.0   # Activation Trailing à 3%
TRAILING_DROP = 0.5 # Sortie si baisse de 0.5% depuis le sommet
SL_VAL = -3.0       # Stop Loss fixe
TRADE_INVESTMENT = 50.0
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

# --- FONCTION RAPPORT HORAIRE (CHAQUE HEURE) ---
def hourly_report_loop():
    """Envoie un résumé des ordres ouverts et fermés chaque heure"""
    while True:
        try:
            # Attendre 1 heure (3600 secondes)
            time.sleep(3600)
            
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            # 1. Récupérer les ordres ouverts
            cur.execute("SELECT symbol, entry_price, current_price FROM trades")
            open_trades = cur.fetchall()
            
            # 2. Récupérer les ordres fermés dans la dernière heure
            last_hour = datetime.now() - timedelta(hours=1)
            cur.execute("SELECT symbol, pnl, exit_reason FROM closed_trades WHERE close_time >= %s", (last_hour,))
            closed_trades = cur.fetchall()
            
            msg = "📊 *RAPPORT HORAIRE DES TRADES*\n━━━━━━━━━━━━━━━\n"
            
            # Section Ordres Ouverts
            msg += "📍 *Positions Actives :*\n"
            if not open_trades:
                msg += "_Aucune position ouverte._\n"
            else:
                for t in open_trades:
                    pnl = ((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * 100
                    msg += f"• `{t['symbol']}` : {pnl:+.2f}%\n"
            
            # Section Ordres Fermés
            msg += "\n✅ *Fermés (Dernière Heure) :*\n"
            if not closed_trades:
                msg += "_Aucun ordre fermé._\n"
            else:
                for c in closed_trades:
                    msg += f"• `{c['symbol']}` : {float(c['pnl']):+.2f}$ ({c['exit_reason']})\n"
            
            send_telegram_msg(msg)
            cur.close(); conn.close()
        except Exception as e:
            print(f"Erreur Rapport: {e}")

# --- MOTEUR DE TRADING (MONITOR ENGINE) ---
async def monitor_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    send_telegram_msg("🚀 *Bot v610 Online*\n_Rapports Horaires & Trailing TP activés._")

    while True:
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            # 1. Gestion du Trailing TP et Sorties
            cur.execute("SELECT * FROM trades")
            for t in cur.fetchall():
                ticker = exchange.fetch_ticker(t['symbol'])
                curr_p = float(ticker['last'])
                entry_p = float(t['entry_price'])
                pnl = ((curr_p - entry_p) / entry_p) * 100
                
                # Update Highest Price pour le Trailing
                highest_p = max(float(t['highest_price'] or curr_p), curr_p)
                cur.execute("UPDATE trades SET current_price=%s, highest_price=%s WHERE symbol=%s", 
                            (curr_p, highest_p, t['symbol']))
                
                # Logique de sortie
                if pnl <= SL_VAL:
                    terminate_trade(cur, t, curr_p, pnl, "❌ Stop Loss")
                elif ((highest_p - entry_p) / entry_p) * 100 >= TP_ACTIVATE:
                    if ((highest_p - curr_p) / highest_p) * 100 >= TRAILING_DROP:
                        terminate_trade(cur, t, curr_p, pnl, "💰 Trailing TP")

            # 2. Scan de nouvelles opportunités (Scoring 100/100)
            # ... (Votre logique de scan ici) ...

            conn.commit()
            cur.close(); conn.close()
            await asyncio.sleep(60) 
        except: await asyncio.sleep(30)

def terminate_trade(cur, t, exit_p, pnl, reason):
    profit_usd = (pnl / 100) * TRADE_INVESTMENT
    cur.execute("INSERT INTO closed_trades (symbol, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s)",
                (t['symbol'], profit_usd, reason, datetime.now()))
    cur.execute("DELETE FROM trades WHERE symbol = %s", (t['symbol'],))
    send_telegram_msg(f"✅ *Ordre Fermé ({reason})*\n🪙 {t['symbol']}\n📈 PnL: {pnl:.2f}%")

@app.route('/')
def home(): return "Bot Active v610"

if __name__ == "__main__":
    # Démarrer le rapport horaire dans un thread séparé
    threading.Thread(target=hourly_report_loop, daemon=True).start()
    # Démarrer le moteur de trading
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
