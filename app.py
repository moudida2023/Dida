import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import requests
from flask import Flask, send_file
from datetime import datetime

app = Flask(__name__)

# استخدام مسار محلي للملف لضمان الاستقرار
CSV_FILE = "trading_log.csv"

TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# قفل لمنع تصادم البيانات
data_lock = threading.Lock()

# دالة مخصصة للكتابة المباشرة والقوية في الملف
def force_write_csv(row_data):
    """تضمن كتابة السطر في الملف فوراً"""
    headers = ['Symbol', 'Time', 'Entry', 'Current', 'TP', 'SL', 'Score']
    with data_lock:
        try:
            file_exists = os.path.isfile(CSV_FILE)
            with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
                import csv
                writer = csv.DictWriter(f, fieldnames=headers)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row_data)
            print(f"💾 تم حفظ {row_data['Symbol']} في الملف بنجاح.")
        except Exception as e:
            print(f"❌ فشل الكتابة في الملف: {e}")

# دالة تحديث السعر في الملف (اختياري لكنها تضمن بقاء الملف محدثاً)
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

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except:
        pass

async def market_engine():
    EXCHANGE = ccxt.binance({'enableRateLimit': True})
    recorded_symbols = set()
    
    # تحميل العملات المسجلة سابقاً من الملف عند التشغيل
    if os.path.exists(CSV_FILE):
        try:
            df = pd.read_csv(CSV_FILE)
            recorded_symbols = set(df['Symbol'].tolist())
        except:
            pass

    print("🚀 الرادار بدأ العمل والكتابة في CSV مفعلة...")

    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                price = tickers[sym].get('last', 0)
                change = tickers[sym].get('percentage', 0)
                
                # تحديث السعر الحالي في الملف للعملات القديمة
                if sym in recorded_symbols:
                    update_csv_price(sym, price)

                # منطق السكور 85+
                score = 90 if change > 4.5 else (85 if change > 3.5 else 0)
                
                if score >= 85 and sym not in recorded_symbols:
                    row = {
                        'Symbol': sym,
                        'Time': datetime.now().strftime('%H:%M:%S'),
                        'Entry': price,
                        'Current': price,
                        'TP': price * 1.05,
                        'SL': price * 0.97,
                        'Score': score
                    }
                    
                    # حفظ في CSV فوراً
                    force_write_csv(row)
                    recorded_symbols.add(sym)
                    
                    # إرسال تليجرام
                    msg = f"🎯 *إشارة جديدة: {sym}*\n💰 السعر: `{price:.4f}`\n📊 السكور: `{score}`"
                    threading.Thread(target=send_telegram, args=(msg,)).start()

            await asyncio.sleep(15)
        except Exception as e:
            print(f"⚠️ Engine Error: {e}")
            await asyncio.sleep(10)

@app.route('/')
def home():
    if not os.path.exists(CSV_FILE):
        return "<h1>البحث جارٍ... الملف لم يُنشأ بعد</h1>"
    
    with data_lock:
        df = pd.read_csv(CSV_FILE)
        rows = ""
        for _, r in df.iloc[::-1].iterrows():
            color = "#00ff00" if float(r['Current']) >= float(r['Entry']) else "#ff4444"
            rows += f"""<tr style="border-bottom:1px solid #2b3139;">
                <td style="color:#f0b90b; padding:12px;"><b>{r['Symbol']}</b></td>
                <td>{r['Time']}</td>
                <td>{r['Entry']}</td>
                <td style="color:{color};">{r['Current']}</td>
                <td>{r['Score']}</td>
            </tr>"""
    
    return f"""<html><body style="background:#0b0e11;color:white;text-align:center;font-family:sans-serif;">
        <h2>📊 سجل التداول المباشر (CSV)</h2>
        <table style="width:90%;margin:auto;background:#1e2329;border-collapse:collapse;">
            <thead><tr><th>العملة</th><th>الوقت</th><th>دخول</th><th>حالي</th><th>السكور</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
        <br><a href="/download" style="color:#f0b90b;">📥 تحميل الملف الآن</a>
    </body></html>"""

@app.route('/download')
def download():
    return send_file(CSV_FILE, as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(market_engine())
