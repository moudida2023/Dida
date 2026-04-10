import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import csv
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. الإعدادات والمسارات ========================
app = Flask('')
CSV_FILE = "/tmp/elite_trades.csv"
EXCHANGE = ccxt.binance({'enableRateLimit': True})

STRICT_SCORE = 85       # العودة للسكور العالي
MAX_TRADES = 50         # الحد الأقصى للسجل

data_lock = threading.Lock()

class CSVManager:
    def __init__(self):
        self.headers = ['Time', 'Symbol', 'Score', 'Entry_Price', 'Current_Price', 'Change_Pct']
        self._init_csv()

    def _init_csv(self):
        if not os.path.exists(CSV_FILE):
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.headers)
                # سطر تأكيدي لبدء النظام
                writer.writerow([datetime.now().strftime('%H:%M:%S'), 'SYSTEM/BOOT', 100, 0, 0, 0])

    def append_trade(self, row):
        with data_lock:
            try:
                with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(row)
            except Exception as e:
                print(f"❌ CSV Write Error: {e}")

    def read_last_entries(self):
        if not os.path.exists(CSV_FILE): return []
        try:
            df = pd.read_csv(CSV_FILE)
            return df.tail(MAX_TRADES).values.tolist()
        except: return []

csv_db = CSVManager()

# ======================== 2. محرك النخبة (تحليل معمق) ========================

async def calculate_elite_score(sym):
    try:
        # جلب بيانات ساعة كاملة للتحليل
        ohlcv = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=24)
        df = pd.DataFrame(ohlcv, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        
        score = 0
        current_price = df['c'].iloc[-1]
        vol_mean = df['v'].mean()
        
        # شرط 1: انفجار حجم التداول (50 نقطة)
        if df['v'].iloc[-1] > vol_mean * 2.5: score += 50
        # شرط 2: صعود سعري حاد (35 نقطة)
        if df['c'].iloc[-1] > df['o'].iloc[-1] * 1.03: score += 35
        # شرط 3: كسر أعلى سعر في 24 ساعة (15 نقطة)
        if current_price >= df['h'].max(): score += 15
        
        return score, current_price
    except: return 0, 0

async def main_engine():
    recorded_symbols = [] # لمنع التكرار في الجلسة الواحدة
    
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            # مسح شامل لجميع أزواج USDT
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                await asyncio.sleep(0.05) # إيقاع هادئ لمنع الحظر
                
                # فحص السكور فقط إذا لم تكن مسجلة
                if sym not in recorded_symbols:
                    score, price = await calculate_elite_score(sym)
                    
                    if score >= STRICT_SCORE:
                        row = [
                            datetime.now().strftime('%H:%M:%S'),
                            sym,
                            score,
                            price,
                            price,
                            0.0
                        ]
                        csv_db.append_trade(row)
                        recorded_symbols.append(sym)
                        print(f"💎 صيد ثمين: {sym} بسكور {score}")
            
            await asyncio.sleep(30) # استراحة بين الدورات الشاملة
        except: await asyncio.sleep(10)

# ======================== 3. واجهة العرض المحدثة ========================

@app.route('/')
def home():
    data = csv_db.read_last_entries()
    rows_html = ""
    for row in reversed(data):
        if row[1] == 'Symbol' or row[1] == 'SYSTEM/BOOT': continue
        rows_html += f"""
        <tr style="border-bottom: 1px solid #2b3139;">
            <td style="padding:12px;">{row[0]}</td>
            <td style="color:#f0b90b; font-weight:bold;">{row[1]}</td>
            <td style="color:#00ff00;">{row[2]}</td>
            <td>{float(row[3]):.4f}</td>
        </tr>"""

    return f"""
    <html><head><meta http-equiv="refresh" content="30">
    <style>
        body {{ background:#0b0e11; color:white; font-family:sans-serif; padding:20px; }}
        .container {{ max-width:800px; margin:auto; background:#1e2329; padding:25px; border-radius:15px; border:1px solid #363a45; }}
        table {{ width:100%; border-collapse:collapse; margin-top:20px; text-align:center; }}
        th {{ color:#848e9c; padding:10px; border-bottom:2px solid #2b3139; }}
        .badge {{ background:#f0b90b; color:black; padding:4px 10px; border-radius:10px; font-size:0.8em; font-weight:bold; }}
    </style>
    </head>
    <body>
        <div class="container">
            <h2 style="text-align:center;">💎 رادار النخبة v69 (Score 85+)</h2>
            <div style="text-align:center; margin-bottom:15px;">
                <span class="badge">نظام CSV نشط</span>
                <a href="/download" style="color:#848e9c; margin-left:15px; text-decoration:none;">📥 تحميل السجل</a>
            </div>
            <table>
                <thead><tr><th>الوقت</th><th>العملة</th><th>السكور</th><th>سعر الدخول</th></tr></thead>
                <tbody>{rows_html if rows_html else "<tr><td colspan='4' style='padding:30px; color:#444;'>البحث عن فرص ذهبية (85+)...</td></tr>"}</tbody>
            </table>
        </div>
    </body></html>"""

@app.route('/download')
def download():
    return send_file(CSV_FILE, as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(main_engine())
