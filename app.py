import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for, request
from datetime import datetime

app = Flask(__name__)

# --- الإعدادات ---
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
TAKE_PROFIT = 5.0  # جني الأرباح عند +5%
STOP_LOSS = -5.0   # وقف الخسارة عند -5%

def get_db_connection():
    try:
        return psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=15)
    except:
        return None

# --- دالة الإغلاق البرمجية ---
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
            exit_p = float(exit_price)
            pnl = ((exit_p - entry_p) / entry_p) * investment
            
            # تسجيل في الصفقات المغلقة
            cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                           VALUES (%s, %s, %s, %s, %s, %s)""", 
                        (symbol, entry_p, exit_p, pnl, reason, datetime.now().strftime('%H:%M')))
            
            # تحديث المحفظة
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
            conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        print(f"Error closing {symbol}: {e}")

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
    balance = 0.0
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        active_trades = cur.fetchall()
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        row = cur.fetchone()
        balance = float(row[0]) if row else 0.0
        cur.close(); conn.close()

    return render_template_string("""
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; }
        .card { background: #1e2329; padding: 20px; border-radius: 15px; border: 2px solid #f0b90b; margin-bottom: 20px; }
        .balance-value { font-size: 40px; font-weight: bold; color: #f0b90b; }
        table { width: 100%; border-collapse: collapse; background: #161a1e; }
        th, td { padding: 15px; border-bottom: 1px solid #2b3139; font-size: 20px; }
        .up { color: #0ecb81; } .down { color: #f6465d; }
        .limit-info { font-size: 12px; color: #848e9c; display: block; }
    </style></head><body>
        <div class="card">
            <div style="color:#848e9c">الرصيد الكلي</div>
            <div class="balance-value">${{ "%.2f"|format(balance + 1000) }}</div>
            <div style="margin-top:10px;">
                <span class="up">الهدف: +5%</span> | <span class="down">الوقف: -5%</span>
            </div>
        </div>
        <h3 style="text-align:right; color:#f0b90b;">🚀 صفقات تحت المراقبة</h3>
        <table>
            <tr><th>العملة</th><th>الربح</th><th>أعلى/أدنى</th><th>تحكم</th></tr>
            {% for t in active_trades %}
            {% set p = ((t.current_price - t.entry_price) / t.entry_price) * 100 %}
            <tr>
                <td>{{ t.symbol.split('/')[0] }}</td>
                <td class="{{ 'up' if p >= 0 else 'down' }}">{{ "%.2f"|format(p) }}
