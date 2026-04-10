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

# الإعدادات الأساسية
CSV_PATH = "/tmp/trading_signals_v92.csv"
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# النسب المئوية للأهداف
TAKE_PROFIT_PERCENT = 1.05  # +5%
STOP_LOSS_PERCENT = 0.97    # -3%

data_lock = threading.Lock()

# --- وظيفة إرسال إشعار الدخول المطور ---
def send_trade_alert(symbol, entry_price, tp, sl, score):
    """إرسال رسالة تليجرام تضم كافة تفاصيل الصفقة"""
    msg = (
        f"🎯 *إشارة دخول جديدة (Score: {score})*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💎 العملة: `#{symbol.replace('/USDT', '')}`\n"
        f"📥 سعر الدخول: `{entry_price:.4f}`\n"
        f"✅ جني الأرباح: `{tp:.4f}`\n"
        f"🚫 وقف الخسارة: `{sl:.4f}`\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⏰ الوقت: `{datetime.now().strftime('%H:%M:%S')}`"
    )
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID, 
            "text": msg, 
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

# --- دالة إدارة البيانات ---
def sync_trading_data(symbol, price, score, is_new=False):
    headers = ['Symbol', 'Time', 'Entry', 'Current', 'TP', 'SL', 'Score']
    with data_lock:
        try:
            if not os.path.exists(CSV_PATH):
                with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerow(headers)

            df = pd.read_csv(CSV_PATH)
            
            if symbol in df['Symbol'].values:
                df.loc[df['Symbol'] == symbol, 'Current'] = f"{price:.4f}"
                df.to_csv(CSV_PATH, index=False)
                return False
            elif is_new:
                tp = price * TAKE_PROFIT_PERCENT
                sl = price * STOP_LOSS_PERCENT
                new_row = [symbol, datetime.now().strftime('%H:%M:%S'), f"{price:.4f}", f"{price:.4f}", f"{tp:.4f}", f"{sl:.4f}", score]
                with open(CSV_PATH, 'a', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerow(new_row)
                return True, tp, sl
        except: pass
    return False

# --- المحرك الرئيسي ---
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
                
                # منطق السكور
                if change > 3: score = 85
                elif change > 1.5: score = 65
                else: score = 0

                if score >= 60:
                    result = sync_trading_data(sym, price, score, is_new=True)
                    if result and isinstance(result, tuple):
                        success, tp, sl = result
                        # إرسال التنبيه فقط إذا كان السكور 85+ (أو حسب رغبتك)
                        if score >= 85 and sym not in sent_list:
                            threading.Thread(target=send_trade_alert, args=(sym, price, tp, sl, score)).start()
                            sent_list.add(sym)
                else:
                    sync_trading_data(sym, price, score, is_new=False)

            await asyncio.sleep(15)
        except:
            await asyncio.sleep(10)

# --- واجهة الموقع ---
@app.route('/')
def index():
    if not os.path.exists(CSV_PATH):
        return "<body style='background:#0b0e11;color:white;text-align:center;'><h2>🔎 جاري فحص الفرص...</h2></body>"
    
    with data_lock:
        df = pd.read_csv(CSV_PATH)
    
    rows = ""
    for _, r in df.iloc[::-1].head(15).iterrows():
        rows += f"""<tr style="border-bottom:1px solid #2b3139;">
            <td style="padding:12px; color:#f0b90b;"><b>{r['Symbol']}</b></td>
            <td>{r['Entry']}</td>
            <td style="color:#00ff00;">{r['TP']}</td>
            <td style="color:#ff4444;">{r['SL']}</td>
            <td><span style="background:#363a45; padding:2px 10px; border-radius:10px;">{r['Score']}</span></td>
        </tr>"""

    return f"""<html><head><meta http-equiv="refresh" content="10"></head>
    <body style="background:#0b0e11; color:white; font-family:sans-serif; text-align:center; padding:20px;">
        <h2 style="color:#f0b90b;">📊 رادار الإشارات v92</h2>
        <table style="width:95%; margin:auto; background:#1e2329; border-collapse:collapse;">
            <thead><tr style="color:#848e9c;"><th>الرمز</th><th>الدخول</th><th>الهدف (TP)</th><th>الوقف (SL)</th><th>السكور</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </body></html>"""

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    asyncio.get_event_loop().run_until_complete(market_engine())
