# 1. استخدام نسخة خفيفة ومستقرة من بايثون
FROM python:3.10-slim

# 2. تحديد مجلد العمل داخل الحاوية (Container)
WORKDIR /app

# 3. نسخ ملف المتطلبات أولاً (لتحسين سرعة البناء مستقبلاً)
COPY requirements.txt .

# 4. تثبيت المكتبات البرمجية
RUN pip install --no-cache-dir -r requirements.txt

# 5. نسخ جميع ملفات الكود إلى الحاوية
COPY . .

# 6. فتح المنفذ الذي يستخدمه Flask (8080)
EXPOSE 8080

# 7. الأمر النهائي لتشغيل البوت
CMD ["python", "app.py"]
