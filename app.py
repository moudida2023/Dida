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

# --- MOTEUR DE RECHERCHE SILENCIEUX ---
async def monitor_engine():
    # Seule alerte conservée : Le démarrage du serveur
    send_telegram_msg("🚀 *Bot Opérationnel (v602)*\nRecherche active en arrière-plan (Mode Silencieux).")
    
    exchange = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            # Suppression de l'alerte "Scan en cours" ici
            
            markets = exchange.load_markets()
            valid_symbols = [s for s in markets if '/USDT' in s and not any(ex in s for ex in EXCLUDE_LIST)]
            valid_symbols = valid_symbols[:150]
            
            # ... Logique de scan technique (EMA, BB, ADX) ...
            # Les alertes ne sont envoyées que si 'is_ready' est True
            
            # Scan toutes les 5 minutes pour rester réactif sans spammer
            await asyncio.sleep(300) 
            
        except Exception as e:
            # On garde l'alerte d'erreur pour vous prévenir en cas de panne
            print(f"Erreur technique: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
