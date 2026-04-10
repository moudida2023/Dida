import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات والربط ========================
app = Flask('')
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# نسب الإدارة المالية
TP_RATE = 0.03 # 3%
SL_RATE = 0.02 # 2%

data_lock = threading.Lock()

class SharedState:
    open_trades = []      # الجدول الأول: الصفقات المفتوحة
    telegram_logs = []    # الجدول الثاني: سجل إشعارات التلغرام
    last_update = "جاري المزامنة..."

state = SharedState()

# ======================== 2. واجهة السيرفر (نظام الجدولين) ========================

@app.route('/')
def home():
    with data_lock:
        trades = list(state.open_trades)
        logs = list(state.telegram_logs)
        sync_time = state.last_update

    # بناء جدول الصفقات المفتوحة
    trade_rows = ""
    for tr in reversed(trades):
        pnl = ((tr['current_price'] - tr['entry_price']) / tr['entry_price']) * 100
        pnl_color = "#00ff00" if pnl >= 0 else "#ff4444"
        trade_rows += f"""
        <tr>
            <td>{tr['time']}</td>
            <td><b>{tr['sym']}</b></td>
            <td>{tr['entry_price']:.6f}</td>
            <td style="color:#00ff00;">{tr['tp']:.6f}</td>
            <td style="color:#ff4444;">{tr['sl']:.6f}</td>
            <td style="color:{pnl_color}; font-weight:bold;">{pnl:+.2f}%</td>
        </tr>"""

    # بناء جدول سجل الإشعارات (ما تم إرساله لتلغرام)
    log_rows = ""
    for log in reversed(logs[-20:]): # عرض آخر 20 إشعار فقط
        log_rows += f"""
        <tr>
            <td style="color:#848e9c; font-size:0.85em;">{log['time']}</td>
            <td style="color:#f0b90b;">{log['sym']}</td>
            <td style="text-align:left; font-size:0.9em;">{log['message']}</td>
        </tr>"""

    return f"""
    <html><head><meta http-equiv="refresh" content="15"><style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; padding: 20px; }}
        .container {{ max-width: 1100px; margin: auto; }}
        .section {{ background: #1e2329; padding: 20px; border-radius: 12px; margin-bottom: 30px; border-top: 4px solid #f0b90b; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 12px; border-bottom: 1px solid #2b3139; text-align: center; }}
        th {{ color: #848e9c; font-size: 13px; background: #2b3139; }}
        h2 {{ color: #f0b90b; display: flex; justify-content: space-between; }}
        .status {{ font-size: 14px; color: #00ff00; }}
    </style></head><body>
        <div class="container">
            <div class="section">
                <h2>🟢 الصفقات المفتوحة <span class="status">تحديث: {sync_time}</span></h2>
                <table>
                    <thead><tr><th>الوقت</th><th>العملة</th><th>الدخول</th><th>الهدف (TP)</th><th>الوقف (SL)</th><th>الربح/الخسارة</th></tr></thead>
                    <tbody>{trade_rows if trade_rows else "<tr><td colspan='6'>لا توجد صفقات مفتوحة</td></tr>"}</tbody>
                </table>
            </div>

            <div class="section" style="border-top-color: #848e9c;">
                <h2>📨 سجل إشعارات تلغرام (Sent Logs)</h2>
                <table>
                    <thead><tr><th width="15%">الوقت</th><th width="15%">العملة</th><th width="70%">نص الرسالة المرسلة</th></tr></thead>
                    <tbody>{log_rows if log_rows else "<tr><td colspan='3'>بانتظار الإشعارات القادمة...</td></tr>"}</tbody>
                </table>
            </div>
        </div>
    </body></html>"""

# ======================== 3. المحرك (الكتابة المزدوجة) ========================

async def run_scanner():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                # التحليل الفني (مثال: سكور 85+)
                score, price = await get_technical_data(sym)
                now = datetime.now().strftime('%H:%M:%S')

                with data_lock:
                    state.last_update = now
                    
                    # تحديث أسعار الصفقات المفتوحة في الجدول الأول
                    for tr in state.open_trades:
                        if tr['sym'] == sym:
                            tr['current_price'] = price

                    if score >= 85:
                        if sym not in [x['sym'] for x in state.open_trades]:
                            # 1. حساب البيانات المالية
                            tp = price * (1 + TP_RATE); sl = price * (1 - SL_RATE)
                            
                            # 2. الكتابة في جدول "الصفقات المفتوحة"
                            state.open_trades.append({
                                'sym': sym, 'entry_price': price, 'current_price': price,
                                'tp': tp, 'sl': sl, 'time': now
                            })
                            
                            # 3. صياغة الرسالة والكتابة في جدول "سجل الإشعارات"
                            msg_text = f"Entry: {price:.6f} | TP: {tp:.6f} | SL: {sl:.6f}"
                            state.telegram_logs.append({
                                'sym': sym, 'time': now, 'message': f"🚀 تم إرسال تنبيه دخول بسكور {score}"
                            })
                            
                            # 4. الإرسال الفعلي لتلغرام
                            send_telegram(f"✅ *{sym}* \n{msg_text}")

                await asyncio.sleep(0.04)
            await asyncio.sleep(120)
        except Exception as e:
            print(f"Error: {e}"); await asyncio.sleep(30)

async def get_technical_data(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=50)
        df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
        # (نفس منطق السكور السابق: بولنجر، سيولة، إلخ)
        # سأفترض هنا شرطاً مبسطاً للاختبار
        return 85, df['close'].iloc[-1] 
    except: return 0, 0

def send_telegram(msg):
    for cid in DESTINATIONS:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                           json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"})
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(run_scanner())
