import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
from datetime import datetime, timedelta

# ======================== 1. الإعدادات ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0
portfolio = {"open_trades": {}}
closed_trades_log = [] # سجل لمتابعة الأداء

# ======================== 2. أدوات الحساب والتحليل ========================

def calculate_exit_points(df):
    """حساب أهداف الخروج بناءً على فيبوناتشي والقمم السابقة"""
    recent_peak = df['high'].max()
    recent_low = df['low'].min()
    entry_price = df.iloc[-1]['close']
    
    # الهدف هو مستوى 50% من موجة الصعود
    target_price = recent_peak - (recent_peak - recent_low) * 0.5
    # وقف الخسارة فوق القمة بـ 1.5%
    stop_loss = recent_peak * 1.015
    
    # حساب نسبة النزول المتوقعة
    expected_drop_pct = ((entry_price - target_price) / entry_price) * 100
    
    return target_price, stop_loss, expected_drop_pct

def detect_signal(df):
    """اكتشاف شمعة الانعكاس وتأكيد الحجم"""
    prev = df.iloc[-2]
    last = df.iloc[-1]
    avg_vol = df['vol'].rolling(10).mean().iloc[-2]
    
    body = abs(prev['close'] - prev['open'])
    upper_wick = prev['high'] - max(prev['open'], prev['close'])
    
    # شرط الشهاب + إغلاق تأكيدي تحت القاع + حجم أعلى من المتوسط
    if upper_wick > (1.8 * body) and last['close'] < prev['low'] and prev['vol'] > avg_vol:
        return True
    return False

# ======================== 3. منطق الفلترة والدخول = : 5% MIN ========================

async def scan_market():
    try:
        tickers = await EXCHANGE.fetch_tickers()
        # فلترة أولية: صعود > 10% وسيولة > 5 مليون
        symbols = [s for s in tickers.keys() if '/USDT' in s 
                   and (tickers[s]['percentage'] or 0) > 10 
                   and (tickers[s]['quoteVolume'] or 0) > 5000000]
        
        for sym in symbols:
            if sym in portfolio["open_trades"]: continue
            
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=40)
            df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
            
            if detect_signal(df):
                tp, sl, drop_pct = calculate_exit_points(df)
                
                # --- الفلتر المطلوب: لا ترسل الصفقة إذا كان النزول المتوقع أقل من 5% ---
                if drop_pct < 5.0:
                    print(f"⚠️ تجاهل {sym}: الربح المتوقع ({drop_pct:.2f}%) أقل من 5%")
                    continue
                
                entry_p = df.iloc[-1]['close']
                portfolio["open_trades"][sym] = {
                    "entry_price": entry_p,
                    "target": tp,
                    "stop_loss": sl,
                    "entry_time": datetime.now()
                }

                msg = (
                    f"🚀 *إشارة دخول مؤكدة (SHORT)*\n"
                    f"---------------------------\n"
                    f"🎫 العملة: {sym}\n"
                    f"📉 النزول المتوقع: {drop_pct:.2f}%\n"
                    f"💰 سعر الدخول: {entry_p:.6f}\n"
                    f"🎯 جني الأرباح (TP): {tp:.6f}\n"
                    f"🛑 وقف الخسارة (SL): {sl:.6f}\n"
                    f"---------------------------"
                )
                send_telegram_msg(msg)
                
    except Exception as e: print(f"Error: {e}")

# ======================== 4. إدارة العمليات والتقارير ========================

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        for sym in list(portfolio["open_trades"].keys()):
            try:
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                
                pnl_pct = (trade['entry_price'] - cp) / trade['entry_price'] * 100
                duration = datetime.now() - trade['entry_time']

                reason = None
                if cp <= trade['target']: reason = "🎯 تم ضرب الهدف"
                elif cp >= trade['stop_loss']: reason = "🛑 ضرب وقف الخسارة"
                elif duration > timedelta(hours=4): reason = "⏰ خروج زمني (4س)"

                if reason:
                    VIRTUAL_BALANCE += 100 * (1 + (pnl_pct/100))
                    res_icon = "✅ ربح" if pnl_pct > 0 else "❌ خسارة"
                    closed_trades_log.append({"sym": sym, "pnl": pnl_pct})
                    
                    msg = (
                        f"🏁 *تقرير إغلاق صفقة*\n"
                        f"---------------------------\n"
                        f"🎫 العملة: {sym}\n"
                        f"📊 النتيجة: {res_icon} ({pnl_pct:+.2f}%)\n"
                        f"📝 السبب: {reason}\n"
                        f"⏳ المدة: {str(duration).split('.')[0]}\n"
                        f"💰 الرصيد الجديد: ${VIRTUAL_BALANCE:.2f}"
                    )
                    send_telegram_msg(msg)
                    del portfolio["open_trades"][sym]
            except: continue
        await asyncio.sleep(30)

async def hourly_report():
    """تقرير أداء شامل كل ساعة"""
    while True:
        await asyncio.sleep(3600)
        total_pnl = sum([t['pnl'] for t in closed_trades_log])
        msg = (
            f"📊 *التقرير الدوري للأداء*\n"
            f"---------------------------\n"
            f"💰 الرصيد الحالي: ${VIRTUAL_BALANCE:.2f}\n"
            f"📈 صافي الربح اليومي: {total_pnl:+.2f}%\n"
            f"📦 صفقات مفتوحة: {len(portfolio['open_trades'])}\n"
            f"✅ صفقات مغلقة: {len(closed_trades_log)}\n"
            f"---------------------------"
        )
        send_telegram_msg(msg)

# ======================== 5. تشغيل النظام ========================

def send_telegram_msg(msg):
    for chat_id in DESTINATIONS:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
        except: pass

async def main():
    send_telegram_msg("🏗️ *نظام Snowball المطور يعمل الآن*\nتم تفعيل فلتر الربح الأدنى 5% والتقارير الآلية.")
    await asyncio.gather(manage_trades(), hourly_report(), scanner_loop())

async def scanner_loop():
    while True:
        await scan_market()
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
