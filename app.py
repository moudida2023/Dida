import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import requests
import csv
from flask import Flask, send_file
from datetime import datetime

app = Flask(__name__)

# إعدادات الملف والبيانات
CSV_FILE = "trading_log.csv"
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# السكور الجديد المطلوب (60)
SCORE_LIMIT = 60 

data_lock = threading.Lock()

# --- دالة الكتابة المباشرة في CSV ---
def force_write_csv(row_data):
    headers = ['Symbol', 'Time', 'Entry', 'Current', 'TP', 'SL', 'Score']
    with data_lock:
        try:
            file_exists = os.path.isfile(CSV_FILE)
            with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row_data)
        except Exception as e:
            print(f"❌ CSV Write Error: {e}")

# --- دالة تحديث السعر حياً في الملف ---
def update_csv_price(symbol, current_price):
    with data_lock:
        try:
            if os.path.exists(CSV_FILE):
                df = pd.read_csv(CSV_FILE)
                if symbol in df['Symbol'].values:
                    df.loc[df['Symbol'] == symbol, 'Current'] = f"{current_price:.4f}"
                    df.to_csv(CSV_FILE, index=False)
        except:
            pass

# --- وظيفة إرسال التنبيه ---
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except:
        pass

# --- المحرك الرئيسي (Engine) ---
async def market_engine():
    EXCHANGE = ccxt.binance({'enableRateLimit': True})
    recorded_symbols = set()
    
    # تحميل البيانات السابقة لمنع التكرار
    if os.path.exists(CSV_FILE):
        try:
            df = pd.read_csv(CSV_FILE)
            recorded_symbols = set(df['Symbol'].tolist())
        except: pass

    print(f"🚀 الرادار يعمل الآن بحد أدنى للسكور: {SCORE_LIMIT}")

    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                price = tickers[sym].get('last', 0)
                change = tickers[sym].get('percentage', 0)
                
                # تحديث الأسعار للعملات المسجلة
                if sym in recorded_symbols:
                    update_csv_price(sym, price)

                # منطق السكور (معدل ليبدأ من 60)
                # صعود 1.5% يعطي سكور 65، صعود 3% يعطي سكور 85
                current_score = 90 if change > 4 else (70 if change > 2 else (65 if change > 1.5 else 0))
                
                if current_score >= SCORE_LIMIT and sym not in recorded_symbols:
                    row = {
                        'Symbol': sym,
                        'Time': datetime.now().strftime('%H:%M:%S'),
                        'Entry': price,
                        'Current': price,
                        'TP': price * 1.05,
                        'SL': price * 0.97,
                        'Score': current_score
                    }
                    
                    force_write_csv(row)
                    recorded_symbols.add(sym)
                    
                    msg = f"🔔 *إشارة دخول (Score: {current_score})*\n💎 العملة: `{sym}`\n💰 السعر: `{price:.4f}`"
                    threading.Thread(target=send_telegram, args=(msg,)).start()

            await asyncio.sleep(15)
        except Exception as e:
            print(f"⚠️ Error: {e}")
            await asyncio.sleep(10)

# --- الواجهة البرمجية (Flask) ---
@app.route('/')
def home():
    if not os.path.exists(CSV_FILE):
        return "<h1>البحث جارٍ عن عملات بسكور 60+...</h1>"
    
    with data_lock:
        df = pd.read_csv(CSV_FILE)
        rows = ""
        for _, r in df.iloc[::-1].iterrows():
            color = "#00ff00" if float(r['Current']) >= float(r['Entry']) else "#ff4444"
            rows += f"""<tr style="border-bottom: 1px solid #2b3139;">
                <td style="color:#f0b90b; padding:12px;"><b>{r['Symbol']}</b></td>
                <td>{r['Time']}</td>
                <td>{r['Entry']}</td>
                <td style="color:{color};">{r['Current']}</td>
                <td><span style="background:#2b3139; padding:2px 8px; border-radius:5px;">{r['Score']}</span></td>
            </tr>"""
    
    return f"""<html><head><meta http-equiv="refresh" content="20">
    <style>body{{background:#0b0e11;color:white;text-align:center;font-family:sans-serif;}} table{{width:90%;margin:auto;background:#1e2329;border-collapse:collapse;}} th{{padding:10px;color:#848e9c;}}</style>
    </head><body>
        <h2>📊 رادار التداول v86 (السكور 60+)</h2>
        <table><thead><tr><th>العملة</th><th>الوقت</th><th>دخول</th><th>حالي</th><th>السكور</th></tr></thead>
        <tbody>{rows}</tbody></table><br>
        <a href="/download" style="color:#f0b90b; text-decoration:none; border:1px solid #f0b90b; padding:5px 10px; border-radius:5px;">📥 تحميل ملف CSV</a>
    </body></html>"""

@app.route('/download')
def download():
    return send_file(CSV_FILE, as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(market_engine())
