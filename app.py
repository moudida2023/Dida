import asyncio
import ccxt.pro as ccxt
import pandas as pd
import requests
import threading
import time
import os
from flask import Flask

# ======================== 1. الإعدادات ========================
TELEGRAM_TOKEN = '8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68'
TELEGRAM_CHAT_ID = '5067771509'
EXCHANGE = ccxt.binance({'enableRateLimit': True})

VIRTUAL_BALANCE = 1000.0
BASE_TRADE_USD = 100.0
portfolio = {"open_trades": {}}
closed_trades_history = []

# ======================== 2. برمجة الأوامر ========================

def handle_telegram_commands():
    global VIRTUAL_BALANCE
    last_update_id = 0
    print("🤖 نظام التحكم عن بُعد نشط...")
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=30"
            response = requests.get(url, timeout=35).json()
            
            if "result" in response:
                for update in response["result"]:
                    last_update_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"].lower().strip()
                        chat_id = str(update["message"]["chat_id"])
                        
                        if chat_id != TELEGRAM_CHAT_ID: continue

                        # 1. أمر البداية /start
                        if text == "/start":
                            msg = ("🌟 **أهلاً بك في بوت القناص!**\n\n"
                                   "الأوامر المتاحة:\n"
                                   "• `/status` : عرض الرصيد والأرباح\n"
                                   "• `/report` : عرض الصفقات المفتوحة حالياً\n"
                                   "• `/close [العملة]` : إغلاق صفقة معينة\n"
                                   "• `/panic` : إغلاق كل الصفقات فوراً")
                            send_telegram_msg(msg)

                        # 2. أمر الحالة /status
                        elif text == "/status":
                            pnl = sum([t['pnl'] for t in closed_trades_history])
                            msg = (f"📊 **ملخص الحساب:**\n"
                                   f"💰 الرصيد المتاح: `${VIRTUAL_BALANCE:.2f}`\n"
                                   f"📈 صافي الأرباح: `${pnl:.2f}`\n"
                                   f"🔄 الصفقات النشطة: `{len(portfolio['open_trades'])}`")
                            send_telegram_msg(msg)

                        # 3. أمر التقرير /report
                        elif text == "/report":
                            if not portfolio["open_trades"]:
                                send_telegram_msg("📭 لا توجد صفقات مفتوحة حالياً.")
                            else:
                                report = "📑 **قائمة الصفقات النشطة:**\n"
                                for sym, data in portfolio["open_trades"].items():
                                    report += f"• `{sym}`: دخول @ {data['entry_price']:.5f}\n"
                                send_telegram_msg(report)

                        # 4. أمر الطوارئ /panic
                        elif text == "/panic":
                            if not portfolio["open_trades"]:
                                send_telegram_msg("🤷 لا توجد صفقات نشطة لإغلاقها.")
                            else:
                                count = len(portfolio["open_trades"])
                                for sym in list(portfolio["open_trades"].keys()):
                                    trade = portfolio["open_trades"][sym]
                                    VIRTUAL_BALANCE += trade['amount_usd']
                                    portfolio["open_trades"].pop(sym)
                                send_telegram_msg(f"🚨 **PANIC MODE:** تم إغلاق {count} صفقات وإعادة الرصيد للمحفظة.")

                        # 5. أمر إغلاق محدد /close
                        elif text.startswith("/close"):
                            parts = text.split(" ")
                            if len(parts) > 1:
                                sym = parts[1].upper()
                                if not sym.endswith("/USDT"): sym += "/USDT"
                                if sym in portfolio["open_trades"]:
                                    VIRTUAL_BALANCE += portfolio["open_trades"][sym]['amount_usd']
                                    portfolio["open_trades"].pop(sym)
                                    send_telegram_msg(f"✅ تم إغلاق صفقة `{sym}` بنجاح.")
                                else:
                                    send_telegram_msg(f"❌ العملة `{sym}` غير موجودة في المحفظة.")

        except: pass
        time.sleep(1)

# ======================== 3. وظائف التشغيل الأساسية ========================

def send_telegram_msg(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

app = Flask('')
@app.route('/')
def home(): return "Bot is Online"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # تشغيل مستمع الأوامر في خيط منفصل
    threading.Thread(target=handle_telegram_commands, daemon=True).start()
    # تشغيل سيرفر الويب
    app.run(host='0.0.0.0', port=port)
