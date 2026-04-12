import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
from flask import Flask

# ======================== 1. الإعدادات والتوكنز ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0
BASE_TRADE_USD = 100.0
TRAILING_TRIGGER = 0.02    # يبدأ الملاحقة عند 2%
TRAILING_CALLBACK = 0.005  # يغلق إذا نزل 0.5% من القمة

portfolio = {"open_trades": {}}

# ======================== 2. محرك التحليل واكتشاف الانفجار ========================

def get_indicators(df):
    """حساب المؤشرات الفنية بدقة"""
    # متوسطات ومؤشرات زخم
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    
    # بولنجر باند (لاكتشاف الضغط)
    basis = df['close'].rolling(window=20).mean()
    std = df['close'].rolling(window=20).std()
    df['upper'] = basis + (std * 2)
    df['lower'] = basis - (std * 2)
    df['bandwidth'] = (df['upper'] - df['lower']) / basis
    
    # مؤشر تدفق السيولة MFI
    tp = (df['high'] + df['low'] + df['close']) / 3
    mf = tp * df['vol']
    pos = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    df['mfi'] = 100 - (100 / (1 + (pos / neg)))
    
    return df

async def is_h4_trend_up(sym):
    """تأكيد الاتجاه العام (الشرط الثامن)"""
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='4h', limit=20)
        df_h4 = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
        ema20 = df_h4['close'].ewm(span=20).mean().iloc[-1]
        return df_h4['close'].iloc[-1] > ema20
    except: return False

# ======================== 3. منطق القناص (8/8 + Ignition) ========================

async def scan_market():
    global VIRTUAL_BALANCE
    if len(portfolio["open_trades"]) >= 10 or VIRTUAL_BALANCE < BASE_TRADE_USD: return

    try:
        tickers = await EXCHANGE.fetch_tickers()
        # تصفية العملات ذات السيولة العالية (أكثر من 2 مليون دولار)
        symbols = [s for s in tickers.keys() if '/USDT' in s and tickers[s]['quoteVolume'] > 2000000]
        
        for sym in sorted(symbols, key=lambda x: tickers[x]['quoteVolume'], reverse=True)[:40]:
            if sym in portfolio["open_trades"] or 'UP/' in sym or 'DOWN/' in sym: continue
            
            bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=100)
            df = get_indicators(pd.DataFrame(bars, columns=['ts','open','high','low','close','vol']))
            last = df.iloc[-1]
            prev = df.iloc[-2]
            
            # --- مصفوفة السكور 8/8 ---
            score = 0
            if last['close'] > last['ema9']: score += 1                # 1
            if last['close'] > last['open']: score += 1                # 2
            if last['vol'] > df['vol'].tail(10).mean(): score += 1      # 3
            if last['close'] > prev['high']: score += 1                # 4
            if last['close'] > prev['close']: score += 1               # 5
            if last['mfi'] > 60: score += 1                            # 6
            if last['bandwidth'] < df['bandwidth'].tail(50).mean(): score += 1 # 7 (الضغط)
            if await is_h4_trend_up(sym): score += 1                   # 8 (الاتجاه)

            # --- فلتر شرارة الانفجار (Ignition) ---
            # الدخول فقط إذا اخترق السعر بقوة مع فوليوم عالي (ضعف المتوسط)
            vol_ignition = last['vol'] > (df['vol'].tail(10).mean() * 1.8)
            price_ignition = last['close'] > prev['high']

            if score == 8 and vol_ignition and price_ignition:
                entry_price = last['close']
                portfolio["open_trades"][sym] = {
                    "entry_price": entry_price,
                    "highest_price": entry_price,
                    "coins": BASE_TRADE_USD / entry_price,
                    "amount_usd": BASE_TRADE_USD,
                    "trailing_active": False
                }
                VIRTUAL_BALANCE -= BASE_TRADE_USD
                send_telegram_msg(f"🚀 **انفجار سعر مكتشف (8/8 + Ignition)**\n🪙 العملة: `{sym}`\n💵 السعر: {entry_price:.6f}\n⚡ الفوليوم: مرتفع جداً\n🎯 الملاحقة تبدأ عند +2%")
                break 
    except: pass

# ======================== 4. إدارة الأرباح والملاحقة ========================

async def manage_trades():
    global VIRTUAL_BALANCE
    while True:
        try:
            for sym in list(portfolio["open_trades"].keys()):
                trade = portfolio["open_trades"][sym]
                ticker = await EXCHANGE.fetch_ticker(sym)
                cp = ticker['last']
                
                # تحديث أعلى سعر للملاحقة
                if cp > trade['highest_price']:
                    portfolio["open_trades"][sym]['highest_price'] = cp
                
                profit_pct = (cp - trade['entry_price']) / trade['entry_price']
                
                # تفعيل الملاحقة عند 2%
                if profit_pct >= TRAILING_TRIGGER and not trade['trailing_active']:
                    portfolio["open_trades"][sym]['trailing_active'] = True
                    send_telegram_msg(f"📈 **تفعيل الملاحقة لعملة {sym}**\nوصلت لربح 2% وتطارد المزيد..")

                # تنفيذ الخروج عند تراجع السعر 0.5% من القمة
                if trade['trailing_active']:
                    drop_from_peak = (trade['highest_price'] - cp) / trade['highest_price']
                    if drop_from_peak >= TRAILING_CALLBACK:
                        pnl = (trade['coins'] * cp) - trade['amount_usd']
                        VIRTUAL_BALANCE += (trade['amount_usd'] + pnl)
                        portfolio["open_trades"].pop(sym)
                        send_telegram_msg(f"🎯 **تم الخروج وتأمين الربح**\n🎫 {sym}\n💰 الربح المحقق: ${pnl:.2f}")
                
                # وقف خسارة اضطراري (حماية 3%)
                elif profit_pct <= -0.03:
                    VIRTUAL_BALANCE += (trade['coins'] * cp)
                    portfolio["open_trades"].pop(sym)
                    send_telegram_msg(f"🛑 **وقف خسارة (3%)**\n🎫 {sym}")

            await asyncio.sleep(10)
        except: await asyncio.sleep(5)

# ======================== 5. نظام التشغيل ========================

def send_telegram_msg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

app = Flask('')
@app.route('/')
def home(): return f"Ignition Sniper 8/8 Active - Balance: {VIRTUAL_BALANCE:.2f}"

async def main_loop():
    send_telegram_msg("🔱 **تم تشغيل محرك قناص الانفجارات 8/8**\nنظام ملاحقة الأرباح +2% مفعّل.")
    asyncio.create_task(manage_trades())
    while True:
        await scan_market()
        await asyncio.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    asyncio.run(main_loop())
