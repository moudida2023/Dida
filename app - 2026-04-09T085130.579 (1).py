import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import requests
from flask import Flask, send_file
from datetime import datetime

app = Flask(__name__)
CSV_FILE = "/tmp/trading_signals_v84.csv"
EXCHANGE = ccxt.binance({'enableRateLimit': True})

TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# --- إدارة البيانات في الرام (Fast Storage) ---
# إنشاء DataFrame فارغ في البداية
columns = ['Symbol', 'Time', 'Entry', 'Current', 'TP', 'SL', 'Score']
trades_df = pd.DataFrame(columns=columns)
data_lock = threading.Lock()

def save_to_disk():
    """حفظ البيانات من الرام إلى القرص (CSV)"""
    with data_lock:
        trades_df.to_csv(CSV_FILE, index=False)

# --- وظائف تليجرam ---
def send_telegram_fast(sym, entry, tp, sl, score):
    msg = (f"🚀 *إشارة سريعة (Score: {score})*\n"
           f"💎 العملة: `{sym}`\n"
           f"📥 الدخول: `{entry:.4f}`\n"
           f"🎯 الهدف: `{tp:.4f}`\n"
           f"🚫 الوقف: `{sl:.4f}`")
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except: pass

# --- المحرك المسرع (Core Engine) ---
async def market_engine():
    global trades_df
    print("⚡ المحرك المسرع يعمل بنظام الذاكرة اللحظية...")
    
    while True:
        try:
            # جلب كل الأسعار دفعة واحدة (أسرع بكثير)
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            with data_lock:
                for sym in symbols:
                    price = tickers[sym].get('last', 0)
                    change = tickers[sym].get('percentage', 0)
                    
                    # 1. تحديث السعر الحالي بسرعة في الرام (لو كانت العملة موجودة)
                    if sym in trades_df['Symbol'].values:
                        trades_df.loc[trades_df['Symbol'] == sym, 'Current'] = price
                    
                    # 2. فحص السكور لإضافة عملة جديدة
                    score = 90 if change > 4.5 else (85 if change > 3.5 else 0)
                    if score >= 85 and sym not in trades_df['Symbol'].values:
                        new_row = {
                            'Symbol': sym,
                            'Time': datetime.now().strftime('%H:%M:%S'),
                            'Entry': price,
                            'Current': price,
                            'TP': price * 1.05,
                            'SL': price * 0.97,
                            'Score': score
                        }
                        # إضافة السطر الجديد للـ DataFrame
                        trades_df = pd.concat([trades_df, pd.DataFrame([new_row])], ignore_index=True)
                        
                        # إرسال التنبيه في خيط مستقل لعدم تعطيل المسح
                        threading.Thread(target=send_telegram_fast, args=(sym, price, price*1.05, price*0.97, score)).start()

            # حفظ نسخة احتياطية في CSV كل دورة
            save_to_disk()
            
            await asyncio.sleep(5) # تقليل زمن الانتظار لأن الكود أصبح أسرع
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(10)

# --- الواجهة ---
@app.route('/')
def home():
    with data_lock:
        # تحويل الـ DataFrame إلى HTML مباشرة (أسرع طريقة للعرض)
        if trades_df.empty:
            return "<h1>البحث جارٍ عن فرص...</h1>"
        
        # ترتيب البيانات لعرض الأحدث أولاً
        df_display = trades_df.iloc[::-1].copy()
        
        # إضافة تنسيق الألوان للجدول
        rows = ""
        for _, r in df_display.iterrows():
            color = "#00ff00" if float(r['Current']) >= float(r['Entry']) else "#ff4444"
            rows += f"""<tr style="border-bottom:1px solid #2b3139;">
                <td style="color:#f0b90b; padding:12px;"><b>{r['Symbol']}</b></td>
                <td>{r['Time']}</td>
                <td>{r['Entry']:.4f}</td>
                <td style="color:{color};">{r['Current']:.4f}</td>
                <td style="color:#00ff00;">{r['TP']:.4f}</td>
                <td style="color:#ff4444;">{r['SL']:.4f}</td>
            </tr>"""

    return f"""<html><head><meta http-equiv="refresh" content="10">
    <style>body{{background:#0b0e11;color:white;text-align:center;font-family:sans-serif;}} table{{width:90%;margin:auto;background:#1e2329;border-collapse:collapse;}} th{{padding:10px;color:#848e9c;}}</style>
    </head><body><h2>🚀 نظام تداول Pandas المسرع v84</h2>
    <table><thead><tr><th>العملة</th><th>الوقت</th><th>دخول</th><th>حالي</th><th>الهدف</th><th>الوقف</th></tr></thead>
    <tbody>{rows}</tbody></table><br><a href="/download" style="color:#f0b90b;">📥 تحميل CSV</a></body></html>"""

@app.route('/download')
def download():
    save_to_disk()
    return send_file(CSV_FILE, as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(market_engine())
