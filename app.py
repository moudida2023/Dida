import os
import threading
import asyncio
import ccxt.pro as ccxt
import psycopg2
from psycopg2 import extras
from flask import Flask, render_template_string
from datetime import datetime

app = Flask(__name__)

# --- الإعدادات ---
DB_URL = "postgresql://trading_bot_db_wv1h_user:IhfQrnLavCH3oULKVq5FeVngBqzL5eOP@dpg-d7cl24navr4c738vnis0-a/trading_bot_db_wv1h"
status_db = "🔴"
status_ex = "🔴"

def get_db_connection():
    global status_db
    try:
        url = DB_URL.replace("postgres://", "postgresql://", 1) if DB_URL.startswith("postgres://") else DB_URL
        conn = psycopg2.connect(url, connect_timeout=5)
        status_db = "🟢"
        return conn
    except Exception as e:
        status_db = "🔴"
        print(f"!!! DATABASE ERROR: {e}") # سيظهر في الـ Logs
        return None

async def trading_engine():
    global status_ex
    exchange = ccxt.gateio({'enableRateLimit': True})
    
    print("🚀 STARTING TRADING ENGINE...") # رسالة بدء المحرك
    
    while True:
        try:
            # 1. فحص الاتصال بالبورصة
            await exchange.load_markets()
            status_ex = "🟢"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Connection to Gate.io: OK")

            # 2. فحص الاتصال بالقاعدة
            conn = get_db_connection()
            if conn:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Connection to DB: OK")
                cur = conn.cursor(cursor_factory=extras.DictCursor)
                
                # تحديث الأسعار (مثال)
                cur.execute("SELECT symbol FROM trades")
                rows = cur.fetchall()
                print(f"📊 Monitoring {len(rows)} active trades.")
                
                cur.close()
                conn.close()
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ DB Connection Failed!")

            await asyncio.sleep(30) # فحص كل 30 ثانية لتجنب ازدحام الـ Logs
            
        except Exception as e:
            status_ex = "🔴"
            print(f"⚠️ ENGINE CRITICAL ERROR: {e}")
            await asyncio.sleep(30)

# --- واجهة الويب ---
@app.route('/')
def index():
    # طباعة رسالة عند كل زيارة للموقع
    print(f"🌐 Website visited at {datetime.now().strftime('%H:%M:%S')}")
    
    html = f"""
    <body style="background:#0b0e11; color:white; font-family:sans-serif; text-align:center; padding:50px;">
        <h1 style="color:#f0b90b;">🛰️ نظام الرصد v340</h1>
        <div style="background:#1e2329; padding:20px; border-radius:10px; display:inline-block;">
            <p>حالة قاعدة البيانات: <b>{status_db}</b></p>
            <p>حالة اتصال البورصة: <b>{status_ex}</b></p>
            <hr>
            <p>افحص شاشة <b>Logs</b> في Render لرؤية تفاصيل العمليات.</p>
        </div>
    </body>
    """
    return render_template_string(html)

if __name__ == "__main__":
    # رسالة عند تشغيل السيرفر لأول مرة
    print("🔥 SERVER BOOTING UP...")
    
    t = threading.Thread(target=lambda: asyncio.run(trading_engine()))
    t.daemon = True
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    print(f"📡 Web server starting on port {port}")
    app.run(host='0.0.0.0', port=port)
