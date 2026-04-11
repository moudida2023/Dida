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
ENTRY_SCORE_THRESHOLD = 60   
MAX_TRADES = 5
STABLE_COINS = ['USDC/USDT', 'FDUSD/USDT', 'TUSD/USDT', 'PAXG/USDT', 'EUR/USDT', 'DAI/USDT']

# لتخزين نتائج المسح لعرضها
last_scan_results = []

DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"

def get_db_connection():
    try: 
        return psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=15)
    except: 
        return None

def calculate_trade_score(ticker):
    symbol = ticker.get('symbol', '')
    quote_vol = float(ticker.get('quoteVolume', 0) or 0)
    
    if symbol in STABLE_COINS or quote_vol > 60000000: 
        return -1 
    
    score = 0
    try:
        change = float(ticker.get('percentage', 0) or 0)
        if change > 1.2: score += 30
        elif change > 0.5: score += 15
        
        if 200000 < quote_vol < 20000000: score += 30
        
        last = float(ticker.get('last', 0) or 0)
        high = float(ticker.get('high', 0) or 0)
        if last >= (high * 0.96): score += 40 
    except: pass
    return score

# --- الواجهة البرمجية ---
@app.route('/')
def index():
    conn = get_db_connection()
    active_trades = []
    net_val = INITIAL_CAPITAL
    
    if conn:
        try:
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
            active_trades = cur.fetchall()
            cur.execute("SELECT balance FROM wallet WHERE id = 1")
            res_w = cur.fetchone()
            realized = float(res_w[0]) if res_w else 0.0
            floating = sum(((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment']) for t in active_trades)
            net_val = INITIAL_CAPITAL + realized + floating
            cur.close(); conn.close()
        except: 
            pass

    return render_template_string("""
    <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
    <style>
        body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; margin: 0; }
        .card { background: #1e2329; padding: 15px; border-radius: 12px; border: 1px solid #f0b90b; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 20px; background: #1e2329; }
        th, td { padding: 10px; border: 1px solid #2b3139; text-align: center; }
        .up { color: #0ecb81; } .down { color: #f6465d; }
        .price-val { color: #f0b90b; font-weight: bold; }
        .section-title { color: #f0b90b; text-align: right; border-right: 4px solid #f0b90b; padding-right: 10px; margin: 20px 0 10px 0; }
        .score-badge { background: #f0b90b; color: black; padding: 2px 5px; border-radius: 4px; font-weight: bold; }
    </style></head><body>
        <div class="card">
            <small style="color:#848e9c;">صافي قيمة الحساب</small>
            <h2 style="margin:5px 0;">${{ "%.2f"|format(net) }}</h2>
        </div>
        <h4 class="section-title">🔍 المسح الفوري (العملات المرشحة)</h4>
        <table>
            <tr><th>العملة</th><th>السعر الحالي</th><th>السكور</th><th>تغير 24h</th></tr>
            {% for item in scan %}
            <tr>
                <td><b>{{ item.sym.split('/')[0] }}</b></td>
                <td class="price-val">${{ item.pr }}</td>
                <td><span class="score-badge">{{ item.sc }}</span></td>
                <td class="up">{{ item.ch }}%</td>
            </tr>
            {% endfor %}
        </table>
        <h4 class="section-title">📍 الصفقات المفتوحة</h4>
        <table>
            <tr><th>العملة</th><th>دخول</th><th>حالي</th><th>الربح %</th></tr>
            {% for t in active %}
            {% set p = ((t.current_price - t.entry_price) / t.entry_price) * 100 %}
            <tr>
                <td><b>{{ t.symbol }}</b></td>
                <td>${{ "%.4f"|format(t.entry_price) }}</td>
                <td class="price-val">${{ "%.4f"|format(t.current_price) }}</td>
                <td class="{{ 'up' if p >= 0 else 'down' }}" style="font-weight:bold;">{{ "%.2f"|format(p) }}%</td>
            </tr>
            {% endfor %}
        </table>
    </body></html>
    """, net=net_val, active=active_trades, scan=last_scan_results[:5])

async def trading_engine():
    global last_scan_results
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            tickers = await exchange.fetch_tickers()
            conn = get_db_connection()
            temp_scan = []
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute("SELECT * FROM trades")
                active_trades = cur.fetchall()
                active_symbols = [x['symbol'] for x in active_trades]
                for t in active_trades:
                    if t['symbol'] in tickers:
                        new_p = float(tickers[t['symbol']]['last'])
                        cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (new_p, t['symbol']))
                for sym, data in tickers.items():
                    if '/USDT' in sym:
                        score = calculate_trade_score(data)
                        if score > 30:
                            temp_scan.append({'sym': sym, 'sc': score, 'ch': data.get('percentage', 0), 'pr': data.get('last')})
                        if score >= ENTRY_SCORE_THRESHOLD and len(active_symbols) < MAX_TRADES and sym not in active_symbols:
                            p = float(data['last'])
                            cur.execute("INSERT INTO trades (symbol, entry_price, current_price, investment, open_time, entry_score) VALUES (%s, %s, %s, %s, %s, %s)",
                                       (sym, p, p, INVESTMENT_PER_TRADE, datetime.now().strftime('%H:%M'), score))
                            active_symbols.append(sym)
                last_scan_results = sorted(temp_scan, key=lambda x: x['sc'], reverse=True)
                conn.commit(); cur.close(); conn.close()
            await asyncio.sleep(15)
        except: 
            await asyncio.sleep(15)

if __name__ == "__main__":
    threading.Thread(target=lambda: asyncio.run(trading_engine()), daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
