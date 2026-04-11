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
from flask import Flask
from datetime import datetime, timedelta

app = Flask(__name__)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"

# --- UTILS ---
def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=5)
    except: pass

def get_db_connection():
    try:
        return psycopg2.connect(DB_URL, sslmode='require')
    except: return None

# --- FONCTION RAPPORT HORAIRE (Chaque 1h) ---
def hourly_report_loop():
    """Envoie une liste des ordres ouverts et fermés chaque heure"""
    while True:
        # الانتظار لمدة ساعة واحدة (3600 ثانية)
        time.sleep(3600)
        
        conn = get_db_connection()
        if not conn: continue
        
        try:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            # 1. جلب الصفقات المفتوحة
            cur.execute("SELECT symbol, entry_price, current_price FROM trades")
            open_trades = cur.fetchall()
            
            # 2. جلب الصفقات المغلقة في آخر ساعة
            last_hour = datetime.now() - timedelta(hours=1)
            cur.execute("SELECT symbol, pnl, exit_reason FROM closed_trades WHERE close_time >= %s", (last_hour,))
            closed_trades = cur.fetchall()
            
            # صياغة رسالة الصفقات المفتوحة
            msg_open = "📋 *Rapport Horaire : Ordres Ouverts*\n━━━━━━━━━━━━━━━\n"
            if open_trades:
                for t in open_trades:
                    pnl = ((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * 100
                    msg_open += f"• `{t['symbol']}` : {pnl:+.2f}%\n"
            else:
                msg_open += "Aucun ordre ouvert actuellement."
            
            # صياغة رسالة الصفقات المغلقة
            msg_closed = "\n✅ *Ordres Fermés (Dernière heure) :*\n━━━━━━━━━━━━━━━\n"
            if closed_trades:
                for t in closed_trades:
                    msg_closed += f"• `{t['symbol']}` : {float(t['pnl']):+.2f}$ ({t['exit_reason']})\n"
            else:
                msg_closed += "Aucun ordre fermé cette heure."

            send_telegram_msg(msg_open + msg_closed)
            
            cur.close(); conn.close()
        except Exception as e:
            print(f"Erreur Rapport: {e}")

# --- (باقي محرك التداول monitor_engine يبقى كما هو في v596) ---
async def monitor_engine():
    # ... نفس كود التحليل الفني وفتح الصفقات ...
    pass

if __name__ == "__main__":
    # 1. تشغيل تقرير الساعة في الخلفية
    threading.Thread(target=hourly_report_loop, daemon=True).start()
    
    # 2. تشغيل المحرك الرئيسي
    threading.Thread(target=lambda: asyncio.run(monitor_engine()), daemon=True).start()
    
    # 3. تشغيل سيرفر الويب
    app.run(host='0.0.0.0', port=10000)
