# استخدام نسخة بايثون مستقرة وخفيفة
FROM python:3.10-slim

# تثبيت أدوات النظام الضرورية لبناء المكتبات (مثل pandas و numpy)
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# تحديد مجلد العمل داخل الحاوية
WORKDIR /app

# تحديث pip أولاً لتجنب مشاكل الإصدارات القديمة
RUN pip install --no-cache-dir --upgrade pip

# نسخ ملف المتطلبات وتثبيته
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ ملفات المشروع (main.py و trading_state.json إذا وجد)
COPY . .

# أمر تشغيل البوت
CMD ["python", "app.py"]
