import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime, timedelta

app = Flask(__name__)

# --- الإعدادات ---
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
TAKE_PROFIT = 5.0
STOP_LOSS = -5.0
INITIAL_CAPITAL = 1000.0

# متغيرات الحالة العالمية
status_indicators = {"db": "🔴", "exchange": "🔴", "server": "🟢"}

def get_db_connection():
    try:
        conn = psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=5)
        status_indicators["db"] = "🟢"
        return conn
    except:
        status_indicators["db"] = "🔴"
        return None

def execute_close_logic(symbol, exit_price, reason="Auto"):
    conn = get_db_connection()
    if not conn: return
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (symbol,))
        trade = cur.fetchone()
        if trade:
            investment = float(trade['investment'])
            entry_p = float(trade['entry_price'])
            pnl = ((float(exit_price) - entry_p) / entry_p) * investment
            cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                           VALUES (%s, %s, %s, %s, %s, %s)""", 
                        (symbol, entry_p, float(exit_price), pnl, reason, datetime.now()))
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
            conn.commit()
        cur.close(); conn.close()
    except: pass

@app.route('/close/<path:symbol>', methods=['POST'])
def manual_close(symbol):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT current_price FROM trades WHERE symbol = %s", (symbol,))
        res = cur.fetchone()
        if res: execute_close_logic(symbol, res['current_price'], "Manual")
        cur.close(); conn.close()
    return redirect(url_for('index'))

@app.route('/')
def index():
    conn = get_db_connection()
    active_trades = []
    closed_24h = []
    realized_pnl_24h = 0.0
    floating_pnl = 0.0
    balance = 0.0
    
    if conn:
        try:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            # صفقات نشطة
            cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
            active_trades = cur.fetchall()
            # صفقات مغلقة آخر 24 ساعة
            time_threshold = datetime.now() - timedelta(hours=24)
            cur.execute("SELECT * FROM closed_trades WHERE close_time > %s ORDER BY close_time DESC", (time_threshold,))
            closed_24h = cur.fetchall()
            realized_pnl_24h = sum(float(c['pnl']) for c in closed_24h)
            
            # محفظة
            cur.execute("SELECT balance FROM wallet WHERE id = 1")
            row = cur.fetchone()
            balance = float(row[0]) if row else 0.0
            
            # الربح العائم
            floating_pnl = sum(((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment']) for t in active_trades)
            
            cur.close(); conn.close()
        except: pass

    return render_template_string("""
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; margin: 0; }
        .status-bar { background: #1e2329; padding: 5px; font-size: 12px; border-bottom: 1px solid #2b3139; display: flex; justify-content: space-around; }
        .card { background: #1e2329; padding: 15px; border-radius: 12px; border: 1px solid #f0b90b; margin: 10px
