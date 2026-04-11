import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
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
TP_VAL = 3.0   
SL_VAL = -3.0  
EXCLUDE_LIST = ['USDT', 'USDC', 'BUSD', 'DAI', 'BEAR', 'BULL', '3L', '3S']

# --- UTILS ---
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

# --- FONCTION DE CALCUL DES STATISTIQUES 24H ---
def get_24h_stats():
    conn = get_db_connection()
    if not conn: return "Erreur de connexion BD pour les stats."
    
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        last_24h = datetime.now() - timedelta(hours=24)
        
        cur.execute("SELECT * FROM closed_trades WHERE close_time >= %s", (last_24h,))
        trades = cur.fetchall()
        
        if not trades:
            return "📊 *Stats (24h):* Aucun ordre fermé."
        
        total = len(trades)
        wins = len([t for t in trades if "TP" in t['exit_reason']])
        net_pnl = sum([float(t['pnl']) for t in trades])
        win_rate = (wins / total) * 100
        
        msg = (
            f"📊 *Performance (Dernières 24h)*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"✅ Ordres Gagnants: {wins}\n"
            f"❌ Ordres Perdants: {total - wins}\n"
            f"📈 Win Rate: *{win_rate:.1f}%*\n"
            f"💵 Profit Net: *${net_pnl:+.2f}*\n"
            f"📦 Total Traité: {total}"
        )
        cur.close(); conn.close()
        return msg
    except Exception as e:
        return f"⚠️ Erreur stats: {e}"

# --- MOTEUR DE TRADING ---
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
                            reason = "✅ TP (+3%)" if pnl >= TP_VAL else "❌ SL (-3%)"
                            p_val = (pnl/100)*TRADE_INVESTMENT
                            
                            # Insertion de l'ordre fermé
                            cur.execute("INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s,%s,%s)", 
                                        (sym, float(t['entry_price']), curr_p, p_val, reason, datetime.now()))
                            cur.execute("DELETE FROM trades WHERE symbol = %s", (sym,))
                            conn.commit() # Commit avant les stats
                            
                            # Alerte de fermeture
                            send_telegram_msg(f"💰 *Fermeture:* {sym}\n📊 PnL: {pnl:.2f}% ({reason})")
                            
                            # --- AJOUT: Rapport 24h après chaque fermeture ---
                            stats_report = get_24h_stats()
                            send_telegram_msg(stats_report)

                # Logic d'ouverture (inchangé)
                for i in range(0, len(valid_symbols), 100):
                    for sym in valid_symbols[i:i+100]:
                        # calculate_score... (votre logique habituelle)
                        pass 

                conn.commit()
                cur.close(); conn.close()
            await asyncio.sleep(20)
        except: await asyncio.sleep(30)

# --- (Self-Ping et Flask inchangés) ---
if __name__ == "__main__":
    # threading.Thread... (v590)
    app.run(host='0.0.0.0', port=10000)
