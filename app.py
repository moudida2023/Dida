import asyncio
import ccxt
import pandas as pd
import requests
import os
from flask import Flask
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

# ======================== 1. الإعدادات العامة ========================
TELEGRAM_TOKEN = '8603477836:AAGG6Outg3Z9vBI-NjWQ3ALJroh_Cye3l2c'
# قائمة الـ IDs الخاصة بك وبأصدقائك
FRIENDS_IDS = ["5067771509", "2107567005"]

# إعداد المنصة (Binance)
exchange = ccxt.binance({'enableRateLimit': True})
app = Flask(__name__)

# مخزن البيانات لمتابعة الصفقات النشطة والتاريخ
portfolio = {"open_trades": {}}
closed_trades_history = []

# ======================== 2. نظام الإشعارات ========================
def send_telegram_msg(message):
    """إرسال رسالة لكل المشتركين في القائمة"""
    for chat_id in FRIENDS_IDS:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"Error sending to {chat_id}: {e}")

# ======================== 3. منطق فحص السوق (Scanner) ========================
def scan_for_explosion():
    print(f"🔍 فحص السوق الجاري: {datetime.now().strftime('%H:%M:%S')}")
    try:
        tickers = exchange.fetch_tickers()
        # تصفية العملات المرتبطة بـ USDT فقط والتي تملك سيولة جيدة
        symbols = [s for s in tickers if s.endswith('/USDT') and tickers[s]['quoteVolume'] > 1000000]
        sorted_symbols = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:30]
        
        for symbol in sorted_symbols:
            bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
            df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
            
            # حساب RSI
            delta = df['c'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / (loss + 1e-9)
            df['RSI'] = 100 - (100 / (1 + rs))
            
            # حساب Bollinger Squeeze (الانضغاط)
            df['MA20'] = df['c'].rolling(20).mean()
            df['STD'] = df['c'].rolling(20).std()
            df['Upper'] = df['MA20'] + (df['STD'] * 2)
            df['Lower'] = df['MA20'] - (df['STD'] * 2)
            df['Width'] = (df['Upper'] - df['Lower']) / df['MA20'] * 100
            
            last = df.iloc[-1]
            
            # شرط الانفجار: انضغاط تحت 2% وقوة نسبية rsi بين 50-60
            if last['Width'] < 2.0 and 50 <= last['RSI'] <= 60:
                if symbol not in portfolio["open_trades"]:
                    entry = last['c']
                    target = entry * 1.06
                    stop = entry * 0.97
                    
                    name = symbol.replace('/USDT', '')
                    msg = (
                        f"⚡️ *توصية انفجار سعري جديدة*\n"
                        f"---------------------------\n"
                        f"🎫 العملة: #{name}\n"
                        f"📥 سعر الدخول: {entry:.4f}\n"
                        f"🎯 الهدف (6%+): {target:.4f}\n"
                        f"🛑 الوقف (3%-): {stop:.4f}\n"
                        f"📊 RSI: {last['RSI']:.2f} | الضغط: {last['Width']:.2f}%\n"
                        f"---------------------------"
                    )
                    send_telegram_msg(msg)
                    
                    # تسجيل الصفقة للمتابعة
                    portfolio["open_trades"][symbol] = {
                        'entry_price': entry,
                        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'target': target,
                        'stop': stop
                    }
    except Exception as e:
        print(f"Scan Error: {e}")

# ======================== 4. إدارة الصفقات المفتوحة ========================
def manage_trades():
    """مراجعة الصفقات المفتوحة لإغلاقها آلياً في التقارير عند تحقق الشروط"""
    if not portfolio["open_trades"]:
        return

    for symbol in list(portfolio["open_trades"].keys()):
        try:
            trade = portfolio["open_trades"][symbol]
            ticker = exchange.fetch_ticker(symbol)
            cp = ticker['last']
            
            profit_pct = (cp - trade['entry_price']) / trade['entry_price'] * 100
            entry_dt = datetime.strptime(trade['time'], '%Y-%m-%d %H:%M:%S')
            hours_passed = (datetime.now() - entry_dt).total_seconds() / 3600

            exit_reason = None
            if cp >= trade['target']: exit_reason = "🎯 تم تحقيق الهدف"
            elif cp <= trade['stop']: exit_reason = "🛑 ضرب وقف الخسارة"
            elif hours_passed >= 24: exit_reason = "⏰ انتهاء الوقت (24 ساعة)"

            if exit_reason:
                msg = (
                    f"🏁 *إشعار إغلاق صفقة*\n"
                    f"العملة: {symbol}\n"
                    f"النتيجة: {profit_pct:+.2f}%\n"
                    f"السبب: {exit_reason}"
                )
                send_telegram_msg(msg)
                del portfolio["open_trades"][symbol]
        except:
            continue

# ======================== 5. خادم الويب والتشغيل الأساسي ========================
@app.route('/')
def home():
    return f"Bot Running. Active monitoring on {len(portfolio['open_trades'])} trades."

if __name__ == "__main__":
    # 1. إعداد المجدول الزمني ليعمل في الخلفية
    scheduler = BackgroundScheduler(daemon=True)
    # فحص السوق كل 15 دقيقة
    scheduler.add_job(scan_for_explosion, 'interval', minutes=15)
    # مراجعة أهداف الصفقات كل 5 دقائق
    scheduler.add_job(manage_trades, 'interval', minutes=5)
    scheduler.start()
    
    # 2. رسالة ترحيب عند التشغيل
    send_telegram_msg("🏗️ *Snowball V11.0* متصل الآن.\nيتم فحص أفضل 30 عملة سيولة كل 15 دقيقة.")
    
    # 3. تشغيل سيرفر Flask (متوافق مع Render/Heroku)
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
