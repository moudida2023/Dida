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

def get_24h_stats():
    conn = get_db_connection()
    if not conn: return "⚠️ Erreur de connexion BD."
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        last_24h = datetime.now() - timedelta(hours=24)
        cur.execute("SELECT * FROM closed_trades WHERE close_time >= %s", (last_24h,))
        trades = cur.fetchall()
        if not trades: return "📊 *Stats (24h):* Aucun ordre fermé."
        total = len(trades)
        wins = len([t for t in trades if "TP" in t['exit_reason']])
        net_pnl = sum([float(t['pnl']) for t in trades])
        win_rate = (wins / total) * 100
        msg = (f"📊 *Performance (24h)*\n━━━━━━━━━━━━━━━\n✅ Wins: {wins} | ❌ Loss: {total-wins}\n"
               f"📈 Win Rate: *{win_rate:.1f}%*\n💵 Profit Net: *${net_pnl:+.2f}*")
        cur.close(); conn.close()
        return msg
    except: return "⚠️ Erreur calcul stats."

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

# --- MOTEUR DE TRADING ET RADAR ---
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
                
                # 1. إدارة الصفقات المفتوحة
                for t in active_trades:
                    sym = t['symbol']
                    if sym in all_tickers:
                        curr_p = float(all_tickers[sym]['last'])
                        pnl = ((curr_p - float(t['entry_price'])) / float(t['entry_price'])) * 100
                        cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (curr_p, sym))
                        
                        if pnl >= TP_VAL or pnl <= SL_VAL:
                            reason = "✅ TP (+3%)" if pnl >= TP_VAL else "❌ SL (-3%)"
                            p_val = (pnl/100)*TRADE_INVESTMENT
                            cur.execute("INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s,%s,%s)", 
                                        (sym, float(t['entry_price']), curr_p, p_val, reason, datetime.now()))
                            cur.execute("DELETE FROM trades WHERE symbol = %s", (sym,))
                            conn.commit()
                            send_telegram_msg(f"💰 *Fermeture:* {sym} ({reason})\n📊 PnL: {pnl:.2f}%")
                            send_telegram_msg(get_24h_stats())

                # 2. رصد كل العملات (Score 100) وإرسال القائمة
                score_100_list = []
                for i in range(0, len(valid_symbols), 100):
                    chunk = valid_symbols[i:i+100]
                    for sym in chunk:
                        if calculate_score(all_tickers[sym]) == 100:
                            score_100_list.append(sym)
                            
                            # فتح صفقة إذا توفر مكان
                            if len(active_list) < MAX_VIRTUAL_TRADES and sym not in active_list:
                                price = float(all_tickers[sym]['last'])
                                cur.execute("INSERT INTO trades (symbol, entry_price, current_price, investment, open_time) VALUES (%s,%s,%s,%s,%s)",
                                            (sym, price, price, TRADE_INVESTMENT, datetime.now()))
                                active_list.append(sym)
                                send_telegram_msg(f"🚀 *Nouvel Ordre:* {sym}\n💵 Prix: {price:.6f}\n🎯 TP: {price*1.03:.6f} | 🛑 SL: {price*0.97:.6f}")

                # إرسال قائمة العملات المكتشفة
                if score_100_list:
                    list_msg = "📍 *Cryptos avec Score 100 détectées :*\n" + "\n".join([f"• `{s}`" for s in score_100_list])
                    send_telegram_msg(list_msg)

                conn.commit()
                cur.close(); conn.close()
            await asyncio.sleep(30) # فحص كل 30 ثانية لتجنب الرسائل المزعجة
        except: await asyncio.sleep(30)

# --- (Self-Ping et Flask - نفس النسخ السابقة) ---
def self_ping():
    if not RENDER_APP_URL: return
    while True:
        try:
            time.sleep(840)
            requests.get(RENDER_APP_URL, timeout=10)
        except: pass

if __name__ == "__main__":
    threading.Thread(target=self_ping, daemon=True).start()
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
