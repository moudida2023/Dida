import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime

app = Flask(__name__)

# --- الإعدادات الأساسية ---
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
INITIAL_CAPITAL = 500.0  # القيمة الافتراضية التي بدأت بها
exchange_status = "🔴"

def get_db_connection():
    try:
        return psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=10)
    except:
        return None

# --- المحرك الخلفي (بدون تغيير في المنطق الأساسي) ---
async def trading_engine():
    global exchange_status
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            await exchange.load_markets()
            exchange_status = "🟢"
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute("SELECT * FROM trades")
                active_trades = cur.fetchall()
                tickers = await exchange.fetch_tickers()
                for t in active_trades:
                    sym = t['symbol']
                    if sym in tickers:
                        curr_p = float(tickers[sym]['last'])
                        # تحديث السعر الحالي أو الإغلاق الآلي
                        cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (curr_p, sym))
                conn.commit()
                cur.close(); conn.close()
            await asyncio.sleep(15)
        except:
            exchange_status = "🔴"
            await asyncio.sleep(20)

# --- واجهة المستخدم المطورة v510 ---
@app.route('/')
def index():
    conn = get_db_connection()
    if conn is None: return "<h3>⚠️ فشل الاتصال بالقاعدة</h3>", 500
    
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        # جلب الصفقات المفتوحة
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        ot = cur.fetchall()
        # جلب الربح المحقق من المحفظة
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        res_wallet = cur.fetchone()
        realized_pnl = res_wallet[0] if res_wallet else 0.0
        # جلب سجل العمليات
        cur.execute("SELECT * FROM closed_trades ORDER BY id DESC LIMIT 5")
        ct = cur.fetchall()
        cur.close(); conn.close()

        # حساب الإحصائيات لحظياً
        invested_now = sum(t['investment'] for t in ot)
        floating_pnl = sum(((t['current_price'] - t['entry_price']) / t['entry_price']) * t['investment'] for t in ot)
        total_net_value = INITIAL_CAPITAL + realized_pnl + floating_pnl

        return render_template_string("""
        <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; margin: 0; padding: 15px; }
            .stats-container { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 20px; }
            .stat-card { background: #1e2329; padding: 15px; border-radius: 10px; border-bottom: 3px solid #f0b90b; }
            .stat-val { font-size: 18px; font-weight: bold; display: block; margin-top: 5px; }
            .up { color: #0ecb81; } .down { color: #f6465d; }
            table { width: 100%; border-collapse: collapse; background: #1e2329; font-size: 12px; margin-top: 10px; }
            th, td { padding: 8px; border: 1px solid #2b3139; }
            th { color: #848e9c; }
            .btn { background: #f6465d; color: white; padding: 3px 7px; border-radius: 4px; text-decoration: none; }
        </style></head><body>

            <h3 style="color:#f0b90b;">📊 ملخص حالة المحفظة</h3>
            <div class="stats-container">
                <div class="stat-card">رأس المال الافتراضي<span class="stat-val">${{ "%.2f"|format(init_cap) }}</span></div>
                <div class="stat-card">القيمة المستعملة<span class="stat-val" style="color:#92a2b1;">${{ "%.2f"|format(inv) }}</span></div>
                <div class="stat-card">النتيجة المحققة<span class="stat-val {{ 'up' if r_pnl >= 0 else 'down' }}">${{ "%.2f"|format(r_pnl) }}</span></div>
                <div class="stat-card">النتيجة العائمة<span class="stat-val {{ 'up' if f_pnl >= 0 else 'down' }}">${{ "%.2f"|format(f_pnl) }}</span></div>
            </div>

            <div style="background:#1e2329; padding:10px; border-radius:10px; margin-bottom:20px;">
                <span>القيمة الإجمالية للمحفظة الآن: </span>
                <b style="font-size:20px;" class="{{ 'up' if net >= init_cap else 'down' }}">${{ "%.2f"|format(net) }}</b>
            </div>

            <h4>📍 صفقات مفتوحة ({{ ot|length }})</h4>
            <table>
                <tr><th>العملة</th><th>الحالي</th><th>الهدف</th><th>الربح</th><th>إجراء</th></tr>
                {% for t in ot %}
                {% set p = ((t.current_price - t.entry_price) / t.entry_price) * t.investment %}
                <tr><td>{{ t.symbol }}</td><td style="color:#f0b90b;">{{ t.current_price }}</td><td class="up">{{ t.tp_price }}</td><td class="{{ 'up' if p >= 0 else 'down' }}">${{ "%.2f"|format(p) }}</td>
                <td><a href="/manual_close/{{ t.symbol }}" class="btn">إغلاق</a></td></tr>
                {% endfor %}
            </table>
        </body></html>
        """, init_cap=INITIAL_CAPITAL, inv=invested_now, r_pnl=realized_pnl, f_pnl=floating_pnl, net=total_net_value, ot=ot, s_ex=exchange_status)
    except Exception as e:
        return f"<h3>خطأ: {e}</h3>", 500

@app.route('/manual_close/<symbol>')
def manual_close_route(symbol):
    try:
        import ccxt
        price = ccxt.gateio().fetch_ticker(symbol)['last']
        # استدعاء دالة الإغلاق (تأكد من وجودها في الكود)
        from app import close_position
        close_position(symbol, price, "👤 يدوي")
    except: pass
    return redirect(url_for('index'))

if __name__ == "__main__":
    t = threading.Thread(target=lambda: asyncio.run(trading_engine()))
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
