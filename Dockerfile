# 1. استخدام نسخة خفيفة ومستقرة من بايثون
FROM python:3.10-slim

# 2. تعيين مجلد العمل داخل الحاوية
WORKDIR /app

# 3. تثبيت أدوات النظام الضرورية (لضمان عمل pandas و ccxt)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 4. نسخ ملف المتطلبات وتثبيته
# تأكد من وجود ملف requirements.txt بجانب الـ Dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. نسخ جميع ملفات المشروع إلى الحاوية
COPY . .

# 6. تعيين المتغيرات البيئية (اختياري لضمان عدم تخزين ملفات pyc)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 7. فتح المنفذ الذي يستخدمه Flask
EXPOSE 8080

# 8. أمر التشغيل (تأكد أن اسم ملفك البرمجي هو main.py أو استبدله بالاسم الصحيح)
CMD ["python", "app.py"]
