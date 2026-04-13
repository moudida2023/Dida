
# استخدام نسخة بايثون خفيفة ومستقرة
FROM python:3.10-slim

# تثبيت الأدوات اللازمة للتعامل مع PostgreSQL داخل النظام
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# تحديد مجلد العمل داخل الحاوية
WORKDIR /app

# نسخ ملف المكتبات أولاً لتسريع عملية البناء
COPY requirements.txt .

# تثبيت مكتبات بايثون
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع إلى الحاوية
COPY . .

# تحديد المنفذ (Port) الذي سيعمل عليه Flask
EXPOSE 10000

# أمر تشغيل البوت
CMD ["python", "app.py"]
