import os
import threading
import time
import requests
import asyncio
import psycopg2
from flask import Flask, render_template_string
from datetime import datetime

app = Flask(__name__)

# --- 1. إعدادات البيئة المحصنة ---
DB_URL = os.environ.get('DATABASE_URL')
APP_URL = os.environ.get('APP_URL') # تأكد من إضافته في Render

def get_db_connection():
    try:
        # تحويل الرابط إذا كان قديماً
        url = DB_URL.replace("postgres://", "postgresql://", 1) if DB_URL and DB_URL.startswith("postgres://") else DB_URL
        return psycopg2.connect(url, sslmode='require', connect_timeout=10)
    except:
        return None

# --- 2. برنامج النبض الذاتي (Keep-Alive) المعدل ---
def self_ping_program():
    """هذه الوظيفة تعمل في الخلفية ولا تعطل التطبيق حتى لو فشلت"""
    time.sleep(30) # انتظر حتى يستقر السيرفر
    while True:
        if APP_URL:
            try:
                requests.get(APP_URL, timeout=20)
                print(f"📡 [Keep-Alive] نبضة ناجحة في {datetime.now().strftime('%H:%M:%S')}")
            except Exception as e:
                print(f"⚠️ [Keep-Alive] السيرفر لم يستجب بعد: {e}")
        else:
            print("❌ [Keep-Alive] APP_URL مفقود. يرجى إضافته في Environment Variables.")
            # لا ننهي البرنامج، بل ننتظر ربما يتم إضافة الرابط لاحقاً
        
        time.sleep(240) # 4 دقائق

# --- 3. مسار Flask الرئيسي (لإبقاء التطبيق حياً) ---
@app.route('/')
def home():
    # محاولة سريعة لفحص الداتابيز عند الزيارة
    db_status = "❌ غير متصل"
    try:
        conn = get_db_connection()
        if conn:
            db_status = "✅ متصل وجاهز"
            conn.close()
    except: pass
    
    return render_template_string("""
    <body style="background:#0b0e11; color:white; font-family:sans-serif; text-align:center; padding:50px;">
        <h1 style="color:#0ecb81;">🛡️ نظام التشغيل المستمر v165</h1>
        <div style="background:#1e2329; display:inline-block; padding:20px; border-radius:10px;">
            <p>حالة قاعدة البيانات: <b>{{ db_status }}</b></p>
            <p>رابط النبض: <code style="color:#f0b90b;">{{ url }}</code></p>
        </div>
        <p style="color:#848e9c; margin-top:20px;">إذا ظهرت هذه الصفحة، فإن التطبيق لن يخرج (No Early Exit).</p>
    </body>
    """, db_status=db_status, url=APP_URL)

# --- 4. نقطة الانطلاق الصحيحة ---
if __name__ == "__main__":
    # أ. تشغيل النبض الذاتي في "خيط منفصل" (Daemon Thread)
    # ملاحظة: daemon=True تضمن أن الخيط لا يمنع إغلاق البرنامج إذا لزم الأمر
    ping_thread = threading.Thread(target=self_ping_program, daemon=True)
    ping_thread.start()
    
    print("💎 جميع برامج الاستقرار تعمل في الخلفية...")
    
    # ب. تشغيل Flask (هذا هو السطر الذي يمنع الـ Early Exit)
    # يجب أن يكون هذا السطر هو الأخير
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
