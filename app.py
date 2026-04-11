import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
import requests
import time
from flask import Flask, render_template_string
from datetime import datetime

app = Flask(__name__)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
# ضع رابط السيرفر الخاص بك هنا (مثال: https://my-bot.onrender.com)
RENDER_APP_URL = os.environ.get("RENDER_EXTERNAL_URL") 

MAX_VIRTUAL_TRADES = 10
TRADE_INVESTMENT = 50.0
TP_VAL = 3.0
SL_VAL = -2.0
EXCLUDE_LIST = ['USDT', 'USDC', 'BUSD', 'DAI', 'BEAR', 'BULL', '3L', '3S']

# --- وظيفة Self-Ping لمنع السيرفر من النوم ---
def self_ping():
    """ترسل طلباً للسيرفر كل 14 دقيقة لابقائه مستيقظاً"""
    if not RENDER_APP_URL:
        print("⚠️ RENDER_EXTERNAL_URL non défini. Le self-ping ne s'activera pas.")
        return
    
    print(f"🚀 Self-ping activé pour: {RENDER_APP_URL}")
    while True:
        try:
            # الانتظار لمدة 14 دقيقة (Render ينام بعد 15 دقيقة خمول)
            time.sleep(840) 
            response = requests.get(RENDER_APP_URL, timeout=10)
            print(f"📡 Self-ping envoyé à {datetime.now().strftime('%H:%M:%S')} | Status: {response.status_code}")
        except Exception as e:
            print(f"❌ Erreur Self-ping: {e}")

# --- الوظائف التقنية (نفس الكود السابق) ---
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

# --- المحرك الرئيسي ---
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
                
                # تحديث الصفقات وإغلاقها
                for t in active_trades:
                    sym = t['symbol']
                    if sym in all_tickers:
                        curr_p = float(all_tickers[sym]['last'])
                        pnl = ((curr_p - float(t['entry_price'])) / float(t['entry_price'])) * 100
                        cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (curr_p, sym))
                        
                        if pnl >= TP_VAL or pnl <= SL_VAL:
                            reason = "✅ TP" if pnl >= TP_VAL else "❌ SL"
                            p_val = (pnl/100)*TRADE_INVESTMENT
                            cur.execute("INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s,%s,%s)", 
                                        (sym, float(t['entry_price']), curr_p, p_val, reason, datetime.now()))
                            cur.execute("DELETE FROM trades WHERE symbol = %s", (sym,))
                            send_telegram_msg(f"💰 *Fermeture:* {sym} ({reason}) | PnL: {pnl:.2f}%")

                # البحث عن سكور 100
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

# --- واجهة الويب (نفس التصميم الاحترافي v587) ---
@app.route('/')
def index():
    conn = get_db_connection()
    active_trades, closed_trades = [], []
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        active_trades = cur.fetchall()
        cur.execute("SELECT * FROM closed_trades ORDER BY close_time DESC LIMIT 20")
        closed_trades = cur.fetchall()
        cur.close(); conn.close()
    return render_template_string("... (استخدم قالب HTML من v587 هنا) ...", 
                                  active_trades=active_trades, 
                                  closed_trades=closed_trades, 
                                  trade_amount=TRADE_INVESTMENT,
                                  now=datetime.now().strftime("%H:%M:%S"))

if __name__ == "__main__":
    # 1. تشغيل وظيفة Self-Ping في خلفية السيرفر
    threading.Thread(target=self_ping, daemon=True).start()
