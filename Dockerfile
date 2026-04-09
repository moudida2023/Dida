# استخدام نسخة خفيفة من بايثون
FROM python:3.9-slim

# تحديد مجلد العمل داخل الحاوية
WORKDIR /app

# تثبيت الأدوات اللازمة للنظام (اختياري لضمان استقرار بعض المكتبات)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# نسخ ملف المكتبات أولاً للاستفادة من خاصية الـ Cache في Docker
COPY requirements.txt .

# تثبيت مكتبات بايثون
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع إلى الحاوية
COPY . .

# تحديد المنفذ الذي سيعمل عليه Flask (الافتراضي 10000 كما في كودك)
EXPOSE 10000

# الأمر النهائي لتشغيل البوت
CMD ["python", "main.py"]
