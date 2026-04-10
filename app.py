import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
import json
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. إعدادات المسارات والقاعدة ========================
app = Flask('')
# تحديد المسار المطلق لضمان صلاحيات الكتابة على السيرفر
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.json")

EXCHANGE = ccxt.binance({'enableRateLimit': True})
MAX_OPEN_TRADES = 20
ENTRY_SCORE = 70      
INVESTMENT = 50.0
data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        # إنشاء الملف فوراً إذا لم يكن موجوداً
        if not os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, 'w') as f:
                    json.dump([], f)
            except Exception as e:
                print(f"⚠️ فشل إنشاء الملف الأولي: {e}")

        self.open_trades = self.load_from_disk()
        self.last_sync = "بدء التشغيل..."
        self.total_scanned = 0

    def load_from_disk(self):
        with data_lock:
            try:
                if os.path.exists(DB_FILE):
                    with open(DB_FILE, 'r') as f:
                        content = f.read()
                        if not content: return []
                        return json.loads(content)
            except Exception as e:
                print(f"❌ خطأ في القراءة: {e}")
            return []

    def save_to_disk(self):
        """نظام حفظ صارم يضمن الكتابة الفعلية على القرص"""
        with data_lock:
            try:
                # كتابة مؤقتة ثم استبدال لضمان عدم تلف الملف
                temp_path = DB_FILE + ".tmp"
                with open(temp_path, 'w') as f:
                    json.dump(self.open_trades, f, indent=4)
                os.replace(temp_path, DB_FILE)
                print(f"💾 تم الحفظ بنجاح! عدد الصفقات: {len(self.open_trades)}")
            except Exception as e:
                print(f"❌ فشل ذريع في الكتابة: {e}")

state = PersistentState()

# ======================== 2. محرك التحليل الفني ========================

async def get_real_score(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=50)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        close = df['c']
        score = 0
        
        # تحليل بولنجر
        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bandwidth = ((ma20 + (2 * std20)) - (ma20 - (2 * std20))) / ma20
        if bandwidth.iloc[-1] < 0.05: score += 40
            
        # مؤشر RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 45 < rsi.iloc[-1] < 70: score += 20
            
        # قوة الحجم والاتجاه
        if df['v'].iloc[-1] > df['v'].mean() * 1.2: score += 20
        if close.iloc[-1] > close.rolling(20).mean().iloc[-1]: score += 20

        return int(score), close.iloc[-1]
    except:
        return 0, 0

# ======================== 3. المحرك الرئيسي ========================

async def main_engine():
    print("🚀 محرك الصيد V52 انطلق...")
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            
            scanned = 0
            for sym in symbols:
                scanned += 1
                with data_lock: state.total_scanned = scanned
                
                # جلب السكور
                score, price = await get_real_score(sym)
                
                with data_lock:
                    # تحديث أسعار الصفقات الحالية في الذاكرة
                    for tr in state.open_trades:
                        if tr['sym'] in tickers:
                            tr['current_price'] = tickers[tr['sym']]['last']

                    # شرط الكتابة: سكور 70+ وعدم وجودها سابقاً
                    if score >= ENTRY_SCORE:
                        if not any(t['sym'] == sym for t in state.open_trades):
                            if len(state.open_trades) < MAX_OPEN_TRADES:
                                state.open_trades.append({
                                    'sym': sym, 'score': score, 
                                    'entry_price': price, 'current_price': price,
                                    'investment': INVESTMENT,
                                    'time': datetime.now().strftime('%H:%M:%S')
                                })
                                # استدعاء الحفظ الفوري
                                state.save_to_disk()

                await asyncio.sleep(0.01)

            with data_lock: state.last_sync = datetime.now().strftime('%H:%M:%S')
            await asyncio.sleep(60)
        except Exception as e:
            print(f"⚠️ خطأ: {e}")
            await asyncio.sleep(30)

# ======================== 4. واجهة العرض ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        sync = state.last_sync
        count = state.total_scanned
    
    rows = ""
    for t in reversed(active):
        pnl_pct = ((t['current_price'] - t['entry_price']) / t['entry_price']) * 100
        pnl_usd = (pnl_pct / 100) * t['investment']
        color = "#00ff00" if pnl_pct >= 0 else "#ff4444"
        
        rows += f"""<tr style="border-bottom: 1px solid #2b3139;">
            <td style="padding:12px;">{t['time']}</td>
            <td><b style="color:#f0b90b;">{t['sym']}</b></td>
            <td><span style="background:#2b3139; padding:4px 10px; border-radius:4px;">{t['score']}</span></td>
            <td>{t['entry_price']:.4f}</td>
            <td>{t['current_price']:.4f}</td>
            <td style="color:{color}; font-weight:bold;">{pnl_pct:+.2f}% (${pnl_usd:+.2f})</td>
        </tr>"""
    
    return f"""<html><head><meta http-equiv="refresh" content="10"></head>
    <body style="background:#0b0
