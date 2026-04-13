# استخدام نسخة بايثون خفيفة ومستقرة
FROM python:3.10-slim

# منع بايثون من إنشاء ملفات .pyc وتأخير إخراج البيانات (Logs)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# تحديد مجلد العمل داخل السيرفر
WORKDIR /app

# تثبيت الأدوات اللازمة للنظام
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# نسخ ملف المتطلبات أولاً لتسريع عملية البناء
COPY requirements.txt .

# تثبيت المكتبات البرمجية
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات الكود إلى السيرفر
COPY . .

# أمر تشغيل البوت (افترضنا أن اسم ملف الكود هو bot.py)
CMD ["python", "app.py"]
