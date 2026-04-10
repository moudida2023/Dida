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

data_lock = threading.Lock()

class GlobalState:
    open_trades = []          # الجدول 1: الصفقات المفتوحة حالياً (تتحرك مع السعر)
    hourly_report_list = []   # الجدول 2: قائمة صفقات الساعة (المسجلة للتقرير)
    last_sync_time = "بدء المزامنة..."

state = GlobalState()

# ======================== 2. نظام التقرير والتصفير (كل ساعة) ========================

def hourly_report_scheduler():
    while True:
        time.sleep(3600)  # الانتظار لمدة ساعة
        with data_lock:
            if state.hourly_report_list:
                msg = "📊 *تقرير الصفقات للساعة الماضية:*\n\n"
                for i, t in enumerate(state.hourly_report_list, 1):
                    msg += f"{i}. 🪙 `{t['sym']}` | السعر: `{t['price']:.6f}` | الوقت: `{t['time']}`\n"
                
                # تصفير القائمة بعد إرسال التقرير
                state.hourly_report_list = []
                
                # الإرسال للتلغرام
                for cid in DESTINATIONS:
                    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                                       json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"})
                    except: pass

# ======================== 3. واجهة الموقع (نظام الجداول الثلاثة) ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        report_queue = list(state.hourly_report_list)
        sync = state.last_sync_time

    # جدول 1: الصفقات المفتوحة (PNL مباشر)
    active_rows = ""
    for tr in reversed(active):
        pnl = ((tr['current_price'] - tr['entry_price']) / tr['entry_price']) * 100
        color = "#00ff00" if pnl >= 0 else "#ff4444"
        active_rows += f"<tr><td>{tr['time']}</td><td><b>{tr['sym']}</b></td><td>{tr['entry_price']:.6f}</td><td>{tr['current_price']:.6f}</td><td style='color:{color}; font-weight:bold;'>{pnl:+.2f}%</td></tr>"

    # جدول 2: سجل صفقات الساعة (التقرير القادم)
    report_rows = ""
    for r in reversed(report_queue):
        report_rows += f"<tr><td>{r['time']}</td><td style='color:#f0b90b;'>{r['sym']}</td><td>{r['price']:.6f}</td><td><span style='color:#00ff00;'>✓ مسجلة</span></td></tr>"

    return f"""
    <html><head><meta http-equiv="refresh" content="15"><style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; padding: 20px; }}
        .section {{ background: #1e2329; border-radius: 10px; padding: 20px; margin-bottom: 30px; border-top: 4px solid #f0b90b; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        th, td {{ padding: 12px; border: 1px solid #2b3139; text-align: center; }}
        th {{ background: #2b3139; color: #848e9c; font-size: 13px; }}
        h2 {{ color: #f0b90b; margin: 0; display: flex; justify-content: space-between; }}
        .report-badge {{ background: #848e9c; color: #000; padding: 2px 10px; border-radius: 4px; font-size: 14px; }}
    </style></head><body>
        <div class="section">
            <h2>🟢 الصفقات النشطة حالياً <span style="color:#00ff00; font-size:14px;">🕒 {sync}</span></h2>
            <table>
                <thead><tr><th>الوقت</th><th>الزوج</th><th>سعر الدخول</th><th>السعر الحالي</th><th>PNL %</th></tr></thead>
                <tbody>{active_rows if active_rows else "<tr><td colspan='5'>بانتظار إشارات دخول...</td></tr>"}</tbody>
            </table>
        </div>

        <div class="section" style="border-top-color: #848e9c;">
            <h2>📊 سجل صفقات التقرير القادم <span class="report_badge">العدد: {len(report_queue)}</span></h2>
            <table>
                <thead><tr><th>وقت الرصد</th><th>العملة</th><th>السعر عند الدخول</th><th>حالة التسجيل</th></tr></thead>
                <tbody>{report_rows if report_rows else "<tr><td colspan='4'>الساعة الحالية فارغة حتى الآن</td></tr>"}</tbody>
            </table>
        </div>
    </body></html>"""

# ======================== 4. المحرك (التسجيل المزدوج) ========================

async def core_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                score, price = await calculate_score(sym)
                now = datetime.now().strftime('%H:%M:%S')

                with data_lock:
                    state.last_sync_time = now
                    # تحديث أسعار الصفقات المفتوحة
                    for tr in state.open_trades:
                        if tr['sym'] == sym: tr['current_price'] = price

                    # تنفيذ الدخول (85+)
                    if score >= 85 and sym not in [x['sym'] for x in state.open_trades]:
                        # 1. إضافة لجدول المفتوحة
                        state.open_trades.append({'sym':sym, 'entry_price':price, 'current_price':price, 'time':now})
                        
                        # 2. تسجيل في "ليست" التقرير الدوري (حفظ في السيرفر)
                        state.hourly_report_list.append({'sym': sym, 'price': price, 'time': now})
                        
                        # إرسال إشعار تلغرام فوري
                        send_now(f"🚀 صفقة جديدة: {sym} | السعر: {price}")

                await asyncio.sleep(0.04)
            await asyncio.sleep(180)
        except: await asyncio.sleep(30)

async def calculate_score(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=50)
        return 85, bars[-1][4]
    except: return 0, 0

def send_now(msg):
    for cid in DESTINATIONS:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": cid, "text": msg})
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    threading.Thread(target=hourly_report_scheduler, daemon=True).start()
    asyncio.get_event_loop().run_until_complete(core_engine())
