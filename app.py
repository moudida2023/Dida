import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import csv
import requests
from flask import Flask, send_file
from datetime import datetime

app = Flask(__name__)

# إعدادات المسارات
CSV_PATH = "/tmp/elite_signals_v90.csv"
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# إعدادات السكور الجديدة
WEB_DISPLAY_LIMIT = 60      # تظهر في الموقع من سكور 60
TELEGRAM_ALERT_LIMIT = 85   # ترسل لتليجرام من سكور 85 (طلبك الحالي)

data_lock = threading.Lock()

# --- دالة مزامنة البيانات ---
def sync_trading_data(symbol, price, score, is_new=False):
    headers = ['Symbol', 'Time', 'Entry', 'Current', 'Score']
    with data_lock:
        try:
            if not os.path.exists(CSV_PATH):
                with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerow(headers)

            df = pd.read_csv(CSV_PATH)
            
            if symbol in df['Symbol'].values:
                # تحديث السعر والسكور في الملف باستمرار
                df.loc[df['Symbol'] == symbol, 'Current'] = f"{price:.4f}"
                df.loc[df['Symbol'] == symbol, 'Score'] = score
                df.to_csv(CSV_PATH, index=False)
                return False
            elif is_new:
                # تسجيل إشارة جديدة
                new_row = [symbol, datetime.now().strftime('%H:%M:%S'), f"{price:.4f}", f"{price:.4f}", score]
                with open(CSV_PATH, 'a', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerow(new_row)
                return True
        except Exception as e:
            print(f"Sync Error: {e}")
        return False

# --- وظيفة إرسال التنبيه (85+) ---
def send_telegram_notification(sym, price, score):
    msg = (f"🚀 *إشارة سكور مرتفع: {score}*\n\n"
           f"💎 العملة: `{sym}`\n"
           f"💰 الدخول: `{price:.4f}`\n"
           f"📊 الحالة: تجاوزت حد الـ {TELEGRAM_ALERT_LIMIT}")
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

# --- المحرك الرئيسي ---
async def market_engine():
    exchange = ccxt.binance({'enableRateLimit': True})
    sent_list = set() # لمنع تكرار الإرسال

    print(f"📡 الرادار يعمل.. تنبيهات تليجرام مفعّلة للسكور {TELEGRAM_ALERT_LIMIT}+")

    while True:
        try:
            tickers = await exchange.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                await asyncio.sleep(0.001)
                price = tickers[sym].get('last', 0)
                change = tickers[sym].get('percentage', 0)
                
                # حساب السكور المحدث
                if change > 4.5: score = 95
                elif change > 3: score = 85
                elif change > 2: score = 75
                elif change > 1.2: score = 60
                else: score = 0

                # 1. تحديث الموقع
                if score >= WEB_DISPLAY_LIMIT:
                    sync_trading_data(sym, price, score, is_new=True)
                    
                    # 2. إرسال تليجرام إذا حقق الشرط الجديد (85)
                    if score >= TELEGRAM_ALERT_LIMIT and sym not in sent_list:
                        threading.Thread(target=send_telegram_notification, args=(sym, price, score)).start()
                        sent_list.add(sym)
                else:
                    sync_trading_data(sym, price, score, is_new=False)

            await asyncio.sleep(15)
        except Exception as e:
            print(f"Scanner Error: {e}")
            await asyncio.sleep(10)

# --- واجهة الموقع ---
@app.route('/')
def index():
    if not os.path.exists(CSV_PATH):
        return "<body style='background:#0b0e11;color:white;text-align:center;'><h2>جاري المسح.. بانتظار سكور 60+</h2></body>"
    
    with data_lock:
        df = pd.read_csv(CSV_PATH)
    
    rows = ""
    for _, r in df.iloc[::-1].iterrows():
        # تمييز عملات الـ 85+ بلون ذهبي
        style = "background:#2d2610;" if r['Score'] >= 85 else ""
        color_p = "#00ff00" if float(r['Current']) >= float(r['Entry']) else "#ff4444"
        
        rows += f"""<tr style="border-bottom:1px solid #2b3139; {style}">
            <td style="padding:12px; color:#f0b90b;"><b>{r['Symbol']}</b></td>
            <td>{r['Time']}</td>
            <td>{r['Entry']}</td>
            <td style="color:{color_p}; font-weight:bold;">{r['Current']}</td>
            <td><span style="background:#363a45; padding:2px 10px; border-radius:10px;">{r['Score']}</span></td>
        </tr>"""

    return f"""<html><head><meta http-equiv="refresh" content="15"></head>
    <body style="background:#0b0e11;color:white;font-family:sans-serif;text-align:center;padding:20px;">
        <h2 style="color:#f0b90b;">🚀 رادار الصفقات v90 (Score 85+)</h2>
        <table style="width:95%; margin:auto; background:#1e2329; border-collapse:collapse; border-radius:10px; overflow:hidden;">
            <thead style="background:#2b3139; color:#848e9c;">
                <tr><th>الرمز</th><th>وقت الرصد</th><th>سعر الدخول</th><th>السعر الحالي</th><th>السكور</th></tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
    </body></html>"""

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    asyncio.get_event_loop().run_until_complete(market_engine())
