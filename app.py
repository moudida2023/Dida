import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import os
import time
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات الأساسية ========================
# تأكد من وضع التوكن الخاص بك والـ ID الصحيح
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# إعدادات المنصة (Binance لجلب أدق الأسعار)
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# إعدادات المحفظة الوهمية
VIRTUAL_BALANCE = 1000.0
TRADE_SIZE_USD = 100.0  # قيمة الدخول في كل صفقة
PROFIT_TARGET_USD = 1.1 # الربح المطلوب بالدولار لإغلاق الصفقة

portfolio = {"open_trades": {}}
closed_trades_history = []

# ======================== 2. نظام الإشعارات والتقارير ========================

def send_telegram_msg(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def generate_report_text():
    """توليد نص التقرير الشامل"""
    open_msg = "📂 *الاصفقات المفتوحة حالياً:*\n"
    if not portfolio["open_trades"]:
        open_msg += "_لا توجد صفقات نشطة حالياً_\n"
    else:
        for sym, data in portfolio["open_trades"].items():
            open_msg += f"• `{sym}` | دخول: {data['entry_price']:.4f}\n"

    total_closed = len(closed_trades_history)
    wins = sum(1 for t in closed_trades_history if t['pnl'] > 0)
    total_pnl = sum(t['pnl'] for t in closed_trades_history)
    
    report = (
        f"{open_msg}\n"
        f"📊 *ملخص الأداء العام:*\n"
        f"✅ صفقات ناجحة: {wins}\n"
        f"❌ صفقات خاسرة: {total_closed - wins}\n"
        f"💰 صافي الأرباح: `${total_pnl:.2f}`\n"
        f"💵 الرصيد المتوفر: `${VIRTUAL_BALANCE:.2f}`"
    )
    return report

# ======================== 3. مستمع الأوامر (Command Listener) ========================

def telegram_command_listener():
    """هذه الدالة تجعل البوت يرد عليك عند إرسال /report"""
    last_update_id = -1
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=30"
            response = requests.get(url, timeout=35).json()
            
            if response.get("result"):
                for update in response["result"]:
                    last_update_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        chat_id = str(update["message"]["chat"]["id"])
                        user_text = update["message"]["text"].lower()

                        # الرد فقط على صاحب الحساب
                        if chat_id == TELEGRAM_CHAT_ID:
                            if user_text in ["/report", "تقرير", "/status"]:
                                report = generate_report_text()
                                send_telegram_msg(f"📋 *تقرير عند الطلب:*\n{report}")
                            elif user_text == "/start":
                                send_telegram_msg("أهلاً بك! أنا بوت القناص. أرسل `/report` في أي وقت لمتابعة أرباحك.")
        except:
            time.sleep(5)
        time.sleep(1)

# ======================== 4. منطق التداول (التحليل والقنص) ========================

async def scan_market():
    global VIRTUAL_BALANCE
    try:
        tickers = await EXCHANGE.fetch_tickers()
        # اختيار أفضل 50 عملة من حيث السيولة
        symbols = [s for s in tickers.keys() if '/USDT' in s and (tickers[s]['quoteVolume'] or 0) > 2000000]
        top_symbols = sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:50]
        
        for sym in top_symbols:
            if sym in portfolio["open_trades"] or VIRTUAL_BALANCE < TRADE_SIZE_USD: continue

            # تحليل شمعة الـ 15 دقيقة
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=50)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[-1]
            last = df.iloc[-1]
            
            # حساب السكور الصارم (5/5)
            score = 0
            if last['close'] > ema9: score += 1
            if last['close'] > last['open']: score += 1
            if last['vol'] > df['vol'].rolling(10).mean().iloc[-1]: score += 1
            if last['close'] > df['high'].iloc[-2]: score += 1 # كسر قمة الشمعة السابقة
            if last['close'] > df['close'].iloc[-2]: score += 1 # استمرار صعودي

            if score == 5:
                entry_price = last['close']
                coins = TRADE_SIZE_USD / entry_price
                
                portfolio["open_trades"][sym] = {
                    "entry_price": entry_price,
                    "amount_usd": TRADE_SIZE_USD,
                    "coins": coins,
                    "time": datetime.now()
                }
                VIRTUAL_BALANCE -= TRADE_SIZE_USD
                send_telegram_msg(f"🚀 *إشعار دخول (5/5)*\n🎫 العملة: {sym}\n💵 السعر: {entry_price:.6f}\n💰 القيمة: $100")
                if len(portfolio["open_trades"]) >= 5: break # حد أقصى 5 صفقات

    except Exception as e:
        print(f"Scan Error: {e}")

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                
                profit_usd = (cp - trade['entry_price']) * trade['coins']
                
                # إغلاق عند ربح 1.1$ أو خسارة 2.0$
                reason = None
                if profit_usd >= PROFIT_TARGET_USD: reason = "🎯 جني أرباح (+1.1$)"
                elif profit_usd <= -2.0: reason = "🛑 وقف خسارة (-2.0$)"

                if reason:
                    VIRTUAL_BALANCE += (trade['amount_usd'] + profit_usd)
                    closed_trades_history.append({"sym": sym, "pnl": profit_usd, "time": datetime.now()})
                    portfolio["open_trades"].pop(sym)
                    send_telegram_msg(f"🏁 *إشعار خروج*\n🎫 {sym}\n📝 السبب: {reason}\n💰 الربح/الخسارة: {profit_usd:+.2f}$")

            await asyncio.sleep(20)
        except: await asyncio.sleep(10)

# ======================== 5. الخادم والتشغيل النهائي ========================

app = Flask('')
@app.route('/')
def home(): 
    return f"Bot v624 Active - Balance: {VIRTUAL_BALANCE:.2f}$"

async def main_loop():
    send_telegram_msg("✅ *تم تفعيل نظام القناص v624*\nأرسل `/report` في أي وقت لرؤية الأداء.")
    asyncio.create_task(manage_trades())
    while True:
        await scan_market()
        await asyncio.sleep(60)

if __name__ == "__main__":
    # تشغيل مستمع الأوامر في خيط منفصل
    threading.Thread(target=telegram_command_listener, daemon=True).start()
    
    # تشغيل Flask على منفذ Render
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    
    # تشغيل محرك البحث عن الصفقات
    asyncio.run(main_loop())
