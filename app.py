import os
import requests
from flask import Flask
import threading
import time

app = Flask(__name__)

# CONFIGURATION
TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
CHAT_ID = '5067771509'

def send_test():
    # Attendre 10 secondes que le serveur soit bien lancé
    time.sleep(10)
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": "✅ Bot v599 en ligne sur Render !"}, timeout=10)
        print(f"Statut Telegram: {r.status_code}")
    except Exception as e:
        print(f"Erreur envoi: {e}")

@app.route('/')
def home():
    return "Bot en ligne"

if __name__ == "__main__":
    # Lancer le test d'envoi dans un thread séparé
    threading.Thread(target=send_test).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
