import asyncio
import ccxt.pro as ccxt
import pandas as pd
import os
import threading
import json
import time
from flask import Flask, send_file
from datetime import datetime

# ======================== 1. الإعدادات ========================
app = Flask('')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.json")

EXCHANGE = ccxt.binance({'enableRateLimit': True})
MAX_OPEN_TRADES = 20
ENTRY_SCORE = 60 # سكور مرن للتجربة
INVESTMENT = 10.0       

data_lock = threading.Lock()

class PersistentState:
    def __init__(self):
        self.open_trades = self.load_from_disk()
        self.total_scanned = 0
        self.last_sync = "بدء..."
        self.last_disk_save = datetime.now().strftime('%H:%M:%S')

        if not self.open_trades:
            self.open_trades.append({
                "sym": "TEST/USDT", "score": 99, "entry_price": 1.0, 
                "current_price": 1.05, "investment": 10.0, 
                "time": datetime.now().strftime('%H:%M:%S')
            })
            self.save_to_disk()

    def load_from_disk(self):
        try:
            if os.path.exists(DB_FILE):
                with open(DB_FILE, 'r') as f: return json.load(f)
        except: pass
        return []

    def save_to_disk(self):
        with data_lock:
            try:
                with open(DB_FILE, 'w') as f:
                    json.dump(self.open_trades, f, indent=4)
                self.last_disk_save = datetime.now().strftime('%H:%M:%S')
            except: pass

state = PersistentState()

# (دوال التحليل الفني ومحرك البحث تبقى كما هي في v56 لضمان استقرار الصيد)
async def get_score(sym):
    try:
        bars = await EXCHANGE.fetch_ohlcv(sym, timeframe='1h', limit=20)
        df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        score = 0
        if df['c'].iloc[-1] > df['o'].iloc[-1]: score += 30
        if df['v'].iloc[-1] > df['v'].mean(): score += 30
        if df['c'].iloc[-1] > df['c'].iloc[-2]: score += 20
        return score, df['c'].iloc[-1]
    except: return 0, 0

async def main_engine():
    while True:
        try:
            tickers = await EXCHANGE.fetch_tickers()
            symbols = [s for s in tickers.keys() if '/USDT' in s and 'UP/' not in s and 'DOWN/' not in s]
            for sym in symbols:
                with data_lock: state.total_scanned += 1
                score, price = await get_score(sym)
                with data_lock:
                    for tr in state.open_trades:
                        if tr['sym'] in tickers: tr['current_price'] = tickers[tr['sym']]['last']
                    if score >= ENTRY_SCORE and len(state.open_trades) < MAX_OPEN_TRADES:
                        if not any(t['sym'] == sym for t in state.open_trades):
                            state.open_trades.append({
                                'sym': sym, 'score': score, 'entry_price': price, 
                                'current_price': price, 'investment': INVESTMENT,
                                'time': datetime.now().strftime('%H:%M:%S')
                            })
                            state.save_to_disk()
                await asyncio.sleep(0.01)
            with data_lock: state.last_sync = datetime.now().strftime('%H:%M:%S')
            await asyncio.sleep(30)
        except: await asyncio.sleep(10)

# ======================== 2. واجهة العرض مع الرابط المباشر ========================

@app.route('/')
def home():
    with data_lock:
        active = list(state.open_trades)
        sync = state.last_sync
        disk = state.last_disk_save
        count = state.total_scanned
    
    rows = "".join([f"<tr style='border-bottom:1px solid #2b3139;'><td>{t['time']}</td><td><b>{t['sym']}</b></td><td>{t['score']}</td><td>{t['current_price']:.4f}</td><td>{((t['current_price']-t['entry_price'])/t['entry_price']*100):+.2f}%</td></tr>" for t in reversed(active)])

    return f"""<html><head><meta http-equiv="refresh" content="10"></head>
    <body style="background:#0b0e11; color:white; font-family:sans-serif; padding:20px;">
        <div style="max-width:800px; margin:auto; background:#1e2329; padding:20px; border-radius:10px; border-top:5px solid #f0b90b;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h2 style="margin:0;">📊 رادار التداول (v57)</h2>
                <a href="/database" target="_blank" style="background:#f0b90b; color:black; padding:8px 15px; border-radius:5px; text-decoration:none; font-weight:bold; font-size:0.8em;">📂 فتح قاعدة البيانات الخام</a>
            </div>
            <hr style="border:0; border-top:1px solid #2b31
