import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for, request, Response
from datetime import datetime, timedelta
import io
import csv

app = Flask(__name__)

# --- Configuration de la Base de Données ---
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
TAKE_PROFIT = 5.0
STOP_LOSS = -5.0
TRADE_AMOUNT = 50.0  
MAX_TRADES = 20      
status_indicators = {"db": "🔴", "exchange": "🔴", "server": "🟢"}

def get_db_connection():
    """Établit une connexion propre à la base de données"""
    try:
        conn = psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=10)
        status_indicators["db"] = "🟢"
        return conn
    except Exception as e:
        print(f"Erreur de connexion BD: {e}")
        status_indicators["db"] = "🔴"
        return None

def calculate_score(ticker):
    """Calcule le score de 100 points pour filtrer les paires"""
    score = 0
    try:
        # On utilise .get() pour éviter les erreurs si une clé est manquante
        change = float(ticker.get('percentage', 0) or 0)
        volume = float(ticker.get('quoteVolume', 0) or 0)
        last = float(ticker.get('last', 0) or 0)
        high = float(ticker.get('high', 0) or 1)

        # Critère 1: Hausse saine (40 pts)
        if 2.0 <= change <= 8.0: score += 40
        # Critère 2: Volume suffisant (30 pts)
        if volume > 50000: score += 30
        # Critère 3: Proche du plus haut / Momentum (30 pts)
        if last >= high * 0.98: score += 30
    except: pass
    return score

# --- Moteur d'Analyse et d'Enregistrement ---
async def monitor_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            # Récupération des prix
            tickers = await exchange.fetch_tickers()
            status_indicators["exchange"] = "🟢"
            
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                
                # 1. Mise à jour des trades existants dans la BD
                cur.execute("SELECT * FROM trades")
                active_trades = cur.fetchall()
                
                for trade in active_trades:
                    symbol = trade['symbol']
                    if symbol in tickers:
                        current_price = float(tickers[symbol]['last'])
                        entry_price = float(trade['entry_price'])
                        pnl_pct = ((current_price - entry_price) / entry_price) * 100
                        
                        # Mise à jour du prix actuel et des records (Max/Min) dans la BD
                        new_max = max(float(trade['max_asc'] or 0), pnl_pct)
                        new_min = min(float(trade['max_desc'] or 0), pnl_pct)
                        
                        cur.execute("""
                            UPDATE trades 
                            SET current_price = %s, max_asc = %s, max_desc = %s 
                            WHERE symbol = %s
                        """, (current_price, new_max, new_min, symbol))
                
                # 2. Recherche et Enregistrement de nouvelles opportunités (Score 100)
                if len(active_trades) < MAX_TRADES:
                    for symbol, ticker in tickers.items():
                        # Filtrage (USDT uniquement, pas de tokens à effet de levier)
                        if '/USDT' in symbol and all(x not in symbol for x in ['BEAR', 'BULL', '3L', '3S']):
                            if calculate_score(ticker) == 100:
                                # Vérifier si le symbole est déjà enregistré
                                cur.execute("SELECT 1 FROM trades WHERE symbol = %s", (symbol,))
                                if not cur.fetchone():
                                    price = float(ticker['last'])
                                    # INSERTION DANS LA BD
                                    cur.execute("""
                                        INSERT INTO trades (symbol, entry_price, current_price, investment, open_time, max_asc, max_desc) 
                                        VALUES (%s, %s, %s, %s, %s, 0, 0)
                                    """, (symbol, price, price, TRADE_AMOUNT, datetime.now()))
                                    print(f"💰 Opportunité trouvée et enregistrée : {symbol}")

                conn.commit() # Validation des changements
                cur.close()
                conn.close()
            
            await asyncio.sleep(10)
        except Exception as e:
            print(f"Erreur moteur: {e}")
            status_indicators["exchange"] = "🔴"
            await asyncio.sleep(15)

# --- Routes Flask ---
@app.route('/')
def index():
    # Logique d'affichage identique à votre version stable
    return render_template_string("... (Votre HTML) ...")

if __name__ == "__main__":
    # Lancement du moteur dans un thread séparé
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
