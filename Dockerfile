# 1. استخدام نسخة خفيفة ومستقرة من بايثون
FROM python:3.9-slim

# 2. تحديد مجلد العمل داخل السيرفر
WORKDIR /app

# 3. تثبيت أدوات النظام الضرورية (للتعامل مع العمليات الحسابية)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 4. نسخ ملف المتطلبات أولاً لتسريع عملية البناء
COPY requirements.txt .

# 5. تثبيت المكتبات البرمجية
RUN pip install --no-cache-dir -r requirements.txt

# 6. نسخ باقي ملفات المشروع (بما فيها app.py) إلى السيرفر
COPY . .

# 7. فتح المنفذ 10000 (الذي يستخدمه Render غالباً)
EXPOSE 10000

# 8. أمر تشغيل البوت
CMD ["python", "app.py"]
