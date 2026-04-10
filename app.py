import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
import time
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات والربط ========================
app = Flask('')
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# القيود البرمجية
MAX_OPEN_TRADES = 10 
data_lock = threading.Lock()

class TradingSystem:
    open_trades = []       # الصفقات النشطة (تظهر في الموقع)
    hourly_history = []    # سجل العملات المرصودة خلال الساعة (للتقرير)
    last_sync = "بدء المزامنة..."

state = TradingSystem()

# ======================== 2. واجهة الموقع (تحديث ديناميكي) ========================

@app.route('/')
def dashboard():
    with data_lock:
        active = list(state.open_trades)
        sync_time = state.last_sync
        count = len(active)
        report_count = len(state.hourly_history)

    rows = ""
    for tr in reversed(active):
        pnl = ((tr['current_price'] - tr['entry_price']) / tr['entry_price']) * 100
        pnl_color = "#00ff00" if pnl >= 0 else "#ff4444"
        rows += f"""
        <tr>
            <td>{tr['time']}</td>
            <td><b>{tr['sym']}</b></td>
            <td style="color:#f0b90b;">{tr['score']}</td>
            <td>{tr['entry_price']:.6f}</td>
            <td>{tr['current_price']:.6f}</td>
            <td style="color:{pnl_color}; font-weight:bold;">{pnl:+.2f}%</td>
        </tr>"""

    return f"""
    <html><head><meta http-equiv="refresh" content="10"><style>
        body {{ background: #0b0e11; color: #eaecef; font-family: 'Segoe UI', sans-serif; padding: 20px; }}
        .container {{ background: #1e2329; border-radius: 12px; padding: 20px; border-top: 5px solid #f0b90b; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
        .stats {{ display: flex; justify-content: space-between; background: #2b3139; padding: 15px; border-radius: 8px; margin: 20px 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 15px; border-bottom: 1px solid #2b3139; text-align: center; }}
        th {{ color: #848e9c; font-size: 13px; background: #2b3139; }}
        .live-dot {{ height: 10px; width: 10px; background-color: #00ff00; border-radius: 50%; display: inline-block; margin-right: 5px; }}
    </style></head><body>
        <div class="container">
            <div style="display:flex; justify-content:space-between; align-items:center; padding: 0 20px;">
                <h2>📊 لوحة تحكم النخبة</h2>
                <span><span class="live-dot"></span> متصل بالسيرفر</span>
            </div>
            <div class="stats">
                <span>الصفقات المفتوحة: <b>{count} / {MAX_OPEN_TRADES}</b></span>
                <span>سجل الساعة: <b>{report_count} عملة</b></span>
                <span>آخر تحديث: <b>{sync_time}</b></span>
            </div>
            <table>
                <thead>
                    <tr><th>الوقت</th><th>الزوج</th><th>السكور</th><th>سعر الدخول</th><th>السعر الحالي</th><th>PNL %</th></tr>
                </thead>
                <tbody>
                    {rows if rows else "<tr><td colspan='6'>جاري مسح السوق... بانتظار عملات تحقق سكور > 85</td></tr>"}
                </tbody>
            </table>
        </div>
    </body></html>"""

# ======================== 3. المحرك والتحليل الفني ========================

async def analyze_and_run():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                score, price = await get_technical_score(sym)
                now_str = datetime.now().strftime('%H:%M:%S')

                with data_lock:
                    state.last_sync = now_str
                    # تحديث أسعار العملات الموجودة مسبقاً في السيرفر
                    for tr in state.open_trades:
                        if tr['sym'] == sym:
                            tr['current_price'] = price

                    # تنفيذ الدخول: سكور 85+ ، عدم التكرار ، أقل من 10 صفقات
                    if score >= 85:
                        is_duplicate = any(t['sym'] == sym for t in state.open_trades)
                        if not is_duplicate and len(state.open_trades) < MAX_OPEN_TRADES:
                            # تسجيل العملة في الذاكرة
                            new_trade = {
                                'sym': sym, 'score': score, 'entry_price': price, 
                                'current_price': price, 'time': now_str
                            }
                            state.open_trades.append(new_trade)
                            state.hourly_history.append(new_trade)
                            
                            # إرسال إشعار فوري للتلغرام
                            send_telegram(f"🆕 *إشارة دخول قوية*\nالعملة: `{sym}`\nالسكور: `{score}`\nالسعر: `{price:.6f}`")

                await asyncio.sleep(0.02)
            await asyncio.sleep(120)
        except Exception as e:
            await asyncio.sleep(30)

async def get_technical_score(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=50)
        df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
        p = df['close'].iloc[-1]
        score = 0
        # حساب السكور (بولنجر 40، متوسطات 20، سيولة 20، RSI 20)
        # سيتم اعتبار سكور 85 كمثال للمحاكاة - أضف معادلاتك هنا
        return 88, p 
    except: return 0, 0

# ======================== 4. التقارير والإشعارات ========================

def hourly_report_worker():
    while True:
        time.sleep(3600) # إرسال كل ساعة
        with data_lock:
            if state.hourly_history:
                msg = "📊 *تقرير صفقات الساعة الماضية:*\n\n"
                for i, item in enumerate(state.hourly_history, 1):
                    msg += f"{i}. `{item['sym']}` | سكور: `{item['score']}` | سعر: `{item['price']:.6f}`\n"
                state.hourly_history = [] # تصفير القائمة لساعة جديدة
            else:
                msg = "📊 *تقرير الساعة:* لم يتم رصد أي عملات جديدة."
            
            send_telegram(msg)

def send_telegram(msg):
    for cid in DESTINATIONS:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                           json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"})
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # تشغيل خيوط السيرفر والتقرير والمسح
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    threading.Thread(target=hourly_report_worker, daemon=True).start()
    asyncio.get_event_loop().run_until_complete(analyze_and_run())
