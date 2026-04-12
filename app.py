import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
from datetime import datetime

# ======================== 1. الإعدادات ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
EXCHANGE = ccxt.binance({'enableRateLimit': True})

# الأطر الزمنية المطلوبة للفحص
TIMEFRAMES = ['15m', '1h', '4h']
# حد الاختناق (كلما قل الرقم كان الاختناق أقوى - 0.05 تعني ضيق شديد)
SQUEEZE_THRESHOLD = 0.05 

# ======================== 2. دالة الإرسال ========================
def send_telegram_msg(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e: print(f"Telegram Error: {e}")

# ======================== 3. تحليل البولنجر ========================
def check_bb_squeeze(df):
    """حساب ما إذا كان هناك اختناق في الإطار الزمني الحالي"""
    # حساب بولنجر (20 شمعة، انحراف معياري 2)
    basis = df['close'].rolling(window=20).mean()
    std = df['close'].rolling(window=20).std()
    upper = basis + (std * 2)
    lower = basis - (std * 2)
    
    # حساب عرض النطاق (Bandwidth)
    bandwidth = (upper - lower) / basis
    current_bandwidth = bandwidth.iloc[-1]
    
    return current_bandwidth <= SQUEEZE_THRESHOLD, current_bandwidth

# ======================== 4. فحص العملة عبر 3 أطر زمنية ========================
async def analyze_coin(symbol):
    score = 0
    results = {}
    
    try:
        for tf in TIMEFRAMES:
            bars = await EXCHANGE.fetch_ohlcv(symbol, timeframe=tf, limit=30)
            df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            
            is_squeezed, width = check_bb_squeeze(df)
            if is_squeezed:
                score += 33.3  # إضافة نقاط لكل إطار زمني به اختناق
            
            results[tf] = round(width, 4)
            
        return score, results
    except:
        return 0, {}

# ======================== 5. المهمة الرئيسية (المسح بـ Batches) ========================
async def scanner_job():
    send_telegram_msg("🔍 *بدء مسح 500 عملة بحثاً عن الاختناق (BB Squeeze)...*")
    
    try:
        # 1. جلب قائمة العملات (أعلى 500 من حيث السيولة)
        tickers = await EXCHANGE.fetch_tickers()
        all_symbols = [s for s in tickers.keys() if '/USDT' in s]
        sorted_symbols = sorted(all_symbols, key=lambda x: tickers[x].get('quoteVolume', 0), reverse=True)[:500]
        
        found_coins = []

        # 2. المسح بنظام المجموعات (100 عملة في المرة)
        for i in range(0, len(sorted_symbols), 100):
            batch = sorted_symbols[i:i+100]
            print(f"Scanning batch {i//100 + 1}...")
            
            tasks = [analyze_coin(sym) for sym in batch]
            results = await asyncio.gather(*tasks)
            
            for idx, (score, details) in enumerate(results):
                if score >= 60:  # إذا وجد اختناق في إطارين على الأقل
                    found_coins.append({
                        "symbol": batch[idx],
                        "score": round(score),
                        "details": details
                    })
            
            await asyncio.sleep(2) # راحة للمنصة لتجنب الحظر

        # 3. صياغة التقرير النهائي
        if found_coins:
            report = "🔥 *العملات المكتشفة (Multi-TF Squeeze):*\n\n"
            # ترتيب حسب الأعلى سكور
            found_coins = sorted(found_coins, key=lambda x: x['score'], reverse=True)
            
            for coin in found_coins[:15]: # إرسال أعلى 15 عملة فقط
                report += f"🎫 *{coin['symbol']}* | Score: {coin['score']}%\n"
                report += f"📊 Width: {coin['details']}\n"
                report += "-------------------\n"
            
            send_telegram_msg(report)
        else:
            send_telegram_msg("✅ المسح انتهى: لم يتم العثور على اختناقات حالياً.")

    except Exception as e:
        print(f"Scanner Error: {e}")

if __name__ == "__main__":
    asyncio.run(scanner_job())
