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

status_indicators = {"db": "🔴", "exchange": "🔴", "server": "🟢"}

def get_db_connection():
    try:
        conn = psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=5)
        status_indicators["db"] = "🟢"
        return conn
    except Exception:
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
            inv = float(trade['investment'])
            ent = float(trade['entry_price'])
            pnl = ((float(exit_price) - ent) / ent) * inv
            cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                           VALUES (%s, %s, %s, %s, %s, %s)""", 
                        (symbol, ent, float(exit_price), pnl, reason, datetime.now()))
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
            conn.commit()
        cur.close(); conn.close()
    except Exception:
        if conn: conn.close()

@app.route('/close/<path:symbol>', methods=['POST'])
def manual_close(symbol):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute("SELECT current_price FROM trades WHERE symbol = %s", (symbol,))
            res = cur.fetchone()
            if res: execute_close_logic(symbol, res['current_price'], "Manual")
            cur.close(); conn.close()
        except:
            if conn: conn.close()
    return redirect(url_for('index'))

@app.route('/')
def index():
    conn = get_db_connection()
    active_trades = []
    closed_history = []
    realized_24h, floating, balance = 0.0, 0.0, 0.0
    
    if conn:
        try:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            # جلب الصفقات النشطة
            cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
            active_trades = cur.fetchall()
            # جلب آخر 20 صفقة مغلقة للسجل
            cur.execute("SELECT * FROM closed_trades ORDER BY close_time DESC LIMIT 20")
            closed_history = cur.fetchall()
            # حساب أرباح آخر 24 ساعة
            cur.execute("SELECT pnl FROM closed_trades WHERE close_time > %s", (datetime.now() - timedelta(hours=24),))
            realized_24h = sum(float(c[0]) for c in cur.fetchall())
            # المحفظة والربح العائم
            cur.execute("SELECT balance FROM wallet WHERE id = 1")
            row = cur.fetchone()
            balance = float(row[0]) if row else 0.0
            floating = sum(((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment']) for t in active_trades)
            cur.close(); conn.close()
        except Exception:
            if conn: conn.close()

    html_template = """
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 5px; margin: 0; }
        .status-bar { background: #1e2329; padding: 5px; font-size: 10px; border-bottom: 1px solid #2b3139; display: flex; justify-content: space-around; }
        .card { background: #1e2329; padding: 15px; border-radius: 15px; border: 1px solid #f0b90b; margin: 10px; }
        .total-val { font-size: 35px; font-weight: bold; color: #f0b90b; }
        .stat-box { background: #161a1e; padding: 10px; border-radius: 10px; width: 48%; display: inline-block; box-sizing: border
