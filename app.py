import os
import requests
import threading
import time
from datetime import datetime

# --- تعديل وظيفة النبض الذاتي لتكون "محصنة" ---
def self_ping_program():
    # محاولة جلب الرابط من البيئة
    app_url = os.environ.get('APP_URL')
    
    # إذا كان الرابط غير موجود، سننتظر قليلاً ثم نحاول مرة أخرى (ربما لم يتم تحميله بعد)
    if not app_url:
        print("⚠️ تحذير: APP_URL غير معرف حالياً. سيعمل البوت ولكن بدون ميزة 'منع النوم'.")
        return

    print(f"🚀 تم تفعيل برنامج النبض الذاتي للرابط: {app_url}")
    
    while True:
        try:
            # إرسال طلب للموقع لإبقائه مستيقظاً
            response = requests.get(app_url, timeout=30)
            print(f"📡 نبضة ناجحة [{datetime.now().strftime('%H:%M:%S')}] - الحالة: {response.status_code}")
        except Exception as e:
            print(f"🚨 تنبيه: فشل النبض الذاتي (قد يكون السيرفر في حالة تحديث): {e}")
        
        # الانتظار 4 دقائق بين كل نبضة
        time.sleep(240)
