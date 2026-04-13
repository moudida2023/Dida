# استخدام نسخة بايثون مستقرة
FROM python:3.10-slim

# تثبيت أدوات النظام الضرورية لبناء المكتبات (مثل pandas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# تحديد مجلد العمل
WORKDIR /app

# نسخ ملف المتطلبات وتثبيته
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# نسخ باقي الكود
COPY . .

# تشغيل البوت
CMD ["python", "app.py"]
