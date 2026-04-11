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
INITIAL_CAPITAL = 1000.0

def get_db_connection():
    try:
        return psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=15)
    except:
        return None

# --- الدالة الجوهرية: تنفيذ عملية الإغلاق وإضافة النتيجة للمحفظة ---
def execute_close_logic(symbol, exit_price, reason="Manual"):
    conn = get_db_connection()
    if not conn: return False
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        
        # 1. جلب بيانات الصفقة قبل حذفها
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (symbol,))
        trade = cur.fetchone()
        
        if trade:
            # 2. حساب الربح/الخسارة الصافي (PnL)
            investment = float(trade['investment'])
            entry_price = float(trade['entry_price'])
            exit_price = float(exit_price)
            
            # الربح = (نسبة التغير) * مبلغ الاستثمار
            pnl = ((exit_price - entry_price) / entry_price) * investment
            
            # 3. تسجيل الصفقة في جدول الصفقات المغلقة
            cur.execute("""
                INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (symbol, entry_price, exit_price, pnl, reason, datetime.now().strftime('%Y-%m-%d %H:%M')))
            
            # 4. تحديث رأس المال في المحفظة (إضافة الربح أو طرح الخسارة)
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            
            # 5. حذف الصفقة من الجدول النشط
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
            
            conn.commit()
            print(f"✅ Closed {symbol} | PnL: {pnl}")
        
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error during close: {e}")
        return False

# --- المسارات (Routes) ---

@app.route('/close/<path:symbol>', methods=['POST'])
def close_trade(symbol):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT current_price FROM trades WHERE symbol = %s", (symbol,))
        res = cur.fetchone()
        if res:
            # تنفيذ دالة الإغلاق البرمجية
            execute_close_logic(symbol, res['current_price'], "Manual Click")
        cur.close(); conn.close()
    return redirect(url_for('index'))

@app.route('/close_all', methods=['POST'])
def close_all():
    conn = get_db_connection()
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT symbol, current_price FROM trades")
        all_trades = cur.fetchall()
        cur.close(); conn.close()
        for t in all_trades:
            execute_close_logic(t['symbol'], t['current_price'], "Panic Close All")
    return redirect(url_for('index'))

@app.route('/')
def index():
    conn = get_db_connection()
    active_trades = []
    closed_history = []
    balance = 0.0
    
    if conn:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        active_trades = cur.fetchall()
        cur.execute("SELECT * FROM closed_trades ORDER BY id DESC LIMIT 10")
        closed_history = cur.fetchall()
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        row = cur.fetchone()
        balance = float(row[0]) if row else 0.0
        cur.close(); conn.close()

    return render_template_string("""
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="20">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; }
        .card { background: #1e2329; padding: 15px; border-radius: 12px; border: 1px solid #f0b90b; margin-bottom: 20px; }
        .btn-panic { background: #f6465d; color: white; border: none; padding: 12px; border-radius: 5px; cursor: pointer; font-weight: bold; width: 100%; margin-bottom: 20px; }
        .btn-close { background: transparent; color: #f6465d; border: 1px solid #f6465d; padding: 4px 10px; border-radius: 4px; cursor: pointer; }
        .btn-close:hover { background: #f6465d; color: white; }
        table { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 10px; }
        th, td { padding: 10px; border: 1px solid #2b3139; }
        .up { color: #0ecb81; } .down { color: #f6465d; }
    </style></head><body>
        <div class="card">
            <small style="color:#848e9c;">رأس المال الحالي (المحقق)</small>
            <h2 style="margin:5px 0; color:#f0b90b;">${{ "%.2f"|format(balance + 1000) }}</h2>
            <form action="/close_all" method="post" onsubmit="return confirm('إغلاق جميع الصفقات الآن؟')">
                <button type="submit" class="btn-panic">🛑 إغلاق كافة المراكز</button>
            </form>
        </div>

        <h4 style="text-align:right; color:#f0b90b;">📍 الصفقات النشطة</h4>
        <table>
            <tr><th>العملة</th><th>الربح %</th><th>إجراء</th></tr>
            {% for t in active %}
            {% set p = ((t.current_price - t.entry_price) / t.entry_price) * 100 %}
            <tr>
                <td><b>{{ t.symbol.split('/')[0] }}</b></td>
                <td class="{{ 'up' if p >= 0 else 'down' }}">{{ "%.2f"|format(p) }}%</td>
                <td>
                    <form action="/close/{{ t.symbol }}" method="post">
                        <button type="submit" class="btn-close">إغلاق الصفقة</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>

        <h4 style="text-align:right; color:#848e9c; margin-top:30px;">📜 سجل العمليات المغلقة</h4>
        <table>
            {% for c in closed_history %}
            <tr>
                <td>{{ c.symbol.split('/')[0] }}</td>
                <td class="{{ 'up' if c.pnl >= 0 else 'down' }}">${{ "%.2f"|format(c.pnl) }}</td>
                <td><small>{{ c.exit_reason }}</small></td>
            </tr>
            {% endfor %}
        </table>
    </body></html>
    """, balance=balance, active=active_trades, closed_history=closed_history)

if __name__ == "__main__":
    # تشغيل Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
