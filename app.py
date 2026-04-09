Aucun élément sélectionné

Aller au contenu
Utiliser Gmail avec un lecteur d'écran
Activez les notifications sur le bureau pour Gmail.
   OK  Non, merci
Conversations
63 % sur 15 Go utilisés
Conditions d'utilisation · Confidentialité · Règlement du programme
Dernière activité sur le compte : il y a 2 heures
Détails
import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
from flask import Flask
from datetime import datetime
import time

# ======================== 1. الإعدادات (تأكد من تعديلها) ========================
TELEGRAM_TOKEN = 'YOUR_BOT_TOKEN'
TELEGRAM_CHAT_ID = 'YOUR_CHAT_ID'
YOUR_RENDER_URL = "https://your-app-name.onrender.com"

# إعدادات المحفظة
INITIAL_BALANCE = 1000
TRADE_AMOUNT = 50
MAX_TRADES = 20

# إعدادات التداول
STOP_LOSS_PCT = -0.03        # وقف خسارة عند -3%
TRAILING_START = 0.02        # بدء التتبع عند ربح +2%
TRAILING_GAP = 0.015         # مسافة التتبع 1.5%
TAKE_PROFIT_PARTIAL = 0.04   # جني أرباح 50% من الكمية عند +4%
TIME_EXIT_HOURS = 6          # إغلاق الصفقة آلياً بعد 6 ساعات

# القائمة السوداء (عملات مستقرة وعملات ثقيلة جداً)
BLACKLIST = [
    'USDC/USDT', 'FDUSD/USDT', 'TUSD/USDT', 'DAI/USDT', 'WBTC/USDT', 
    'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT', 'DOGE/USDT'
]

EXCHANGE = ccxt.binance({'enableRateLimit': True})
portfolio = {"balance": INITIAL_BALANCE, "open_trades": {}}

# ======================== 2. المعادلات الفنية (المؤشرات) ========================
def calculate_indicators(df):
    close = df['close']
    high = df['high']
    low = df['low']
    
    # المتوسطات والبولنجر
    df['ema9'] = close.ewm(span=9, adjust=False).mean()
    df['ema21'] = close.ewm(span=21, adjust=False).mean()
    df['sma200'] = close.rolling(window=200).mean()
    df['sma20'] = close.rolling(window=20).mean()
    df['std20'] = close.rolling(window=20).std()
    df['bandwidth'] = (4 * df['std20']) / df['sma20'] # Bollinger Bandwidth
    
    # مؤشر RSI
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))

    # مؤشر ADX
    plus_dm = high.diff().clip(lower=0)
    minus_dm = low.diff().clip(upper=0).abs()
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    plus_di = 100 * (plus_dm.rolling(14).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(14).mean() / atr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    df['adx'] = dx.rolling(14).mean()
    
    return df

def calculate_score(df):
    if len(df) < 200: return 0
    df = calculate_indicators(df)
    last = df.iloc[-1]
    score = 0
    
    if last['close'] > last['sma200']: score += 1
    if last['adx'] > 25: score += 1
    if last['ema9'] > last['ema21']: score += 1
    if last['rsi'] > 50: score += 1
    
    # فحص انفجار البولنجر (Squeeze)
    min_bw = df['bandwidth'].rolling(100).min().iloc[-1]
    if last['bandwidth'] < min_bw * 1.15: score += 2
    
    return score

# ======================== 3. فلاتر البيتكوين وإدارة الصفقات ========================
async def get_btc_trend():
    """فلتر البيتكوين على فريم 15 دقيقة"""
    try:
        bars = await EXCHANGE.fetch_ohlcv('BTC/USDT', timeframe='15m', limit=50)
        df = pd.DataFrame(bars, columns=['ts','o','h','l','c','v'])
        ema50 = df['c'].ewm(span=50, adjust=False).mean().iloc[-1]
        return df['c'].iloc[-1] > ema50
    except: return False

async def manage_trades():
    if not portfolio["open_trades"]: return
    symbols = list(portfolio["open_trades"].keys())
    tickers = await EXCHANGE.fetch_tickers(symbols)
    now = datetime.now()
    
    for sym in symbols:
        curr_p = tickers[sym]['last']
        trade = portfolio["open_trades"][sym]
        pnl = (curr_p - trade['entry_price']) / trade['entry_price']
        hours_passed = (now - trade['entry_time']).total_seconds() / 3600

        if curr_p > trade['highest_p']:
            portfolio["open_trades"][sym]['highest_p'] = curr_p

        # جني أرباح جزئي (بيع 50% عند 4%)
        if pnl >= TAKE_PROFIT_PARTIAL and not trade['partial_sold']:
            portfolio["balance"] += (TRADE_AMOUNT * 0.5) * (1 + pnl)
            portfolio["open_trades"][sym]['partial_sold'] = True
            send_telegram_msg(f"💰 *جني ربح جزئي (+4%):* {sym}")

        # إغلاق زمني (بعد 6 ساعات)
        if hours_passed >= TIME_EXIT_HOURS:
            ratio = 0.5 if trade['partial_sold'] else 1.0
            portfolio["balance"] += (TRADE_AMOUNT * ratio) * (1 + pnl)
            send_telegram_msg(f"⏳ *إغلاق زمني (6س):* {sym}\nالربح: {pnl:+.2f}%")
            del portfolio["open_trades"][sym]
            continue

        # وقف الخسارة والتتبع
        reason = None
        if pnl <= STOP_LOSS_PCT: 
            reason = "Stop Loss 🛑"
        elif (trade['highest_p'] - trade['entry_price']) / trade['entry_price'] >= TRAILING_START:
            if curr_p <= trade['highest_p'] * (1 - TRAILING_GAP):
                reason = "Trailing Stop ✅"

        if reason:
            ratio = 0.5 if trade['partial_sold'] else 1.0
            portfolio["balance"] += (TRADE_AMOUNT * ratio) * (1 + pnl)
            send_telegram_msg(f"🚪 *خروج:* {sym}\nالسبب: {reason}\nالنتيجة: {pnl:+.2f}%")
            del portfolio["open_trades"][sym]

# ======================== 4. مسح السوق بنظام الدفعات (500 عملة) ========================
async def scan_market():
    if len(portfolio["open_trades"]) >= MAX_TRADES: return
    if not await get_btc_trend(): return 

    markets = await EXCHANGE.fetch_tickers()
    # استبعاد القائمة السوداء والعملات المستقرة
    symbols = [s for s in markets.keys() if '/USDT' in s and s not in BLACKLIST and 'USD' not in s.split('/')[0]]
    
    # اختيار 500 عملة مع استبعاد الـ 10 الكبار (الحيتان)
    top_symbols = sorted(symbols, key=lambda x: markets[x]['quoteVolume'] or 0, reverse=True)[10:510]
    
    batch_size = 100
    for i in range(0, len(top_symbols), batch_size):
        batch = top_symbols[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        
        for sym in batch:
            if sym in portfolio["open_trades"]: continue
            try:
                bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='15m', limit=210)
                df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
                if calculate_score(df) >= 4:
                    entry_p = df['close'].iloc[-1]
                    portfolio["balance"] -= TRADE_AMOUNT
                    portfolio["open_trades"][sym] = {
                        "entry_price": entry_p, 
                        "highest_p": entry_p, 
                        "entry_time": datetime.now(), 
                        "partial_sold": False
                    }
                    send_telegram_msg(f"🚀 *دخول فوري (دفعة {batch_num}):* {sym}\nالسعر: {entry_p}")
                    if len(portfolio["open_trades"]) >= MAX_TRADES: return
                await asyncio.sleep(0.02) # حماية من الحظر
            except: continue
        
        print(f"✅ تم مسح الدفعة {batch_num} (100 عملة)")

    print("🏁 تم مسح كامل السوق (500 عملة) بنجاح.")

# ======================== 5. نظام التشغيل والـ Keep-Alive ========================
def send_telegram_msg(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

app = Flask('')
@app.route('/')
def home(): return "Snowball V5.5 Active!"

def run_server(): app.run(host='0.0.0.0', port=8080)

def pinger():
    while True:
        try: requests.get(YOUR_RENDER_URL, timeout=10)
        except: pass
        time.sleep(300)

async def main_loop():
    send_telegram_msg("⚡ *Snowball V5.5* بدأ العمل الآن!\nيتم فحص 500 عملة بنظام الدفعات.")
    while True:
        try:
            await manage_trades()
            await scan_market()
            await asyncio.sleep(60) # راحة لمدة دقيقة بين كل دورة مسح كاملة
        except Exception as e:
            print(f"Error: {e}"); await asyncio.sleep(20)

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=pinger, daemon=True).start()
    asyncio.run(main_loop())
app - 2026-04-08T140916.616.py
Affichage de app - 2026-04-08T140916.616.py en cours...
