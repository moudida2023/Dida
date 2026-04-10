import asyncio
import ccxt.pro as ccxt
import pandas as pd
import psycopg2
from psycopg2 import extras
import os
import threading
import requests
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات والربط ========================
app = Flask(__name__)

DB_URL = os.environ.get('DATABASE_URL', 'your_postgresql_url_here')
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'

# --- إعدادات الاستراتيجية المحسنة ---
INITIAL_BALANCE = 1000.0
TRADE_AMOUNT = 50.0
MAX_OPEN_TRADES = 20
STOP_LOSS_PCT = -0.03       # وقف خسارة 3%
MIN_PROFIT_FOR_EXIT = 0.03  # ربح أدنى 3% للخروج بالسكور
EXIT_SCORE_THRESHOLD = 95    # سكور الخروج
MIN_VOLUME_24H = 1000000    # الحد الأدنى للسيولة (1 مليون دولار)

# قائمة الاستبعاد (العملات الكبيرة جداً)
EXCLUDED_COINS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT', 'DOT/USDT', 'LTC/USDT']

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

def send_telegram_msg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=5)
    except: pass

# ======================== 2. محرك التحليل الفني ========================

async def perform_analysis(sym, exchange_instance):
    try:
        bars = await exchange_instance.fetch_ohlcv(sym, timeframe='1h', limit=40)
        df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        close = df['close']
        
        score = 0
        # Bollinger Squeeze
        ma20 = close.rolling(20).mean(); std20 = close.rolling(20).std()
        bw = ((ma20 + 2*std20) - (ma20 - 2*std20)) / (ma20 + 1e-9)
        if bw.iloc[-1] < 0.045: score += 50 
        
        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 40 < rsi.iloc[-1] < 70: score += 45 
        
        return int(score), close.iloc[-1]
    except: return 0, 0

# ======================== 3. منطق الاختيار النخبوي ========================

async def main_engine():
    print(f"🚀 تشغيل v126 | السيولة > {MIN_VOLUME_24H}$ | اختيار الأفضل فقط")
    EXCHANGE = ccxt.gateio({'enableRateLimit': True})
    
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            
            # فلترة أولية صارمة قبل بدء التحليل المعقد
            valid_symbols = []
            for s, t in tickers.items():
                if '/USDT' in s and s not in EXCLUDED_COINS and '3L' not in s and '3S' not in s:
                    change_24h = t.get('percentage', 0) or 0
                    volume_24h = t.get('quoteVolume', 0) or 0
                    
                    # تطبيق الفلاتر (ارتفاع < 5% وسيولة > 1 مليون)
                    if change_24h <= 5.0 and volume_24h >= MIN_VOLUME_24H:
                        valid_symbols.append(s)

            scored_candidates = []
            # مسح أفضل 80 عملة اجتازت الفلتر (مرتبة حسب الحجم لضمان السيولة)
            valid_symbols = sorted(valid_symbols, key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)

            for sym in valid_symbols[:80]:
                score, _ = await perform_analysis(sym, EXCHANGE)
                if score >= 70:
                    scored_candidates.append({
                        'symbol': sym, 
                        'score': score, 
                        'price': tickers[sym]['last'],
                        'vol': tickers[sym]['quoteVolume'],
                        'change': tickers[sym]['percentage']
                    })
                await asyncio.sleep(0.01)

            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=extras.DictCursor)
            now_time = datetime.now().strftime('%H:%M:%S')

            if scored_candidates:
                # اختيار "صاحب أعلى سكور" في السوق حالياً
                scored_candidates.sort(key=lambda x: x['score'], reverse=True)
                best = scored_candidates[0]
                
                if best['score'] >= 85:
                    cur.execute("SELECT COUNT(*) FROM trades WHERE symbol = %s AND status = 'OPEN'", (best['symbol'],))
                    if cur.fetchone()[0] == 0:
                        cur.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
                        if cur.fetchone()[0] < MAX_OPEN_TRADES:
                            cur.execute('''INSERT INTO trades (symbol, entry_price, current_price, investment, status, score, open_time) 
                                         VALUES (%s, %s, %s, %s, 'OPEN', %s, %s)''', 
                                         (best['symbol'], best['price'], best['price'], TRADE_AMOUNT, best['score'], now_time))
                            send_telegram_msg(f"💎 *فرصة ذهبية مختارة*\n🪙 `{best['symbol']}`\n📊 السكور: `{best['score']}`\n💰 السعر: `{best['price']}`\n🌊 السيولة: `${best['vol']/1e6:.1f}M`\n📈 نمو 24س: `{best['change']:.2f}%`")

            # إدارة الصفقات المفتوحة
            cur.execute("SELECT * FROM trades WHERE status = 'OPEN'")
            for ot in cur.fetchall():
                current_p = tickers[ot['symbol']]['last'] if ot['symbol'] in tickers else ot['current_price']
                change = (current_p - ot['entry_price']) / ot['entry_price']
                
                # فحص الخروج بناءً على السكور الجديد والربح
                s_score, _ = await perform_analysis(ot['symbol'], EXCHANGE)
                
                exit_now = False
                if change <= STOP_LOSS_PCT:
                    exit_now = True; reason = "🛑 وقف خسارة (-3%)"
                elif s_score >= EXIT_SCORE_THRESHOLD and change >= MIN_PROFIT_FOR_EXIT:
                    exit_now = True; reason = f"🎯 جني أرباح (Score: {s_score})"

                if exit_now:
                    cur.execute("UPDATE trades SET exit_price=%s, status='CLOSED', close_time=%s WHERE symbol=%s", (current_p, now_time, ot['symbol']))
                    send_telegram_msg(f"{reason}\n🪙 `{ot['symbol']}` | 📈 `{change*100:+.2f}%` | 💵 `${current_p}`")
                else:
                    cur.execute("UPDATE trades SET current_price=%s WHERE symbol=%s", (current_p, ot['symbol']))

            conn.commit()
            cur.close(); conn.close()
            await asyncio.sleep(20)
        except Exception as e:
            print(f"⚠️ خطأ: {e}")
            await asyncio.sleep(15)

# ======================== 4. واجهة العرض والتشغيل ========================
@app.route('/')
def index():
    # كود عرض بسيط للإحصائيات (يمكنك توسيعه)
    return "Bot v126 is running... Check Telegram for signals."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    asyncio.run(main_engine())
