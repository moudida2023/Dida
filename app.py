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

# استخدام مسار ثابت ومضمون
CSV_PATH = "/tmp/live_trading_v91.csv"
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

data_lock = threading.Lock()

# --- دالة مزامنة البيانات (معدلة لضمان الظهور الفوري) ---
def sync_data(symbol, price, score, is_new=False):
    headers = ['Symbol', 'Time', 'Entry', 'Current', 'Score']
    with data_lock:
        try:
            # 1. إنشاء الملف إذا لم يكن موجوداً
            if not os.path.exists(CSV_PATH):
                with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerow(headers)

            # 2. قراءة البيانات الحالية
            df = pd.read_csv(CSV_PATH)
            
            # 3. إذا كانت العملة موجودة، حدث السعر والسكور
            if symbol in df['Symbol'].values:
                df.loc[df['Symbol'] == symbol, 'Current'] = f"{price:.4f}"
                df.loc[df['Symbol'] == symbol, 'Score'] = score
                df.to_csv(CSV_PATH, index=False)
                return False
            
            # 4. إذا كانت عملة جديدة (وسكورها يسمح)، أضفها
            elif is_new:
                with open(CSV_PATH, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([symbol, datetime.now().strftime('%H:%M:%S'), f"{price:.4f}", f"{price:.4f}", score])
                return True
        except Exception as e:
            print(f"❌ خطأ في الملف: {e}")
        return False

# --- محرك البحث المطور ---
async def market_engine():
    exchange = ccxt.binance({'enableRateLimit': True})
    sent_list = set()

    while True:
        try:
            tickers = await exchange.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                await asyncio.sleep(0.001)
                price = tickers[sym].get('last', 0)
                change = tickers[sym].get('percentage', 0)
                
                # حساب السكور
                if change > 3: score = 85
                elif change > 1.5: score = 65
                else: score = 0

                # التنفيذ بناءً على السكور
                if score >= 60:
                    # إضافة للملف (ستظهر في الموقع)
                    if sync_data(sym, price, score, is_new=True):
                        # إرسال تليجرام إذا وصل 85
                        if score >= 85 and sym not in sent_list:
                            threading.Thread(target=lambda: requests.post(
                                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                json={"chat_id": TELEGRAM_CHAT_ID, "text": f"🚀 إشارة: {sym}\n💰 السعر: {price}\n📊 السكور: {score}"}
                            )).start()
                            sent_list.add(sym)
                else:
                    # تحديث السعر فقط إذا كانت مسجلة مسبقاً
                    sync_data(sym, price, score, is_new=False)

            await asyncio.sleep(15)
        except Exception as e:
            await asyncio.sleep(10)

# --- واجهة الموقع (مصلحة لعرض البيانات فوراً) ---
@app.route('/')
def index():
    try:
        if not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) < 20:
            return "<body style='background:#0b0e11;color:white;text-align:center;'><h2>🔎 جاري فحص السوق.. انتظر ظهور أول عملة</h2></body>"
        
        with data_lock:
            df = pd.read_csv(CSV_PATH)
        
        # التأكد من أن البيانات ليست فارغة
        if df.empty:
            return "<body style='background:#0b0e11;color:white;text-align:center;'><h2>🔎 السوق هادئ حالياً.. بانتظار حركة</h2></body>"

        rows = ""
        # عرض آخر 20 عملة (الأحدث بالأعلى)
        for _, r in df.iloc[::-1].head(20).iterrows():
            entry_p = float(r['Entry'])
            curr_p = float(r['Current'])
            color_p = "#00ff00" if curr_p >= entry_p else "#ff4444"
            
            rows += f"""<tr style="border-bottom:1px solid #2b3139;">
                <td style="padding:12px; color:#f0b90b;"><b>{r['Symbol']}</b></td>
                <td style="color:#848e9c;">{r['Time']}</td>
                <td>{entry_p:.4f}</td>
                <td style="color:{color_p}; font-weight:bold;">{curr_p:.4f}</td>
                <td><span style="background:#363a45; padding:2px 10px; border-radius:10px;">{r['Score']}</span></td>
            </tr>"""

        return f"""<html><head><meta http-equiv="refresh" content="10">
        <style>
            body{{background:#0b0e11; color:white; font-family:sans-serif; text-align:center; padding:20px;}}
            table{{width:95%; margin:auto; background:#1e2329; border-collapse:collapse; border-radius:10px; overflow:hidden;}}
            th{{background:#2b3139; color:#848e9c; padding:15px; text-align:center;}}
            td{{padding:10px; text-align:center;}}
        </style></head>
        <body>
            <h2 style="color:#f0b90b;">📊 رادار التداول المباشر v91</h2>
            <table>
                <thead><tr><th>الرمز</th><th>الوقت</th><th>الدخول</th><th>الحالي</th><th>السكور</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </body></html>"""
    except Exception as e:
        return f"خطأ في عرض الصفحة: {e}"

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080, use_reloader=False)).start()
    asyncio.get_event_loop().run_until_complete(market_engine())
