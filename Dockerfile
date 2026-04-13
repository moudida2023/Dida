# استخدام النسخة الكاملة لتجنب مشاكل بناء pandas و ccxt
FROM python:3.10

# منع بايثون من إنشاء ملفات مؤقتة
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# تحديد مجلد العمل
WORKDIR /app

# نسخ الملفات
COPY requirements.txt .

# تحديث pip وتثبيت المكتبات
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي الكود
COPY . .

# تشغيل البوت
CMD ["python", "app.py"]
