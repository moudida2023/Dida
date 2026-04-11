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
            # تم إصلاح الأقواس هنا (السطر 90 سابقاً)
            pnl = ((float(exit_price) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment'])
            cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (str(symbol), float(t['entry_price']), float(exit_price), pnl, str(reason), datetime.now().strftime('%Y-%m-%d %H:%M')))
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (str(symbol),))
            conn.commit()
        cur.close(); conn.close()
        return True
    except:
        if conn: conn.close()
        return False

# --- 3. واجهة المستخدم (Dashboard) ---
@app.route('/')
def index():
    conn = get_db_connection()
    if not conn: return "DB Connection Error", 500
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        active_trades = cur.fetchall()
        cur.execute("SELECT * FROM closed_trades ORDER BY close_time DESC LIMIT 10")
        closed_trades = cur.fetchall()
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        res_w = cur.fetchone()
        realized_pnl = float(res_w[0]) if res_w else 0.0
        cur.close(); conn.close()

        floating = sum(((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment']) for t in active_trades)
        net_val = INITIAL_CAPITAL + realized_pnl + floating

        return render_template_string("""
        <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="20">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; margin: 0; }
            .card { background: #1e2329; padding: 20px; border-radius: 12px; border: 1px solid #f0b90b; margin-bottom: 20px; }
            .up { color: #0ecb81; } .down { color: #f6465d; }
            .score-badge { background: #f0b90b; color: black; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
            table { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 10px; }
            th, td { padding: 10px; border: 1px solid #2b3139; }
            .section-title { color: #f0b90b; text-align: right; margin-top: 20px; border-right: 4px solid #f0b90b; padding-right: 8px; }
        </style></head><body>
            <div class="card">
                <small>صافي قيمة المحفظة</small><br>
                <b style="font-size:30px;">${{ "%.2f"|format(net) }}</b>
            </div>
            <h4 class="section-title">📍 صفقات نشطة</h4>
            <table>
                <tr><th>العملة</th><th>سكور</th><th>أعلى صعود</th><th>أدنى نزول</th><th>الربح %</th></tr>
                {% for t in active %}
                {% set p = ((t.current_price - t.entry_price) / t.entry_price) * 100 %}
                <tr>
                    <td><b>{{ t.symbol }}</b></td>
                    <td><span class="score-badge">{{ t.entry_score or '--' }}</span></td>
                    <td class="up">+{{ "%.2f"|format(t.max_asc or 0) }}%</td>
                    <td class="down">{{ "%.2f"|format(t.max_desc or 0) }}%</td>
                    <td class="{{ 'up' if p >= 0 else 'down' }}">{{ "%.2f"|format(p) }}%</td>
                </tr>
                {% endfor %}
            </table>
            <h4 class="section-title">✅ تاريخ الإغلاق</h4>
            <table>
                <tr><th>العملة</th><th>الربح ($)</th><th>السبب</th></tr>
                {% for c in closed %}
                <tr><td>{{ c.symbol }}</td><td class="{{ 'up' if c.pnl >= 0 else 'down' }}">${{ "%.2f"|format(c.pnl) }}</td><td>{{ c.exit_reason }}</td></tr>
                {% endfor %}
            </table>
        </body></html>
        """, net=net_val, active=active_trades, closed=closed_trades)
    except: 
        return "Dashboard Error", 500

# --- 4. محرك التداول ---
async def trading_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute("SELECT * FROM trades")
                active_trades = cur.fetchall()
                
                for t in active_trades:
                    sym = t['symbol']
                    if sym in tickers:
                        curr_p = float(tickers[sym]['last'])
                        entry_p = float(t['entry_price'])
                        curr_pnl_pct = (curr_p - entry_p) / entry_p * 100
                        
                        m_asc = max(float(t['max_asc'] or 0), curr_pnl_pct)
                        m_desc = min(float(t['max_desc'] or 0), curr_pnl_pct)
                        
                        cur.execute("UPDATE trades SET current_price = %s, max_asc = %s, max_desc = %s WHERE symbol = %s", 
                                   (curr_p, m_asc, m_desc, sym))
                        
                        if curr_pnl_pct >= (TAKE_PROFIT_PCT * 100): 
                            close_position(sym, curr_p, "🎯 TP 4%")
                        elif curr_pnl_pct <= -(STOP_LOSS_PCT * 100): 
                            close_position(sym, curr_p, "🛑 SL 2%")
                
                if len(active_trades) < MAX_TRADES:
                    for sym, data in tickers.items():
                        if '/USDT' in sym and sym not in [x['symbol'] for x in active_trades]:
                            score = calculate_trade_score(data)
                            if score >= ENTRY_SCORE_THRESHOLD:
                                p = float(data['last'])
                                cur.execute("""INSERT INTO trades (symbol, entry_price, current_price, investment, open_time, max_asc, max_desc, entry_score) 
                                               VALUES (%s, %s, %s, %s, %s, 0, 0, %s)""",
                                           (sym, p, p, INVESTMENT_PER_TRADE, datetime.now().strftime('%H:%M'), score))
                                break
                conn.commit(); cur.close(); conn.close()
            await asyncio.sleep(20)
        except: 
            await asyncio.sleep(20)

if __name__ == "__main__":
    init_db_updates()
    threading.Thread(target=keep_alive, daemon=True).start()
    threading.Thread(target=lambda: asyncio.run(trading_engine()), daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
