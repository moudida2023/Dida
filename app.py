import asyncio
import ccxt.pro as ccxt
import pandas as pd
import psycopg2
from psycopg2 import extras
import os
import threading
from flask import Flask, render_template_string
from datetime import datetime

# ======================== 1. الإعدادات والربط ========================
app = Flask(__name__)

DB_URL = os.environ.get('DATABASE_URL')
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

INITIAL_BALANCE = 500.0 # الرصيد الافتراضي كما طلبت

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

# ======================== 2. محرك إدارة الصفقات والمحفظة v159 ========================

async def main_engine():
    # إعادة تهيئة الجدول مع إضافة عمود الاستثمار
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS trades")
        cur.execute('''CREATE TABLE trades 
            (symbol TEXT PRIMARY KEY, entry_price REAL, current_price REAL, 
             tp REAL, sl REAL, score INTEGER, open_time TEXT, 
             investment REAL, status TEXT)''')
        conn.commit()
        cur.close(); conn.close()
    except: pass

    EXCHANGE = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            # فحص العملات الأكثر سيولة في USDT
            valid_symbols = [s for s in tickers if '/USDT' in s]
            top_symbols = sorted(valid_symbols, key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:50]
            
            conn = get_db_connection()
            cur = conn.cursor()

            for sym in top_symbols:
                price = tickers[sym]['last']
                # حساب أهداف ذكية: ربح 2% ووقف 3%
                tp_price = price * 1.02
                sl_price = price * 0.97
                
                # إدخال الصفقات (محاكاة دخول بمبلغ 50 دولار لكل صفقة)
                cur.execute("""INSERT INTO trades (symbol, entry_price, current_price, tp, sl, score, open_time, investment, status) 
                               VALUES (%s, %s, %s, %s, %s, 85, %s, 50.0, 'OPEN') 
                               ON CONFLICT (symbol) DO UPDATE SET current_price = EXCLUDED.current_price""", 
                            (sym, price, price, tp_price, sl_price, datetime.now().strftime('%H:%M:%S')))
            
            conn.commit()
            cur.close(); conn.close()
            await asyncio.sleep(8) 
        except Exception as e:
            await asyncio.sleep(10)

# ======================== 3. واجهة المحفظة والصفقات ========================

@app.route('/')
def index():
    trades = []
    total_unrealized_pnl = 0
    active_investments = 0
    
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        trades = cur.fetchall()
        cur.close(); conn.close()
        
        # حساب إحصائيات المحفظة
        for t in trades:
            pnl = ((t['current_price'] - t['entry_price']) / t['entry_price']) * t['investment']
            total_unrealized_pnl += pnl
            active_investments += t['investment']
    except: pass

    html = """
    <!DOCTYPE html><html lang="ar"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="5">
    <title>Portfolio Manager v159</title>
    <style>
        body { background: #0b0e11; color: white; font-family: 'Segoe UI', sans-serif; padding: 20px; direction: rtl; }
        .dashboard { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: #1e2329; padding: 20px; border-radius: 12px; border-bottom: 4px solid #f0b90b; text-align: center; }
        .stat-val { font-size: 24px; font-weight: bold; margin-top: 10px; }
        .profit { color: #0ecb81; } .loss { color: #f6465d; }
        table { width: 100%; border-collapse: collapse; background: #1e2329; border-radius: 12px; overflow: hidden; }
        th { background: #2b3139; color: #848e9c; padding: 15px; font-size: 13px; text-align: center; }
        td { padding: 15px; text-align: center; border-bottom: 1px solid #2b3139; }
        .symbol-tag { background: #474d57; padding: 4px 8px; border-radius: 6px; font-weight: bold; }
    </style></head><body>
        <div style="max-width: 1200px; margin: auto;">
            <h1 style="color: #f0b90b;">🛰️ رادار الصفقات وحالة المحفظة</h1>
            
            <div class="dashboard">
                <div class="stat-card">
                    <div style="color: #848e9c;">الرصيد الافتراضي</div>
                    <div class="stat-val">${{ "%.2f"|format(500 + total_unrealized_pnl) }}</div>
                </div>
                <div class="stat-card">
                    <div style="color: #848e9c;">إجمالي الأرباح/الخسائر</div>
                    <div class="stat-val {{ 'profit' if total_unrealized_pnl >= 0 else 'loss' }}">
                        {{ "%+.2f"|format(total_unrealized_pnl) }} USDT
                    </div>
                </div>
                <div class="stat-card">
                    <div style="color: #848
