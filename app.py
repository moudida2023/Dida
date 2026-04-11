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
# التأكد من أن الرابط نصي خالص
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"

def get_db_connection():
    try:
        # تحويل الرابط لنص صريح لتجنب خطأ "got type instead"
        conn_str = str(DB_URL).strip()
        return psycopg2.connect(conn_str, sslmode='require', connect_timeout=15)
    except Exception as e:
        print(f"DATABASE CONNECTION ERROR: {e}")
        return None

def close_position(symbol, exit_price, reason):
    conn = get_db_connection()
    if not conn: return False
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        # استخدام str() لضمان أن الرمز نص وليس كائن
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (str(symbol),))
        t = cur.fetchone()
        if t:
            # ضمان أن الأسعار أرقام عشرية
            e_price = float(t['entry_price'])
            ex_price = float(exit_price)
            inv = float(t['investment'])
            
            pnl = ((ex_price - e_price) / e_price) * inv
            
            cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (str(symbol), e_price, ex_price, pnl, str(reason), datetime.now().strftime('%Y-%m-%d %H:%M')))
            
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (str(symbol),))
            conn.commit()
        cur.close(); conn.close()
        return True
    except Exception as e:
        print(f"CLOSE ERROR: {e}")
        if conn: conn.rollback(); conn.close()
        return False

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        if not conn: return "<h3>⚠️ تعذر الاتصال بقاعدة البيانات</h3>", 500
        
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        ot = cur.fetchall()
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        res_w = cur.fetchone()
        realized_pnl = float(res_w[0]) if res_w else 0.0
        cur.close(); conn.close()

        invested = len(ot) * INVESTMENT_PER_TRADE
        unused = (INITIAL_CAPITAL + realized_pnl) - invested
        floating = sum(((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment']) for t in ot)
        net = INITIAL_CAPITAL + realized_pnl + floating

        return render_template_string("""
        <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="20">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; margin: 0; }
            .card { background: #1e2329; padding: 15px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #f0b90b; }
            .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 15px; }
            .s-card { background: #1e2329; padding: 10px; border-radius: 8px; font-size: 12px; }
            .up { color: #0ecb81; } .down { color: #f6465d; }
            .btn-all { background: #f6465d; color: white; padding: 12px; border-radius: 8px; text-decoration: none; display: block; margin: 15px 0; font-weight: bold; border: 1px solid white; }
            table { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 10px; }
            th, td { padding: 8px; border: 1px solid #2b3139; text-align: center; }
        </style></head><body>
            <div class="card">
                <small style="color:#848e9c;">صافي القيمة الكلية</small><br>
                <b style="font-size:26px;" class="{{ 'up' if net >= 1000 else 'down' }}">${{ "%.2f"|format(net) }}</b>
            </div>
            <div class="stats">
                <div class="s-card">المستعملة<br><b style="color:#f0b90b;">${{ "%.2f"|format(inv) }}</b></div>
                <div class="s-card">غير المستعملة<br><b style="color:#92a2b1;">${{ "%.2f"|format(un) }}</b></div>
            </div>
            {% if ot|length > 0 %}
            <a href="/close_all" class="btn-all" onclick="return confirm('إغلاق الكل؟')">⚠️ إغلاق كافة الصفقات</a>
            {% endif %}
            <h4>📍 صفقات مفتوحة ({{ ot|length }})</h4>
            <table>
                <tr><th>العملة</th><th>الحالي</th><th>الربح ($
