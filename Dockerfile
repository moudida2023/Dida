Aucun élément sélectionné 

Aller au contenu
Utiliser Gmail avec un lecteur d'écran
Activez les notifications sur le bureau pour Gmail.
   OK  Non, merci
Conversations
63 % sur 15 Go utilisés
Conditions d'utilisation · Confidentialité · Règlement du programme
Dernière activité sur le compte : il y a 2 heures
Détails
# 1. استخدام نسخة خفيفة ومستقرة من بايثون
FROM python:3.10-slim

# 2. تعيين مجلد العمل داخل الحاوية (Container)
WORKDIR /app

# 3. تثبيت أدوات النظام الضرورية لعمل المكتبات (مثل pandas و numpy)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 4. نسخ ملف المكتبات أولاً للاستفادة من الـ Caching وتسريع البناء
COPY requirements.txt .

# 5. تثبيت المكتبات البرمجية
RUN pip install --no-cache-dir -r requirements.txt

# 6. نسخ بقية ملفات المشروع (الكود) إلى الحاوية
COPY . .

# 7. تعيين المنفذ الافتراضي (Render يستخدم PORT تلقائياً)
ENV PORT=10000
EXPOSE 10000

# 8. أمر التشغيل النهائي للبوت
CMD ["python", "app.py"]

Dockerfile (2).txt
Affichage de dockerignore (2).txt en cours...
