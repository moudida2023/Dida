import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import csv
import time
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. الإعدادات والمسارات ========================
app = Flask(__name__)
CSV_FILE = "/tmp/live_market_data.csv"
EXCHANGE = ccxt.binance({'enableRateLimit': True})

SCORE_LIMIT = 60 
data_lock = threading.Lock()

# ذاكرة مؤقتة لتخزين الصفقات وتحديثها قبل حفظها في CSV
trades_registry = [] 

def save_all_to_csv():
    """دالة تقوم بمسح ملف CSV وإعادة كتابة كل الصفقات بالأسعار المحدثة"""
    with data_lock:
        try:
            headers = ['Symbol', 'Entry_Time', 'Entry_Price', 'Current_Price', 'PNL_%', 'Score']
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for t in trades_registry:
                    # حساب نسبة التغير اللحظية
                    pnl = ((t['current_price'] - t['entry_price']) / t['entry_price']) * 100
                    writer.writerow([
                        t['sym'], t['time'], f"{t['entry_price']:.4f}", 
                        f"{t['current_price']:.4f}", f"{pnl:+.2f}%", t['score']
                    ])
        except Exception as e:
            print(f"CSV Update Error: {e}")

# ======================== 2. محرك المسح والتحديث المستمر ========================

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                await asyncio.sleep(0.01)
                ticker = tickers[sym]
                price = ticker.get('last', 0)
                change = ticker.get('percentage', 0)

                with data_lock:
                    # أولاً: تحديث السعر الحالي لأي عملة موجودة مسبقاً في القائمة
                    for t in trades_registry:
                        if t['sym'] == sym:
                            t['current_price'] = price

                    # ثانياً: إضافة عملة جديدة إذا حققت السكور ولم تكن موجودة
                    score = 75 if change > 1.5 else 0
                    if score >= SCORE_LIMIT and not any(x['sym'] == sym for x in trades_registry):
                        trades_registry.append({
                            'sym': sym,
                            'time': datetime.now().strftime('%H:%M:%S'),
                            'entry_price': price,
                            'current_price': price,
                            'score': score
                        })
            
            # ثالثاً: حفظ الحالة المحدثة بالكامل في ملف CSV بعد كل دورة مسح
            save_all_to_csv()
            
            await asyncio.sleep(10)
        except Exception as e:
            print(f"⚠️ Engine Error: {e}")
            await asyncio.sleep(10)

# ======================== 3. واجهة العرض (قراءة البيانات المحدثة) ========================

@app.route('/')
def home():
    with data_lock:
        active_trades = list(trades_registry)
    
    rows_html = ""
    for t in reversed(active_trades):
        pnl = ((t['current_price'] - t['entry_price']) / t['entry_price']) * 100
        color = "#00ff00" if pnl >= 0 else "#ff4444"
        
        rows_html += f"""
        <tr style="border-bottom: 1px solid #2b3139;">
            <td style="color:#f0b90b; font-weight:bold; padding:12px;">{t['sym']}</td>
            <td>{t['time']}</td>
            <td>{t['entry_price']:.4f}</td>
            <td style="color:{color}; font-weight:bold;">{t['current_price']:.4f}</td>
            <td style="color:{color};">{pnl:+.2f}%</td>
            <td>{t['score']}</td>
        </tr>"""

    return f"""
    <html>
    <head>
        <title>Live CSV Scanner</title>
        <meta http-equiv="refresh" content="10">
        <style>
            body {{ background:#0b0e11; color:white; font-family:sans-serif; padding:20px; }}
            .container {{ max-width:950px; margin:auto; background:#1e2329; padding:20px; border-radius:15px; border:1px solid #363a45; }}
            table {{ width:100%; border-collapse:collapse; margin-top:20px; text-align:center; }}
            th {{ color:#848e9c; padding:10px; border-bottom:2px solid #2b3139; font-size:0.85em; }}
            .btn {{ color:#f0b90b; text-decoration:none; border:1px solid #f0b90b; padding:5px 12px; border-radius:5px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h2>🔄 رادار CSV المتغير حياً</h2>
                <a href="/download" class="btn">📥 تحميل ملف CSV المحدث</a>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>العملة</th><th>وقت الدخول</th><th>سعر الدخول</th>
                        <th>السعر الحالي</th><th>الربح/الخسارة</th><th>السكور</th>
                    </tr>
                </thead>
                <tbody>{rows_html if rows_html else "<tr><td colspan='6'>جاري المراقبة...</td></tr>"}</tbody>
            </table>
        </div>
    </body></html>"""

@app.route('/download')
def download():
    save_all_to_csv() # التأكد من الحفظ قبل التحميل
    return send_file(CSV_FILE, as_attachment=True, mimetype='text/csv')

# ======================== 4. التشغيل ========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
