import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات الأساسية ========================
app = Flask('')
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']

# إعداد المنصة مع حماية مدمجة من الحظر
EXCHANGE = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# قائمة العملات المستبعدة (العملات المستقرة والقيادية جداً)
EXCLUDE_LIST = ['TUSD/USDT', 'USDC/USDT', 'FDUSD/USDT', 'USDT/USDT', 'BTC/USDT', 'ETH/USDT', 'BNB/USDT']

# متغيرات النظام
OPEN_TRADES = {}     
SEARCH_HISTORY = [] 
CURRENT_BALANCE = 500.0

# عتبات التحكم
TABLE_SCORE_LEVEL = 50   # للظهور في الجدول
TRADE_SCORE_LEVEL = 85   # للشراء الفعلي

# ======================== 2. واجهة العرض (Dashboard) ========================

@app.route('/')
def home():
    # إنشاء جدول الصفقات المفتوحة
    trades_rows = ""
    for sym, data in OPEN_TRADES.items():
        pnl = ((data['current'] - data['entry']) / data['entry']) * 100
        color = "#00ff00" if pnl >= 0 else "#ff4444"
        trades_rows += f"""
        <tr>
            <td>{sym}</td>
            <td>{data['entry']:.6f}</td>
            <td>{data['current']:.6f}</td>
            <td style="color:{color}; font-weight:bold;">{pnl:+.2f}%</td>
            <td>{data.get('score')}</td>
        </tr>"""

    # إنشاء جدول الرادار التاريخي (آخر 40 فرصة)
    history_rows = ""
    # نسخة من السجل لتجنب أخطاء التزامن أثناء البحث
    safe_history = list(SEARCH_HISTORY)
    for item in reversed(safe_history[-40:]):
        history_rows += f"""
        <tr>
            <td>{item['time']}</td>
            <td><strong>{item['sym']}</strong></td>
            <td><span style="color:#f0b90b;">{item['score']}</span></td>
            <td>{item['price']:.6f}</td>
        </tr>"""

    return f"""
    <html><head>
        <title>Sniper Elite v17 - Final</title>
        <meta http-equiv="refresh" content="30">
        <style>
            body {{ background: #0b0e11; color: #eaecef; font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; text-align: center; }}
            .header {{ background: #1e2329; padding: 20px; border-bottom: 3px solid #f0b90b; border-radius: 10px; }}
            .stats {{ display: flex; justify-content: space-around; background: #181a20; padding: 15px; margin: 20px 0; border-radius: 8px; }}
            table {{ width: 100%; border-collapse: collapse; background: #1e2329; margin-top: 10px; border-radius: 8px; overflow: hidden; }}
            th, td {{ padding: 12px; border: 1px solid #2b3139; text-align: center; }}
            th {{ background: #2b3139; color: #f0b90b; }}
            h2 {{ color: #f0b90b; border-left: 5px solid #f0b90b; padding-left: 10px; text-align: left; }}
        </style>
    </head>
    <body>
        <div class="header"><h1>🎯 Sniper Elite v17 (النسخة النهائية)</h1></div>
        <div class="stats">
            <div>الرصيد: <b>{CURRENT_BALANCE:.2f} USDT</b></div>
            <div>الصفقات النشطة: <b>{len(OPEN_TRADES)}</b></div>
            <div>العملات في الرادار: <b>{len(SEARCH_HISTORY)}</b></div>
        </div>
        
        <h2>💎 الصفقات الحالية</h2>
        <table>
            <thead><tr><th>العملة</th><th>سعر الدخول</th><th>السعر الحالي</th><th>الربح/الخسارة</th><th>السكور</th></tr></thead>
            <tbody>{trades_rows if trades_rows else "<tr><td colspan='5'>لا توجد صفقات مفتوحة حالياً</td></tr>"}</tbody>
        </table>

        <h2>🏆 رادار الفرص المكتشفة (سكور {TABLE_SCORE_LEVEL}+)</h2>
        <table>
            <thead><tr><th>الوقت</th><th>العملة</th><th>السكور الفني</th><th>سعر الرصد</th></tr></thead>
            <tbody>{history_rows if history_rows else "<tr><td colspan='4'>جاري مسح السوق... انتظر قليلاً</td></tr>"}</tbody>
        </table>
    </body></html>"""

# ======================== 3. محرك التحليل والبحث ========================

async def calculate_score(sym):
    try:
        # جلب بيانات الشموع (Limit قليل لتوفير البيانات)
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=40)
        if len(bars) < 30: return 0, 0
        
        df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
        score = 0
        
        # 1. فلتر الاتجاه (EMA 200) - 30 نقطة
        ema = df['close'].ewm(span=200).mean().iloc[-1]
        if df['close'].iloc[-1] > ema: score += 30
        
        # 2. فلتر السيولة (Volume) - 30 نقطة
        avg_vol = df['vol'].rolling(20).mean().iloc[-1]
        if df['vol'].iloc[-1] > avg_vol: score += 30
        
        # 3. فلتر القوة النسبية (RSI) - 40 نقطة
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9)))).iloc[-1]
        if 45 < rsi < 75: score += 40
        
        return int(score), df['close'].iloc[-1]
    except:
        return 0, 0

async def main_engine():
    global SEARCH_HISTORY, OPEN_TRADES
    while True:
        try:
            # جلب كل الأسعار بطلب واحد (توفيراً للـ Rate Limit)
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and s not in EXCLUDE_LIST]
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] بدأ فحص {len(symbols)} عملة...")

            for sym in symbols:
                score, price = await calculate_score(sym)
                
                # تحديث الجدول فورياً
                if score >= TABLE_SCORE_LEVEL:
                    # التحقق من عدم التكرار في آخر دورة
                    if sym not in [x['sym'] for x in SEARCH_HISTORY[-15:]]:
                        SEARCH_HISTORY.append({
                            'sym': sym, 'score': score, 'price': price,
                            'time': datetime.now().strftime('%H:%M:%S')
                        })
                        if len(SEARCH_HISTORY) > 60: SEARCH_HISTORY.pop(0)

                # تنفيذ الشراء الآلي
                if score >= TRADE_SCORE_LEVEL and sym not in OPEN_TRADES:
                    OPEN_TRADES[sym] = {'entry': price, 'current': price, 'score': score}
                    send_telegram(f"🚀 *إشارة دخول قوية!*\nالعملة: {sym}\nالسكور: {score}\nالسعر: {price}")
                
                # تأخير 0.05 ثانية بين كل عملة لحماية الـ IP من الحظر
                await asyncio.sleep(0.05)

            print("--- انتهاء المسح. راحة لمدة 5 دقائق ---")
            await asyncio.sleep(300) 
            
        except Exception as e:
            print(f"خطأ في المحرك: {e}")
            await asyncio.sleep(60)

def send_telegram(msg):
    for cid in DESTINATIONS:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                          json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        except:
            pass

# ======================== 4. بدء التشغيل ========================

if __name__ == "__main__":
    # تشغيل سيرفر الويب
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    
    # تشغيل البوت
    loop = asyncio.get_event_loop()
    loop.create_task(main_engine())
    loop.run_forever()
