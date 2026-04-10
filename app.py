import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات والنسب ========================
app = Flask('')
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# نسب إدارة المخاطر
TP_RATE = 0.03  # 3% ربح
SL_RATE = 0.02  # 2% خسارة

data_lock = threading.Lock()

class SharedState:
    open_trades = []
    last_update = "بانتظار البيانات..."

state = SharedState()

# ======================== 2. واجهة الجدول المتطور ========================

@app.route('/')
def home():
    with data_lock:
        current_open = list(state.open_trades)
        sync_time = state.last_update

    rows = ""
    for tr in reversed(current_open):
        # حساب النسبة المئوية للحركة الحالية
        pnl = ((tr['current_price'] - tr['entry_price']) / tr['entry_price']) * 100
        pnl_color = "#00ff00" if pnl >= 0 else "#ff4444"
        
        rows += f"""
        <tr>
            <td style="color:#f0b90b;">{tr['time']}</td>
            <td><b>{tr['sym']}</b></td>
            <td>{tr['entry_price']:.6f}</td>
            <td style="color:#00ff00; font-weight:bold;">{tr['tp']:.6f}</td>
            <td style="color:#ff4444; font-weight:bold;">{tr['sl']:.6f}</td>
            <td>{tr['current_price']:.6f}</td>
            <td style="background:{pnl_color}; color:#000; font-weight:bold;">{pnl:+.2f}%</td>
        </tr>"""

    return f"""
    <html><head><meta http-equiv="refresh" content="10">
    <style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; padding: 20px; }}
        .card {{ background: #1e2329; padding: 20px; border-radius: 12px; border-top: 5px solid #f0b90b; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 15px; border-bottom: 1px solid #2b3139; text-align: center; }}
        th {{ color: #848e9c; font-size: 12px; text-transform: uppercase; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; }}
        .sync-tag {{ font-size: 12px; color: #00ff00; }}
    </style></head><body>
        <div class="card">
            <div class="header">
                <h2>🟢 الصفقات المفتوحة وأهداف التداول</h2>
                <span class="sync-tag">تحديث السعر: {sync_time}</span>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>وقت الدخول</th>
                        <th>الزوج</th>
                        <th>سعر الدخول</th>
                        <th>جني الأرباح (TP)</th>
                        <th>وقف الخسارة (SL)</th>
                        <th>السعر الحالي</th>
                        <th>الحالة (PNL)</th>
                    </tr>
                </thead>
                <tbody>
                    {rows if rows else "<tr><td colspan='7'>لا توجد صفقات نشطة حالياً... جاري مسح السوق</td></tr>"}
                </tbody>
            </table>
        </div>
    </body></html>"""

# ======================== 3. محرك البحث الذكي ========================

async def analyze_market():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            for sym in symbols:
                # محاكاة تحليل السكور (اختصاراً للوقت)
                bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=50)
                df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
                current_p = df['close'].iloc[-1]
                
                # حساب سكور بسيط (بولنجر + سيولة)
                std = df['close'].rolling(20).std(); ma = df['close'].rolling(20).mean()
                is_squeeze = ((4 * std) / ma).iloc[-1] < 0.05
                vol_spike = df['vol'].iloc[-1] > df['vol'].rolling(20).mean().iloc[-1] * 1.5
                
                with data_lock:
                    state.last_update = datetime.now().strftime('%H:%M:%S')
                    
                    # تحديث السعر الحالي للصفقات المفتوحة
                    for tr in state.open_trades:
                        if tr['sym'] == sym:
                            tr['current_price'] = current_p

                    # شرط الدخول: انضغاط + سيولة
                    if is_squeeze and vol_spike:
                        if sym not in [x['sym'] for x in state.open_trades]:
                            # حساب القيم المالية
                            tp_price = current_p * (1 + TP_RATE)
                            sl_price = current_p * (1 - SL_RATE)
                            entry_time = state.last_update
                            
                            # إضافة للجدول (الكتابة أولاً)
                            state.open_trades.append({
                                'sym': sym, 'entry_price': current_p, 'current_price': current_p,
                                'tp': tp_price, 'sl': sl_price, 'time': entry_time
                            })
                            
                            # إرسال التلجرام
                            msg = (f"🚀 *إشارة دخول*\nالعملة: {sym}\nالدخول: {current_p:.6f}\n"
                                   f"🎯 الهدف: {tp_price:.6f}\n🛑 الوقف: {sl_price:.6f}\n⏰ الوقت: {entry_time}")
                            send_telegram(msg)
                
                await asyncio.sleep(0.05)
            await asyncio.sleep(120)
        except Exception as e:
            print(f"Error: {e}"); await asyncio.sleep(30)

def send_telegram(msg):
    for cid in DESTINATIONS:
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                           json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"})
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    asyncio.get_event_loop().run_until_complete(analyze_market())
