import asyncio
import ccxt.pro as ccxt
import threading
import requests
from flask import Flask
from datetime import datetime

app = Flask(__name__)

# --- إعدادات التنبيهات ---
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
SCORE_THRESHOLD = 60  # تم الضبط على 60 للتجربة السريعة

# مخزن البيانات في الذاكرة (لضمان الظهور الفوري على الموقع)
live_trades = {}
data_lock = threading.Lock()

# --- وظيفة إرسال تليجرام ---
def send_telegram(symbol, price, score):
    tp, sl = price * 1.05, price * 0.97
    msg = (f"🔔 *إشارة مكتشفة (Score: {score})*\n"
           f"💎 العملة: `{symbol}`\n"
           f"💰 الدخول: `{price:.4f}`\n"
           f"🎯 الهدف: `{tp:.4f}`\n"
           f"🚫 الوقف: `{sl:.4f}`")
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except:
        pass

# --- المحرك الرئيسي (Engine) ---
async def market_engine():
    exchange = ccxt.binance({'enableRateLimit': True})
    sent_symbols = set()
    print(f"🚀 الرادار بدأ العمل.. سكور التجربة: {SCORE_THRESHOLD}")

    while True:
        try:
            tickers = await exchange.fetch_tickers()
            for sym, ticker in tickers.items():
                if '/USDT' not in sym or 'UP/' in sym or 'DOWN/' in sym:
                    continue

                price = ticker.get('last', 0)
                change = ticker.get('percentage', 0)
                
                # حساب السكور بناءً على الصعود (أكثر من 1.2% صعود = سكور 60+)
                current_score = 90 if change > 4 else (75 if change > 2 else (60 if change > 1.2 else 0))

                if current_score >= SCORE_THRESHOLD:
                    with data_lock:
                        # إضافة أو تحديث البيانات في الذاكرة
                        if sym not in live_trades:
                            live_trades[sym] = {
                                'time': datetime.now().strftime('%H:%M:%S'),
                                'entry': price,
                                'current': price,
                                'score': current_score
                            }
                            # إرسال تليجرام للعملات الجديدة فقط
                            if sym not in sent_symbols:
                                threading.Thread(target=send_telegram, args=(sym, price, current_score)).start()
                                sent_symbols.add(sym)
                        else:
                            # تحديث السعر الحالي والسكور فقط
                            live_trades[sym]['current'] = price
                            live_trades[sym]['score'] = current_score

            await asyncio.sleep(10) # تحديث كل 10 ثوانٍ
        except Exception as e:
            print(f"Engine Error: {e}")
            await asyncio.sleep(5)

# --- واجهة العرض (الموقع) ---
@app.route('/')
def home():
    with data_lock:
        if not live_trades:
            return "<body style='background:#0b0e11;color:white;text-align:center;'><h2>🔎 جاري مسح السوق.. انتظر صعود عملة فوق 1.2% (سكور 60)</h2></body>"
        
        # تحويل القاموس إلى صفوف HTML
        rows = ""
        # ترتيب حسب الوقت (الأحدث أولاً)
        sorted_trades = sorted(live_trades.items(), key=lambda x: x[1]['time'], reverse=True)
        
        for sym, details in sorted_trades:
            color = "#00ff00" if details['current'] >= details['entry'] else "#ff4444"
            rows += f"""
            <tr style="border-bottom:1px solid #2b3139;">
                <td style="color:#f0b90b; padding:12px;"><b>{sym}</b></td>
                <td>{details['time']}</td>
                <td>{details['entry']:.4f}</td>
                <td style="color:{color}; font-weight:bold;">{details['current']:.4f}</td>
                <td><span style="background:#363a45; padding:2px 10px; border-radius:10px;">{details['score']}</span></td>
            </tr>"""

    return f"""
    <html><head><meta http-equiv="refresh" content="10">
    <style>
        body{{background:#0b0e11; color:white; font-family:sans-serif; text-align:center; padding:20px;}}
        table{{width:95%; margin:auto; background:#1e2329; border-collapse:collapse; border-radius:10px; overflow:hidden;}}
        th{{background:#2b3139; color:#848e9c; padding:15px;}}
        td{{padding:10px; border-bottom:1px solid #2b3139;}}
    </style></head>
    <body>
        <h2 style="color:#f0b90b;">📊 رادار التداول الفوري v95</h2>
        <p>يتم تحديث الأسعار والسكور تلقائياً كل 10 ثوانٍ</p>
        <table>
            <thead><tr><th>العملة</th><th>الوقت</th><th>الدخول</th><th>الحالي</th><th>السكور</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </body></html>
    """

if __name__ == "__main__":
    # تشغيل Flask
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080), daemon=True).start()
    # تشغيل المحرك
    asyncio.get_event_loop().run_until_complete(market_engine())
