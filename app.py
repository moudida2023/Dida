import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string
from datetime import datetime
import requests
import time

app = Flask(__name__)

# --- الإعدادات ---
INITIAL_CAPITAL = 1000.0
INVESTMENT_PER_TRADE = 50.0
ENTRY_SCORE_THRESHOLD = 70   
TAKE_PROFIT_PCT = 0.04       
STOP_LOSS_PCT = 0.02         
MAX_TRADES = 5

DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
RENDER_APP_URL = "https://dida-fvym.onrender.com"

# --- 1. تحديث تلقائي لقاعدة البيانات ---
def init_db_updates():
    try:
        conn = psycopg2.connect(str(DB_URL).strip(), sslmode='require')
        cur = conn.cursor()
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='trades' AND column_name='entry_score') THEN
                    ALTER TABLE trades ADD COLUMN entry_score INT DEFAULT 0;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='trades' AND column_name='max_asc') THEN
                    ALTER TABLE trades ADD COLUMN max_asc FLOAT DEFAULT 0;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='trades' AND column_name='max_desc') THEN
                    ALTER TABLE trades ADD COLUMN max_desc FLOAT DEFAULT 0;
                END IF;
            END $$;
        """)
        conn.commit()
        cur.close(); conn.close()
        print("✅ Database columns checked/added.")
    except Exception as e:
        print(f"⚠️ Auto-update DB failed: {e}")

def get_db_connection():
    try:
        return psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=15)
    except Exception as e:
        print(f"❌ DB Conn Error: {e}")
        return None

def keep_alive():
    while True:
        try: 
            requests.get(RENDER_APP_URL, timeout=10)
        except: 
            pass
        time.sleep(600)

# --- 2. منطق الحسابات الفنية ---
def calculate_trade_score(ticker):
    score = 0
    try:
        change = float(ticker.get('percentage', 0) or 0)
        if change > 1.5: score += 40
        elif change > 0.5: score += 20
        
        quote_vol = float(ticker.get('quoteVolume', 0) or 0)
        if quote_vol > 300000: score += 30
        
        last = float(ticker.get('last', 0) or 0)
        high = float(ticker.get('high', 0) or 0)
        if last >= (high * 0.95): score += 30
    except: pass
    return score

def close_position(symbol, exit_price, reason):
    conn = get_db_connection()
    if not conn: return False
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (str(symbol),))
        t = cur.fetchone()
        if t:
            pnl = ((
