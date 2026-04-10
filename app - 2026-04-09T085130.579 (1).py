import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import csv
import requests
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. الإعدادات والبيانات ========================
app = Flask(__name__)
CSV_FILE = "/tmp/trading_signals_v80.csv"
EXCHANGE = ccxt.binance({'enableRateLimit': True})

TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

ELITE_SCORE = 85 
TP_PERCENT = 1.05  # جني أرباح عند +5%
SL_PERCENT = 0.97  # وقف خسارة عند -3%

data_lock = threading.Lock()

class TradeManager:
    def __init__(self):
        # الأعمدة الجديدة المطلوبة
        self.headers = ['Symbol', 'Time', 'Entry', 'TP', 'SL', 'Score']
        self._init_csv()

    def _init_csv(self):
        if not os.path.exists(CSV_FILE):
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.headers)

    def add_signal(self, row):
        with data_lock:
            try:
                if os.path.exists(CSV_FILE) and os.path.getsize(CSV_FILE) > 0:
                    df = pd.read_csv(CSV_FILE)
                    if row[0] in df['Symbol'].values: return False
                
                with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(row)
                return True
            except: return False

    def get_history(self):
        if not os.path.exists(CSV_FILE): return []
        try:
            df = pd.read_csv(CSV_FILE)
            return df.values.tolist()
        except: return []

trade_db = TradeManager()

# ======================== 2. إرسال التنبيه المفصل ========================

def send_detailed_alert(sym, entry, tp, sl, score):
    msg = (f"🎯 *صفقة جديدة المكتشفة (Score: {score})*\n\n"
           f"Symbol: #{sym.replace('/USDT', '')}\n"
           f"📥 سعر الدخول: `{entry:.4f}`\n"
           f"✅ جني الأرباح (TP): `{tp:.4f}`\n"
           f"🚫 وقف الخسارة (SL): `{sl:.4f}`\n"
           f"⏰ الوقت: `{datetime.now().strftime('%H:%M:%S')}`")
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

# ======================== 3. المحرك الذكي ========================

async def core_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                await asyncio.sleep(0.01)
                ticker = tickers[sym]
                change = ticker.get('percentage', 0)
                price = ticker.get('last', 0)
                
                # حساب السكور
                score = 90 if change > 4.5 else (85 if change > 3.5 else 0)
                
                if score >= ELITE_SCORE:
                    # حساب الأهداف
                    tp_price = price * TP_PERCENT
                    sl_price = price * SL_PERCENT
                    entry_time = datetime.now().strftime('%H:%M:%S')
                    
                    row = [sym, entry_time, price, tp_price, sl_price, score]
                    
                    if trade_db.add_signal(row):
                        send_detailed_alert(sym, price, tp_price, sl_price, score)

            await asyncio.sleep(20)
        except: await asyncio.sleep(10)

# ======================== 4. واجهة العرض ========================

@app.route('/')
def home():
    data = trade_db.get_history()
    rows_html = ""
    for r in reversed(data):
        rows_html += f"""
        <tr style="border-bottom: 1px solid #2b3139;">
            <td style="color:#f0b90b; padding:12px;"><b>{r[0]}</b></td>
            <td>{r[1]}</td>
            <td style="color:#ffffff;">{float(r[2]):.4f}</td>
            <td style="color:#00ff00;">{float(r[3]):.4f}</td>
            <td style="color:#ff4444;">{float(r[4]):.4f}</td>
            <td><span style="background:#2b3139; padding:2px 8px; border-radius:5px;">{r[5]}</span></td>
        </tr>"""

    return f"""
    <html><head><meta http-equiv="refresh" content="30">
    <style>
        body {{ background:#0b0e11; color:white; font-family:sans-serif; text-align:center; padding:20px; }}
        .container {{ max-width:950px; margin:auto; background:#1e2329; padding:20px; border-radius:15px; border:1px solid #363a45; }}
        table {{ width:100%; border-collapse:collapse; margin-top:20px; }}
        th {{ color:#848e9c; padding:10px; border-bottom:2px solid #2b3139; font-size:0.9em; }}
    </style></head>
    <body><div class="container">
        <h2>🚀 صفقات النخبة (Score 85+)</h2>
        <table>
            <thead><tr><th>العملة</th><th>الوقت</th><th>الدخول</th><th>الهدف (TP)</th><th>الوقف (SL)</th><th>السكور</th></tr></thead>
            <tbody>{rows_html if rows_html else "<tr><td colspan='6' style='padding:30px;'>بانتظار الإشارات القوية...</td></tr>"}</tbody>
        </table>
        <br><a href="/download" style="color:#f0b90b;">📥 تحميل سجل الصفقات CSV</a>
    </div></body></html>"""

@app.route('/download')
def download():
    return send_file(CSV_FILE, as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(core_engine())
