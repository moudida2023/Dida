# ... (نفس أجزاء الاستيراد والإعدادات السابقة) ...

@app.route('/')
def index():
    conn = get_db_connection()
    if not conn: return "DB Connection Error", 500
    try:
        cur = conn.cursor(cursor_factory=extras.DictCursor)
        
        # 1. جلب الصفقات المفتوحة
        cur.execute("SELECT * FROM trades ORDER BY open_time DESC")
        active_trades = cur.fetchall()
        
        # 2. جلب آخر 10 صفقات مغلقة
        cur.execute("SELECT * FROM closed_trades ORDER BY close_time DESC LIMIT 10")
        closed_trades = cur.fetchall()
        
        # 3. جلب بيانات المحفظة
        cur.execute("SELECT balance FROM wallet WHERE id = 1")
        res_w = cur.fetchone()
        realized_pnl = float(res_w[0]) if res_w else 0.0
        cur.close(); conn.close()

        invested = len(active_trades) * INVESTMENT_PER_TRADE
        unused = (INITIAL_CAPITAL + realized_pnl) - invested
        floating = sum(((float(t['current_price']) - float(t['entry_price'])) / float(t['entry_price'])) * float(t['investment']) for t in active_trades)
        net_value = INITIAL_CAPITAL + realized_pnl + floating

        return render_template_string("""
        <!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="20">
        <style>
            body { background: #0b0e11; color: white; font-family: sans-serif; text-align: center; padding: 10px; margin: 0; }
            .card { background: #1e2329; padding: 15px; border-radius: 10px; border: 1px solid #f0b90b; margin-bottom: 15px; }
            .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 15px; }
            .s-box { background: #1e2329; padding: 10px; border-radius: 8px; border: 1px solid #2b3139; }
            .up { color: #0ecb81; } .down { color: #f6465d; }
            .section-title { color: #f0b90b; margin-top: 20px; border-bottom: 1px solid #2b3139; padding-bottom: 5px; }
            table { width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 20px; }
            th, td { padding: 8px; border: 1px solid #2b3139; }
            th { background: #2b3139; }
        </style></head><body>
            <div class="card">
                <small>صافي قيمة المحفظة</small><br>
                <b style="font-size:28px;" class="{{ 'up' if net >= 1000 else 'down' }}">${{ "%.2f"|format(net) }}</b>
            </div>
            <div class="stats">
                <div class="s-box">قيد التداول<br><b style="color:#f0b90b;">${{ "%.2f"|format(inv) }}</b></div>
                <div class="s-box">رصيد متاح<br><b style="color:#92a2b1;">${{ "%.2f"|format(un) }}</b></div>
            </div>

            <h4 class="section-title">📍 صفقات مفتوحة ({{ active|length }})</h4>
            <table>
                <tr><th>العملة</th><th>الدخول</th><th>الحالي</th><th>الربح</th></tr>
                {% for t in active %}
                {% set p = ((t.current_price - t.entry_price) / t.entry_price) * 50 %}
                <tr><td>{{ t.symbol }}</td><td>{{ t.entry_price }}</td><td>{{ t.current_price }}</td><td class="{{ 'up' if p >= 0 else 'down' }}">${{ "%.2f"|format(p) }}</td></tr>
                {% endfor %}
            </table>

            <h4 class="section-title">✅ آخر الصفقات المغلقة</h4>
            <table>
                <tr><th>العملة</th><th>الربح ($)</th><th>السبب</th><th>التوقيت</th></tr>
                {% for c in closed %}
                <tr>
                    <td>{{ c.symbol }}</td>
                    <td class="{{ 'up' if c.pnl >= 0 else 'down' }}">{{ "%.2f"|format(c.pnl) }}</td>
                    <td style="font-size:9px;">{{ c.exit_reason }}</td>
                    <td style="color:#848e9c;">{{ c.close_time }}</td>
                </tr>
                {% endfor %}
            </table>
        </body></html>
        """, net=net_value, inv=invested, un=unused, active=active_trades, closed=closed_trades)
    except Exception as e:
        return f"Dashboard Error: {e}", 500

# ... (بقية الكود الخاص بـ trading_engine و keep_alive تبقى كما هي) ...
