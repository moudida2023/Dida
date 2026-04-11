import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
import requests
from flask import Flask
from datetime import datetime

app = Flask(__name__)

# --- إعداداتك الفنية ---
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"

# الإعدادات الفنية للتداول الافتراضي
MAX_VIRTUAL_TRADES = 10
TRADE_INVESTMENT = 50.0
TP_PCT = 3.0
SL_PCT = -2.0
EXCLUDE_LIST = ['USDT', 'USDC', 'BUSD', 'DAI', 'BEAR', 'BULL', '3L', '3S']

# حالة الاتصال الأولي
db_initialized = False

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=5)
    except: pass

def get_db_connection():
    global db_initialized
    try:
        conn = psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=10)
        if not db_initialized:
            send_telegram_msg("✅ *Connexion avec succès* (Base de données connectée)")
            db_initialized = True
        return conn
    except Exception as e:
        print(f"Erreur DB: {e}")
        return None

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

# --- المحرك الرئيسي المحسن ---
async def monitor_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            all_tickers = await exchange.fetch_tickers()
            # تصفية وفحص أول 500 عملة
            valid_symbols = [s for s, t in all_tickers.items() if '/USDT' in s and not any(ex in s for ex in EXCLUDE_LIST)]
            valid_symbols = valid_symbols[:500]
            
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                
                # 1. تحديث الصفقات في الـ BD
                cur.execute("SELECT * FROM trades")
                active_trades = cur.fetchall()
                active_list = [t['symbol'] for t in active_trades]
                
                for t in active_trades:
                    sym = t['symbol']
                    if sym in all_tickers:
                        curr_p = float(all_tickers[sym]['last'])
                        pnl = ((curr_p - float(t['entry_price'])) / float(t['entry_price'])) * 100
                        cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (curr_p, sym))
                        
                        if pnl >= TP_PCT or pnl <= SL_PCT:
                            reason = "✅ TP +3%" if pnl >= TP_PCT else "❌ SL -2%"
                            p_val = (pnl / 100) * TRADE_INVESTMENT
                            cur.execute("INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s,%s,%s)", 
                                        (sym, float(t['entry_price']), curr_p, p_val, reason, datetime.now()))
                            cur.execute("DELETE FROM trades WHERE symbol = %s", (sym,))
                            send_telegram_msg(f"💰 *Fermeture d'ordre*\n🪙 {sym}\n📊 Résultat: {reason}\n💵 PnL: ${p_val:.2f}")

                # 2. البحث عن سكور 100 والحفظ مع تأكيد الإضافة
                all_found_100 = []
                for i in range(0, len(valid_symbols), 100):
                    chunk = valid_symbols[i:i+100]
                    for sym in chunk:
                        if calculate_score(all_tickers[sym]) == 100:
                            all_found_100.append(sym)
                            if len(active_list) < MAX_VIRTUAL_TRADES and sym not in active_list:
                                price = float(all_tickers[sym]['last'])
                                
                                # محاولة الإضافة في قاعدة البيانات
                                try:
                                    cur.execute("""
                                        INSERT INTO trades (symbol, entry_price, current_price, investment, open_time, max_asc, max_desc) 
                                        VALUES (%s, %s, %s, %s, %s, 0, 0)
                                    """, (sym, price, price, TRADE_INVESTMENT, datetime.now()))
                                    
                                    # إرسال تنبيه في حال نجاح الإضافة فقط
                                    send_telegram_msg(f"🚀 *Nouvel ordre (Score 100)*\n🪙 Symbole: {sym}\n💵 Prix: {price}\n✅ *Données enregistrées avec succès dans la BD*")
                                    active_list.append(sym)
                                except Exception as db_err:
                                    send_telegram_msg(f"⚠️ *Erreur d'enregistrement BD* pour {sym}: {db_err}")

                conn.commit()
                cur.close(); conn.close()
            
            await asyncio.sleep(20)
        except Exception as e:
            print(f"Global Error: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
