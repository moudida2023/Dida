import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import os
import threading
from flask import Flask
from datetime import datetime

# ======================== 1. الإعدادات والبيانات ========================
app = Flask('')
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
DESTINATIONS = ['5067771509', '-1003692815602']
EXCHANGE = ccxt.binance({'enableRateLimit': True})

EXCLUDE_LIST = ['TUSD/USDT', 'USDC/USDT', 'FDUSD/USDT', 'USDT/USDT', 'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT']

# متغيرات الحالة العالمية
CURRENT_BALANCE = 500.0
OPEN_TRADES = {}     
SEARCH_HISTORY = [] # الذاكرة التي يعتمد عليها الجدول

# عتبات السكور
TABLE_SCORE = 50  
TRADE_SCORE = 85  

# ======================== 2. لوحة التحكم (الويب) ========================

@app.route('/')
def home():
    # جدول الصفقات المفتوحة
    trades_html = ""
    for s, d in OPEN_TRADES.items():
        pnl = ((d['current'] - d['entry']) / d['entry']) * 100
        color = "#00ff00" if pnl >= 0 else "#ff4444"
        trades_html += f"<tr><td>{s}</td><td>{d['entry']:.6f}</td><td>{d['current']:.6f}</td><td style='color:{color}; font-weight:bold;'>{pnl:+.2f}%</td><td>{d.get('score')}</td></tr>"

    # جدول الرادار - التأكد من القراءة من SEARCH_HISTORY
    history_html = ""
    current_history = list(SEARCH_HISTORY) # نسخة محلية لضمان عدم حدوث خطأ أثناء التحديث
    for item in reversed(current_history[-40:]):
        disc_p = item['price']
        live_p = item.get('live_price', disc_p)
        change = ((live_p - disc_p) / disc_p) * 100
        history_html += f"<tr><td>{item['time']}</td><td><strong>{item['sym']}</strong></td><td>{item['score']}</td><td>{disc_p:.6f}</td><td>{live_p:.6f}</td><td style='color:{'#00ff00' if change>=0 else '#ff4444'}; font-weight:bold;'>{change:+.2f}%</td></tr>"

    return f"""
    <html><head><title>Sniper Elite v15</title><meta http-equiv="refresh" content="30">
    <style>
        body {{ background: #0b0e11; color: #eaecef; font-family: sans-serif; margin: 0; text-align:center; }}
        .header {{ background: #1e2329; padding: 15px; border-bottom: 2px solid #f0b90b; }}
        table {{ width: 95%; margin: 20px auto; border-collapse: collapse; background: #1e2329; }}
        th, td {{ padding: 10px; border: 1px solid #2b3139; text-align: center; }}
        th {{ background: #2b3139; color: #f0b90b; }}
        .status-bar {{ background: #2b3139; padding: 5px; font-size: 0.9em; color: #f0b90b; }}
    </style></head>
    <body>
        <div class="header"><h1>🚀 Sniper Elite Dashboard v15</h1></div>
        <div class="status-bar">
            Memory Data: {len(SEARCH_HISTORY)} items | 
            Active Trades: {len(OPEN_TRADES)} | 
            Balance: {CURRENT_BALANCE:.2f} USDT
        </div>
        <div class="container">
            <h3>💎 الصفقات المفتوحة</h3>
            <table><thead><tr><th>العملة</th><th>الدخول</th><th>الحالي</th><th>الربح %</th><th>السكور</th></tr></thead>
            <tbody>{trades_html if trades_html else "<tr><td colspan='5'>لا توجد صفقات حالياً</td></tr>"}</tbody></table>
            
            <h3>🏆 رادار الفرص (تحديث فوري)</h3>
            <table><thead><tr><th>الوقت</th><th>العملة</th><th>السكور</th><th>سعر الاكتشاف</th><th>السعر الحالي</th><th>الأداء</th></tr></thead>
            <tbody>{history_html if history_html else "<tr><td colspan='6'>بانتظار أول عملة... تأكد من الـ Logs في Render</td></tr>"}</tbody></table>
        </div></body></html>"""

# ======================== 3. المحرك الفني ========================

async def calculate_elite_score(sym):
    try:
        # تبسيط الشروط مؤقتاً لضمان ملء الجدول والاختبار
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=50)
        df = pd.DataFrame(bars, columns=['ts','open','high','low','close','vol'])
        score = 0
        if df['close'].iloc[-1] > df['close'].ewm(span=200).mean().iloc[-1]: score += 30
        if df['vol'].iloc[-1] > df['vol'].rolling(20).mean().iloc[-1]: score += 30
        
        # RSI بسيط
        delta = df['close'].diff(); gain = delta.where(delta > 0, 0).rolling(14).mean(); loss = -delta.where(delta < 0, 0).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain / (loss + 1e-9))))
        if 40 < rsi.iloc[-1] < 75: score += 40
        return score, df['close'].iloc[-1]
    except: return 0, 0

async def sniper_cycle():
    global SEARCH_HISTORY, CURRENT_BALANCE
    while True
