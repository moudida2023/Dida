import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string, redirect, url_for
from datetime import datetime
import requests
import time

app = Flask(__name__)

# --- الإعدادات الأساسية ---
INITIAL_CAPITAL = 1000.0
INVESTMENT_PER_TRADE = 50.0
ENTRY_SCORE_THRESHOLD = 85   # عتبة الدخول (سكور)
TAKE_PROFIT_PCT = 0.02       # جني الأرباح (2%)
STOP_LOSS_PCT = 0.012        # وقف الخسارة (1.2%)
MAX_TRADES = 5               # أقصى عدد صفقات متزامنة

DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"
RENDER_APP_URL = "https://dida-fvym.onrender.com"

# --- إدارة قاعدة البيانات ---
def get_db_connection():
    try:
        url = str(DB_URL).strip()
        return psycopg2.connect(url, sslmode='require', connect_timeout=15)
    except Exception as e:
        print(f"❌ DB Connection Error: {e}")
        return None

def keep_alive():
    """منع السيرفر من النوم عبر مراسلة نفسه"""
    while True:
        try:
            requests.get(RENDER_APP_URL, timeout=10)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔔 Self-Ping Sent")
        except: pass
        time.sleep(600)

# --- منطق الاستراتيجية (السكور) ---
def calculate_trade_score(ticker):
    """حساب السكور بناءً على البولينجر، الفوليوم، والزخم"""
    score = 0
    try:
        # 1. تحليل التغير السعري (الزخم) - [30 نقطة]
        change = float(ticker.get('percentage', 0) or 0)
        if change > 2.5: score += 30
        elif change > 1.0: score += 15

        # 2. تحليل الفوليوم (السيولة) - [30 نقطة]
        quote_vol = float(ticker.get('quoteVolume', 0) or 0)
        if quote_vol > 1000000: score += 30
        elif quote_vol > 500000: score += 15

        # 3. اختراق البولينجر والقوة الشرائية - [40 نقطة]
        last = float(ticker.get('last', 0) or 0)
        high = float(ticker.get('high', 0) or 0)
        if last >= (high * 0.985): score += 40  # قريب جداً من القمة (انفجار)
        elif last >= (high * 0.96): score += 20
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
            pnl = ((float(exit_price) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment'])
            cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (str(symbol), float(t['entry_price']), float(exit_price), pnl, str(reason), datetime.now().strftime('%Y-%m-%d %H:%M')))
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (str(symbol),))
            conn.commit()
            print(f"✅ Closed {symbol} | Reason: {reason} | PnL: ${pnl:.2f}")
        cur.close(); conn.close()
        return True
    except Exception as e:
        print(f"❌ Error Closing: {e}")
        if conn: conn.close()
        return False

# --- واجهة الويب (Dashboard) ---
@app.route('/')
def index():
    conn = get_db_connection()
    if not conn: return "DB Connection Error", 500
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        active_trades = cur.fetchall()
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        res_w = cur.fetchone()
        realized_pnl = float(res_w[0]) if res_w else 0.0
        cur.close(); conn.close()

        invested = len(active_trades) * INVESTMENT_PER_TRADE
        unused = (INITIAL_CAPITAL + realized_pnl) - invested
        floating = sum(((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment']) for t in active_trades)
        net_value = INITIAL_CAPITAL + realized_pnl + floating

        return render_template_string("""
        <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; margin: 0; }
            .card { background: #1e2329; padding: 15px; border-radius: 10px; border: 1px solid #f0b90b; margin-bottom: 15px; }
            .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 15px; }
            .s-box { background: #1e2329; padding: 10px; border-radius: 8px; border: 1px solid #2b3139; }
            .up { color: #0ecb81; } .down { color: #f6465d; }
            table { width: 100%; border-collapse: collapse; font-size: 12px; }
            th, td { padding: 10px; border: 1px solid #2b3139; }
        </style></head><body>
            <div class="card">
                <small>صافي قيمة المحفظة (الآن)</small><br>
                <b style="font-size:28px;" class="{{ 'up' if net >= 1000 else 'down' }}">${{ "%.2f"|format(net) }}</b>
            </div>
            <div class="stats">
                <div class="s-box">قيد التداول<br><b style="color:#f0b90b;">${{ "%.2f"|format(inv) }}</b></div>
                <div class="s-box">رصيد متاح<br><b style="color:#92a2b1;">${{ "%.2f"|format(un) }}</b></div>
            </div>
            <h4>📍 صفقات نشطة ({{ trades|length }})</h4>
            <table>
                <tr><th>العملة</th><th>السعر</th><th>الربح</th></tr>
                {% for t in trades %}
                {% set p = ((t.current_price - t.entry_price) / t.entry_price) * 50 %}
                <tr><td>{{ t.symbol }}</td><td>{{ t.current_price }}</td><td class="{{ 'up' if p >= 0 else 'down' }}">${{ "%.2f"|format(p) }}</td></tr>
                {% endfor %}
            </table>
        </body></html>
        """, net=net_value, inv=invested, un=unused, trades=active_trades)
    except: return "Dashboard Error", 500

# --- محرك التداول الآلي ---
async def trading_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    print("🚀 Trading Engine Starting...")
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute("SELECT * FROM trades")
                active_trades = cur.fetchall()
                
                # 1. مراقبة الأهداف (TP/SL) وتحديث الأسعار
                for t in active_trades:
                    sym = t['symbol']
                    if sym in tickers:
                        curr_p = float(tickers[sym]['last'])
                        cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (curr_p, sym))
                        
                        # حساب الربح/الخسارة للخروج
                        pnl_pct = (curr_p - float(t['entry_price'])) / float(t['entry_price'])
                        if pnl_pct >= TAKE_PROFIT_PCT:
                            close_position(sym, curr_p, "🎯 جني أرباح سريع")
                        elif pnl_pct <= -STOP_LOSS_PCT:
                            close_position(sym, curr_p, "🛑 وقف خسارة حماية")
                
                # 2. البحث عن فرص جديدة (سكور 85+)
                if len(active_trades) < MAX_TRADES:
                    for sym, data in tickers.items():
                        if '/USDT' in sym and sym not in [x['symbol'] for x in active_trades]:
                            score = calculate_trade_score(data)
                            if score >= ENTRY_SCORE_THRESHOLD:
                                price = float(data['last'])
                                cur.execute("INSERT INTO trades (symbol, entry_price, current_price, investment, open_time) VALUES (%s, %s, %s, %s, %s)",
                                           (sym, price, price, INVESTMENT_PER_TRADE, datetime.now().strftime('%H:%M')))
                                print(f"🔥 Auto-Entry: {sym} | Score: {score}")
                                break # فتح صفقة واحدة فقط في كل دورة
                
                conn.commit(); cur.close(); conn.close()
            await asyncio.sleep(20)
        except Exception as e:
            print(f"Engine Loop Error: {e}")
            await asyncio.sleep(20)

if __name__ == "__main__":
    threading.Thread(target=keep_alive, daemon=True).start()
    threading.Thread(target=lambda: asyncio.run(trading_engine()), daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
