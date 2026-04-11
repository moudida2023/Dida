import os
import threading
import asyncio
import psycopg2
from psycopg2 import extras
import ccxt.pro as ccxt
from flask import Flask, render_template_string
from datetime import datetime

app = Flask(__name__)

# --- إعدادات قاعدة البيانات (الرابط الخارجي الموثوق) ---
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a.frankfurt-postgres.render.com/trading_bot_db_wv1h"

def get_db_connection():
    try:
        # ضروري جداً: استخدام sslmode=require للاتصال بقواعد Render الخارجية
        conn = psycopg2.connect(DB_URL, sslmode='require', connect_timeout=10)
        return conn
    except Exception as e:
        print(f"❌ DATABASE ERROR: {e}")
        return None

# --- تهيئة الجداول عند أول تشغيل ---
def init_db():
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS trades 
            (symbol TEXT PRIMARY KEY, entry_price DOUBLE PRECISION, current_price DOUBLE PRECISION, 
             tp_price DOUBLE PRECISION, sl_price DOUBLE PRECISION, investment DOUBLE PRECISION, open_time TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS closed_trades 
            (id SERIAL PRIMARY KEY, symbol TEXT, entry_price DOUBLE PRECISION, exit_price DOUBLE PRECISION, 
             pnl DOUBLE PRECISION, exit_reason TEXT, close_time TEXT)''')
        conn.commit()
        cur.close(); conn.close()
        print("✅ Database Tables Verified/Created.")

# --- محرك التداول (يعمل في الخلفية) ---
async def trading_engine():
    init_db()
    exchange = ccxt.gateio({'enableRateLimit': True})
    print("🚀 Trading Engine is Online...")
    
    while True:
        try:
            conn = get_db_connection()
            if not conn:
                await asyncio.sleep(20); continue
            
            # هنا يمكنك إضافة منطق فتح وإغلاق الصفقات الفعلي
            # حالياً البوت سيقوم بطباعة رسالة تأكيد الاتصال فقط في الـ Logs
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚙️ Engine: Connection Active")
            
            conn.close()
            await asyncio.sleep(60) 
        except Exception as e:
            print(f"⚠️ Engine Loop Error: {e}")
            await asyncio.sleep(20)

# --- الواجهة الرسومية ---
HTML_PAGE = """
<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="20">
<title>Radar v400</title>
<style>
    body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding-top: 50px; }
    .status-box { background: #1e2329; padding: 30px; display: inline-block; border-radius: 12px; border: 1px solid #2b3139; }
    .status-on { color: #0ecb81; font-weight: bold; }
    .status-off { color: #f6465d; font-weight: bold; }
</style></head><body>
    <div class="status-box">
        <h2 style="color:#f0b90b;">🛰️ نظام الرصد v400</h2>
        <p>حالة قاعدة البيانات: <span class="{{ 'status-on' if db_ok else 'status-off' }}">{{ '🟢 متصلة' if db_ok else '🔴 غير متصلة' }}</span></p>
        <p>توقيت السيرفر: {{ now }}</p>
        <hr style="border:0; border-top:1px solid #2b3139;">
        <p style="font-size:12px; color:#848e9c;">افحص شاشة Logs في Render للتفاصيل التقنية.</p>
    </div>
</body></html>
"""

@app.route('/')
def index():
    conn = get_db_connection()
    db_ok = True if conn else False
    if conn: conn.close()
    
    print(f"🌐 Dashboard Access: DB Status {'OK' if db_ok else 'FAILED'}")
    return render_template_string(HTML_PAGE, db_ok=db_ok, now=datetime.now().strftime('%H:%M:%S'))

if __name__ == "__main__":
    # تشغيل محرك التداول في خيط منفصل
    t = threading.Thread(target=lambda: asyncio.run(trading_engine()))
    t.daemon = True
    t.start()
    
    # تشغيل تطبيق Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
