import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

app = Flask(__name__)

# --- الإعدادات المالية ---
INITIAL_CAPITAL = 1000.0
INVESTMENT_PER_TRADE = 50.0
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
exchange_status = "🔴"

def get_db_connection():
    try:
        return psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=10)
    except:
        return None

# --- دالة الإغلاق (المحرك الرئيسي) ---
def close_position(symbol, exit_price, reason):
    conn = get_db_connection()
    if not conn: return False
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (symbol,))
        t = cur.fetchone()
        if t:
            pnl = ((float(exit_price) - t['entry_price']) / t['entry_price']) * t['investment']
            cur.execute("INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) VALUES (%s,%s,%s,%s,%s,%s)",
                        (symbol, t['entry_price'], exit_price, pnl, reason, datetime.now().strftime('%Y-%m-%d %H:%M')))
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
            conn.commit()
        cur.close(); conn.close()
        return True
    except: return False

# --- واجهة الويب v530 ---
@app.route('/')
def index():
    conn = get_db_connection()
    if not conn: return "DB Error", 500
    cur = conn.cursor(extras.DictCursor)
    cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
    ot = cur.fetchall()
    cur.execute("SELECT balance FROM wallet WHERE id = 1")
    res = cur.fetchone()
    realized_pnl = res[0] if res else 0.0
    cur.close(); conn.close()

    invested = len(ot) * INVESTMENT_PER_TRADE
    unused = (INITIAL_CAPITAL + realized_pnl) - invested
    floating = sum(((t['current_price'] - t['entry_price']) / t['entry_price']) * t['investment'] for t in ot)
    net = INITIAL_CAPITAL + realized_pnl + floating

    return render_template_string("""
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="20">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; }
        .card { background: #1e2329; padding: 15px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #f0b90b; }
        .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 15px; }
        .s-card { background: #1e2329; padding: 10px; border-radius: 8px; font-size: 12px; }
        .up { color: #0ecb81; } .down { color: #f6465d; }
        .btn-all { background: #f6465d; color: white; padding: 12px; border-radius: 8px; text-decoration: none; display: block; margin: 10px 0; font-weight: bold; border: 2px solid white; }
        table { width: 100%; border-collapse: collapse; font-size: 11px; }
        th, td { padding: 8px; border: 1px solid #2b3139; }
