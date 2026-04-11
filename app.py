import time
import requests
import os
import threading
import psycopg2
from psycopg2 import extras
from datetime import datetime

# --- إعدادات النظام ---
APP_URL = os.environ.get('APP_URL')  # رابط موقعك على Render
DB_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    if DB_URL and DB_URL.startswith("postgres://"):
        url = DB_URL.replace("postgres://", "postgresql://", 1)
    else:
        url = DB_URL
    return psycopg2.connect(url, sslmode='require', connect_timeout=10)

# ======================== 1. برنامج النبض الذاتي (Keep-Alive) ========================

def self_ping_program():
    """
    هذا البرنامج يعمل كـ 'قلب' للسيرفر، يرسل نبضات مستمرة لمنع التوقف
    ويتحقق من جودة الاتصال بقاعدة البيانات في كل نبضة.
    """
    print(f"🚀 بدء تشغيل برنامج النبض الذاتي لـ: {APP_URL}")
    
    while True:
        try:
            if APP_URL:
                # إرسال نبضة للموقع
                response = requests.get(APP_URL, timeout=20)
                
                # التحقق من قاعدة البيانات بالتزامن مع النبضة
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM trades")
                count = cur.fetchone()[0]
                cur.close()
                conn.close()
                
                print(f"✅ نبضة ناجحة [{datetime.now().strftime('%H:%M:%S')}] | الحالة: {response.status_code} | صفقات مسترجعة: {count}")
            else:
                print("⚠️ خطأ: APP_URL غير معرف. النبض الذاتي لا يمكنه العمل.")
                
        except Exception as e:
            print(f"🚨 فشل في برنامج النبض أو الداتابيز: {e}")
        
        # الانتظار لمدة 4 دقائق (أقل من فترة الخمول للمنصات المجانية)
        time.sleep(240)

# ======================== 2. نظام مزامنة وجلب المعطيات ========================

def data_sync_monitor():
    """
    وظيفة مخصصة للتأكد من أن البيانات المسترجعة من القاعدة محدثة دائماً
    """
    while True:
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            
            # جلب كافة الصفقات المفتوحة
            cur.execute("SELECT symbol, entry_price, current_price FROM trades")
            trades = cur.fetchall()
            
            if trades:
                print(f"🔄 تم جلب {len(trades)} صفقة بنجاح من قاعدة البيانات.")
            else:
                print("ℹ️ قاعدة البيانات متصلة ولكن لا توجد صفقات مسجلة حالياً.")
                
            cur.close()
            conn.close()
        except Exception as e:
            print(f"❌ خطأ في جلب المعطيات: {e}")
            
        time.sleep(60) # فحص كل دقيقة

# ======================== تشغيل البرامج ========================

if __name__ == "__main__":
    # تشغيل النبض الذاتي في خيط منفصل
    t1 = threading.Thread(target=self_ping_program, daemon=True)
    t1.start()
    
    # تشغيل مراقب البيانات في خيط منفصل
    t2 = threading.Thread(target=data_sync_monitor, daemon=True)
    t2.start()
    
    # هنا يوضع كود Flask الرئيسي لتشغيل السيرفر
    print("💎 جميع برامج الاستقرار تعمل الآن خلف الكواليس.")
    # app.run(...)
