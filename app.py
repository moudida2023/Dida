import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

app = Flask(__name__)

# --- إعدادات قاعدة البيانات ---
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
exchange_status = "🔴"

def get_db_connection():
    try:
        return psycopg2.connect(DB_URL, sslmode='require', connect_timeout=10)
    except:
        return None

# --- وظيفة إغلاق الصفقة (المحرك الأساسي) ---
def close_position(symbol, exit_price, reason):
    """تقوم هذه الدالة بحساب الربح، تحديث المحفظة، ونقل الصفقة للسجل"""
    conn = get_db_connection()
    if not conn: return False
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        # 1. جلب بيانات الصفقة قبل حذفها
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (symbol,))
        trade = cur.fetchone()
        
        if trade:
            # 2. حساب الربح أو الخسارة (PNL)
            pnl = ((exit_price - trade['entry_price']) / trade['entry_price']) * trade['investment']
            
            # 3. تسجيل الصفقة في جدول المغلقة
            cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (symbol, trade['entry_price'], exit_price, pnl, reason, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            
            # 4. تحديث الرصيد التراكمي في المحفظة
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            
            # 5. مسح الصفقة من المفتوحة
            cur.execute("DELETE FROM trades WHERE symbol = %s", (symbol,))
            
            conn.commit()
            print(f"✅ Closed {symbol} | Reason: {reason} | PNL: {pnl}")
        cur.close(); conn.close()
        return True
    except Exception as e:
        print(f"❌ Error closing position: {e}")
        return False

# --- محرك الرصد والإغلاق الآلي ---
async def trading_engine():
    global exchange_status
    exchange = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            await exchange.load_markets()
            exchange_status = "🟢"
            
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(extras.DictCursor)
                cur.execute("SELECT * FROM trades")
                trades = cur.fetchall()
                tickers = await exchange.fetch_tickers()
                
                for t in trades:
                    sym = t['symbol']
                    if sym in tickers:
                        curr_p = float(tickers[sym]['last'])
                        
                        # فحص الإغلاق الآلي
                        if curr_p >= t['tp_price']:
                            close_position(sym, curr_p, "🎯 جني أرباح (آلي)")
                        elif curr_p <= t['sl_price']:
                            close_position(sym, curr_p, "🛑 وقف خسارة (آلي)")
                        else:
                            # تحديث السعر الحالي فقط للعرض
                            cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (curr_p, sym))
                
                conn.commit()
                cur.close(); conn.close()
            await asyncio.sleep(15)
        except:
            exchange_status = "🔴"
            await asyncio.sleep(15)

# --- الواجهة الرسومية ---
@app.route('/')
def index():
    conn = get_db_connection()
    ot, ct, balance = [], [], 0.0
    if conn:
        cur = conn.cursor(extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        ot = cur.fetchall()
        cur.execute("SELECT * FROM closed_trades ORDER BY id DESC LIMIT 10")
        ct = cur.fetchall()
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        res = cur.fetchone()
        balance = res[0] if res else 0.0
        cur.close(); conn.close()
    
    return render_template_string("""
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 20px; }
        .card { background: #1e2329; padding: 20px; border-radius: 12px; margin-bottom: 20px; border-bottom: 4px solid #f0b90b; }
        table { width: 100%; border-collapse: collapse; background: #1e2329; }
        th, td { padding: 10px; border: 1px solid #2b3139; }
        .btn-manual { background: #f6465d; color: white; padding: 5px 10px; border-radius: 4px; text-decoration: none; font-size: 12px; }
        .up { color: #0ecb81; } .down { color: #f6465d; }
    </style></head><body>
        <div class="card">
            <h2>💰 المحفظة التراكمية: ${{ "%.2f"|format(balance) }}</h2>
            <p>حالة الاتصال: البورصة {{ s_ex }} | القاعدة 🟢</p>
        </div>

        <h3>📍 الصفقات المفتوحة</h3>
        <table>
            <tr><th>العملة</th><th>الدخول</th><th>الحالي</th><th>النتيجة</th><th>تحكم</th></tr>
            {% for t in ot %}
            {% set pnl = ((t.current_price - t.entry_price) / t.entry_price) * t.investment %}
            <tr>
                <td>{{ t.symbol }}</td>
                <td>{{ t.entry_price }}</td>
                <td style="color:#f0b90b;">{{ t.current_price }}</td>
                <td class="{{ 'up' if pnl >= 0 else 'down' }}">${{ "%.2f"|format(pnl) }}</td>
                <td><a href="/manual_close/{{ t.symbol }}" class="btn-manual">إغلاق يدوي</a></td>
            </tr>
            {% endfor %}
        </table>

        <h3>⌛ سجل الصفقات المغلقة</h3>
        <table>
            <tr><th>العملة</th><th>النتيجة</th><th>سبب الإغلاق</th><th>التوقيت</th></tr>
            {% for c in ct %}
            <tr><td>{{ c.symbol }}</td><td class="{{ 'up' if c.pnl >= 0 else 'down' }}">${{ "%.2f"|format(c.pnl) }}</td><td>{{ c.exit_reason }}</td><td>{{ c.close_time }}</td></tr>
            {% endfor %}
        </table>
    </body></html>
    """, s_ex=exchange_status, ot=ot, ct=ct, balance=balance)

@app.route('/manual_close/<symbol>')
def manual_close_route(symbol):
    # جلب آخر سعر من البورصة لإغلاق دقيق
    try:
        import ccxt
        ex = ccxt.gateio()
        ticker = ex.fetch_ticker(symbol)
        price = ticker['last']
        close_position(symbol, price, "👤 يدوي")
    except:
        pass
    return redirect(url_for('index'))

if __name__ == "__main__":
    # تهيئة الجداول (تأكد من وجود جدول wallet و trades و closed_trades)
    t = threading.Thread(target=lambda: asyncio.run(trading_engine()))
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
