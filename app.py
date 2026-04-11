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

# --- الإعدادات المالية والبرمجية (v630) ---
INITIAL_CAPITAL = 1000.0      # رأس المال الكلي
INVESTMENT_PER_TRADE = 50.0   # قيمة الصفقة الواحدة
MAX_TRADES = 20               # الحد الأقصى لعدد الصفقات
RADAR_THRESHOLD = 70          # سكور الرصد (بدء المراقبة)
ENTRY_SCORE = 85              # سكور الدخول (بدء الصفقة)
TP_PCT = 1.04                 # هدف الربح (4%)
SL_PCT = 0.98                 # وقف الخسارة (2%)

# رابط قاعدة البيانات
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"

def get_db_connection():
    try:
        return psycopg2.connect(str(DB_URL).strip(), sslmode='require', connect_timeout=15)
    except: return None

# --- دالة إغلاق الصفقات (المحرك المالي) ---
def close_position(symbol, exit_price, reason):
    conn = get_db_connection()
    if not conn: return False
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades WHERE symbol = %s", (str(symbol),))
        t = cur.fetchone()
        if t:
            pnl = ((float(exit_price) - float(t['entry_price'])) / float(t['entry_price'])) * INVESTMENT_PER_TRADE
            cur.execute("""INSERT INTO closed_trades (symbol, entry_price, exit_price, pnl, exit_reason, close_time) 
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (str(symbol), float(t['entry_price']), float(exit_price), pnl, str(reason), datetime.now().strftime('%H:%M:%S')))
            cur.execute("UPDATE wallet SET balance = balance + %s WHERE id = 1", (pnl,))
            cur.execute("DELETE FROM trades WHERE symbol = %s", (str(symbol),))
            conn.commit()
        cur.close(); conn.close()
        return True
    except:
        if conn: conn.close()
        return False

# --- نظام الحماية من التوقف (Self-Ping) ---
def keep_alive_monitor():
    while True:
        try:
            url = os.environ.get('RENDER_EXTERNAL_URL')
            if url: requests.get(url, timeout=10)
            else: requests.get("http://127.0.0.1:10000/", timeout=5)
        except: pass
        time.sleep(600) # نبضة كل 10 دقائق

# --- محرك التداول الذكي (Trading Engine) ---
async def trading_engine():
    exchange = ccxt.gateio({'enableRateLimit': True})
    while True:
        try:
            await exchange.load_markets()
            conn = get_db_connection()
            if conn:
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                cur.execute("SELECT * FROM trades")
                active_trades = cur.fetchall()
                if active_trades:
                    tickers = await exchange.fetch_tickers()
                    for t in active_trades:
                        sym = str(t['symbol'])
                        if sym in tickers:
                            curr_p = float(tickers[sym]['last'])
                            entry = float(t['entry_price'])
                            # تنفيذ الخروج الآلي
                            if curr_p >= entry * TP_PCT:
                                close_position(sym, curr_p, "🎯 جني أرباح (4%)")
                            elif curr_p <= entry * SL_PCT:
                                close_position(sym, curr_p, "🛑 وقف خسارة (2%)")
                            else:
                                cur.execute("UPDATE trades SET current_price = %s WHERE symbol = %s", (curr_p, sym))
                conn.commit(); cur.close(); conn.close()
            await asyncio.sleep(15)
        except: await asyncio.sleep(30)

# --- واجهة التحكم الرئيسية ---
@app.route('/')
def index():
    conn = get_db_connection()
    if not conn: return "<h3>⚠️ قاعدة البيانات غير متصلة</h3>", 500
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        ot = cur.fetchall()
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        res_w = cur.fetchone()
        realized_pnl = float(res_w[0]) if res_w else 0.0
        cur.close(); conn.close()

        num_trades = len(ot)
        invested = num_trades * INVESTMENT_PER_TRADE
        unused = (INITIAL_CAPITAL + realized_pnl) - invested
        floating = sum(((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * INVESTMENT_PER_TRADE for t in ot)
        net = INITIAL_CAPITAL + realized_pnl + floating

        return render_template_string("""
        <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="15">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; margin: 0; }
            .card { background: #1e2329; padding: 15px; border-radius: 10px; margin-bottom: 10px; border-bottom: 3px solid #f0b90b; }
            .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 15px; }
            .s-card { background: #1e2329; padding: 10px; border-radius: 8px; font-size: 11px; border: 1px solid #2b3139; }
            .up { color: #0ecb81; } .down { color: #f6465d; }
            .progress-bar { background: #2b3139; height: 10px; border-radius: 5px; margin: 10px 0; overflow: hidden; }
            .progress-fill { background: #f0b90b; height: 100%; width: {{ (count/20)*100 }}%; transition: 0.5s; }
            table { width: 100%; border-collapse: collapse; font-size: 11px; background: #1e2329; }
            th, td { padding: 10px; border: 1px solid #2b3139; text-align: center; }
            th { background: #2b3139; color: #848e9c; }
            .btn-close-all { background: #f6465d; color: white; padding: 12px; border
