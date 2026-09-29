import os, io, re, time as _time, threading, hashlib, calendar, requests, json
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
matplotlib.use("Agg")
import mplfinance as mpf
from datetime import datetime, timedelta
from flask import Flask, request
from flask import render_template, jsonify
import sqlite3
import os

DATA_DIR = "/app/data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "mtc_platform.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Сетапы (активные и история)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS setups (
            id TEXT PRIMARY KEY,
            sym TEXT, tf TEXT, dir TEXT, level REAL,
            entry_price REAL, sl REAL, tp REAL, link TEXT,
            status TEXT, created_at REAL, expires_entry REAL,
            vip_chat TEXT, vip_msg TEXT, chart_image TEXT,
            close_result TEXT, pnl_pct REAL, pnl_usd REAL
        )
    ''')
    
    # 2. Глобальная статистика (всегда 1 строка с id=1)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS global_stats (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0, skipped INTEGER DEFAULT 0, expired INTEGER DEFAULT 0,
            pnl REAL DEFAULT 0.0, pnl_usd REAL DEFAULT 0.0,
            deposit REAL DEFAULT 10000.0, balance REAL DEFAULT 10000.0
        )
    ''')
    cursor.execute('INSERT OR IGNORE INTO global_stats (id) VALUES (1)')
    
    # 3. История сделок (с user_id для персональной статистики)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setup_id TEXT, 
            user_id INTEGER,
            date TEXT, sym TEXT, tf TEXT, dir TEXT,
            result TEXT, pnl REAL, pnl_usd REAL
        )
    ''')
    
    # 4. Аналитики
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analyses (
            setup_id TEXT PRIMARY KEY,
            symbol TEXT, tf TEXT, direction TEXT, entry REAL, exit REAL,
            result TEXT, pnl REAL, analysis_text TEXT, chart_image TEXT,
            created_by INTEGER, created_at REAL, views INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS coin_analyses (
            id TEXT PRIMARY KEY,
            symbol TEXT, tf1_link TEXT, tf2_link TEXT, tf3_link TEXT, tf4_link TEXT,
            chart_image TEXT, tf1_screenshot TEXT, tf2_screenshot TEXT, 
            tf3_screenshot TEXT, tf4_screenshot TEXT, tf1_comment TEXT, 
            tf2_comment TEXT, tf3_comment TEXT, tf4_comment TEXT,
            description TEXT, bingx_link TEXT, created_by INTEGER, 
            created_at REAL, updated_at REAL
        )
    ''')
    
    # 5. Активность пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, action TEXT, timestamp REAL
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_activity ON user_activity(user_id, timestamp)')
    
    # 6. Пользовательские сетапы (на модерации)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_setups (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            user_name TEXT,
            sym TEXT, dir TEXT, entry REAL, sl REAL, tp REAL,
            tv_link TEXT, status TEXT, created_at REAL,
            admin_comment TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ База данных SQLite инициализирована.")


TOKEN = "8845319540:AAHsIvOXzVeaKEBNWYWDIHVRPY9QX4YLSmA" 

WEBHOOK_URL = "https://web-production-eadde.up.railway.app/tg_webhook"
app = Flask(__name__)

CHAT = "-1002026400906"
MTC_CHAT = "-1001208487435"
VIP_TOPIC = 2190
LAST = {"text": None, "ts": 0.0}
ADMIN_IDS = []

# --- YOUTUBE НАСТРОЙКИ ---
# ВСТАВЬ СЮДА СВОЙ CHANNEL ID (начинается с UC)
YT_CHANNEL_ID = "UCC71uNPC5AA9wFGvlPL1Iig"
YT_LAST_FILE = "/app/data/yt_last.json"

DATA_DIR = "/app/data"
SETUPS_FILE = DATA_DIR + "/bingx_setups.json"
STATS_FILE = DATA_DIR + "/trading_stats.json"
ANALYSES_FILE = DATA_DIR + "/analyses.json"
COIN_ANALYSIS_FILE = DATA_DIR + "/coin_analyses.json"
USERS_FILE = DATA_DIR + "/users_stats.json"
BX = {"pending": {}, "active": {}, "wait_link": {}, "seq": 1}

def bx_load():
    import os
    try:
        if not os.path.exists(SETUPS_FILE):
            with open(SETUPS_FILE, "w") as f:
                json.dump({"pending": {}, "active": {}, "wait_link": {}, "seq": 1}, f)
            print("✅ Создан bingx_setups.json")
        with open(SETUPS_FILE) as f: 
            data = json.load(f)
            BX["pending"].update(data.get("pending", {}))
            BX["active"].update(data.get("active", {}))
            BX["wait_link"] = data.get("wait_link", {})
            BX["seq"] = data.get("seq", 1)
        print(f"✅ Загружено сетапов: {len(BX['active'])} активных")
    except Exception as e:
        print(f"⚠️ Ошибка загрузки: {e}")

def bx_save():
    try:
        with open(SETUPS_FILE, "w") as f: 
            json.dump(BX, f, indent=2)
    except Exception as e: 
        print("BX SAVE FAIL:", e)

def load_stats():
    import os
    try:
        if not os.path.exists(STATS_FILE):
            with open(STATS_FILE, "w") as f:
                json.dump({
                    "total": 0, "wins": 0, "losses": 0, "skipped": 0, "expired": 0, 
                    "pnl": 0.0, "pnl_usd": 0.0, "deposit": 10000.0, "balance": 10000.0, "history": []
                }, f)
        with open(STATS_FILE, "r") as f: 
            data = json.load(f)
            # Миграция для старых файлов: добавляем поля, если их нет
            if "deposit" not in data: data["deposit"] = 10000.0
            if "balance" not in data: data["balance"] = data.get("deposit", 10000.0)
            if "pnl_usd" not in data: data["pnl_usd"] = 0.0
            return data
    except: 
        return {
            "total": 0, "wins": 0, "losses": 0, "skipped": 0, "expired": 0, 
            "pnl": 0.0, "pnl_usd": 0.0, "deposit": 10000.0, "balance": 10000.0, "history": []
        }

def load_analyses():
    import os
    try:
        if not os.path.exists(ANALYSES_FILE):
            with open(ANALYSES_FILE, "w") as f:
                json.dump({}, f)
        with open(ANALYSES_FILE, "r") as f: return json.load(f)
    except: return {}


def save_stat(setup, result, pnl, user_id=0):
    stats = load_stats()
    stats["total"] += 1
    status_text = {"tp": "TP", "sl": "SL", "skipped_tp": "Пропуск", "expired": "Истек", "admin_cancel": "Отмена", "manual": "Ручное"}.get(result, "Неизвестно")
    if result == "tp": stats["wins"] += 1
    elif result == "sl": stats["losses"] += 1
    elif result == "skipped_tp": stats["skipped"] += 1
    elif result in ["expired", "admin_cancel"]: stats["expired"] += 1
    
    stats["pnl"] = round(stats["pnl"] + pnl, 2)
    pnl_usd = stats["balance"] * (pnl / 100)
    stats["pnl_usd"] = round(stats["pnl_usd"] + pnl_usd, 2)
    stats["balance"] = round(stats["balance"] + pnl_usd, 2)
    
    stats["history"].append({
        "date": datetime.now().strftime("%d.%m.%Y %H:%M"), 
        "sym": setup.get("sym", ""), 
        "tf": setup.get("tf", ""), 
        "dir": setup.get("dir", ""), 
        "result": status_text, 
        "pnl": round(pnl, 2),
        "pnl_usd": round(pnl_usd, 2)
    })
    
    if len(stats["history"]) > 1000:
        stats["history"] = stats["history"][-1000:]
    
    with open(STATS_FILE, "w") as f: 
        json.dump(stats, f, indent=2)
    
    # Запись в SQLite с user_id
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO trade_history (setup_id, user_id, date, sym, tf, dir, result, pnl, pnl_usd)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (setup.get('id', ''), user_id, datetime.now().strftime("%d.%m.%Y %H:%M"), 
          setup.get('sym', ''), setup.get('tf', ''), setup.get('dir', ''), 
          result, round(pnl, 2), round(pnl_usd, 2)))
    conn.commit()
    conn.close()



def save_analysis(setup_id, data):
    analyses = load_analyses()
    analyses[setup_id] = data
    with open(ANALYSES_FILE, "w") as f: json.dump(analyses, f, indent=2)

def get_analysis(setup_id): return load_analyses().get(setup_id)

def delete_analysis(setup_id):
    analyses = load_analyses()
    if setup_id in analyses:
        del analyses[setup_id]
        with open(ANALYSES_FILE, "w") as f: json.dump(analyses, f, indent=2)
        return True
    return False

def get_all_analyses(): return load_analyses()

def load_coin_analyses():
    import os
    try:
        if not os.path.exists(COIN_ANALYSIS_FILE):
            with open(COIN_ANALYSIS_FILE, "w") as f:
                json.dump([], f)
        with open(COIN_ANALYSIS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_coin_analysis(analysis_id, data):
    analyses = load_coin_analyses()
    for i, item in enumerate(analyses):
        if item.get("id") == analysis_id:
            analyses[i] = data
            with open(COIN_ANALYSIS_FILE, "w") as f:
                json.dump(analyses, f, indent=2)
            return True
    analyses.append(data)
    with open(COIN_ANALYSIS_FILE, "w") as f:
        json.dump(analyses, f, indent=2)
    return True
    
def delete_coin_analysis(analysis_id):
    analyses = load_coin_analyses()
    for i, item in enumerate(analyses):
        if item.get("id") == analysis_id:
            analyses.pop(i)
            with open(COIN_ANALYSIS_FILE, "w") as f:
                json.dump(analyses, f, indent=2)
            return True
    return False

def get_coin_analysis(analysis_id):
    analyses = load_coin_analyses()
    for item in analyses:
        if item.get("id") == analysis_id:
            return item
    return None

def fetch_admins_from_group():
    global ADMIN_IDS
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getChatAdministrators", params={"chat_id": CHAT})
        if r.json().get("ok"):
            ADMIN_IDS = [m["user"]["id"] for m in r.json()["result"] if m["status"] in ("creator", "administrator") and not m["user"].get("is_bot")]
            print(f"👑 Загружено админов: {len(ADMIN_IDS)}")
    except Exception as e: print("️ Не подтянул админов:", e)

bx_load()
fetch_admins_from_group()

def is_admin(uid): return uid in ADMIN_IDS

def new_pending(sym, tf, direction, level):
    sid = str(BX["seq"])
    BX["seq"] += 1
    BX["pending"][sid] = {"sym": sym, "tf": tf, "dir": direction, "level": level, "created": _time.time()}
    bx_save()
    return sid

def get_price(sym, source="bingx"):
    if source in ("bingx", "auto"):
        try:
            symbol = f"{sym.upper()}-USDT"
            r = requests.get("https://open-api.bingx.com/openApi/swap/v2/quote/ticker", params={"symbol": symbol}, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data.get('code') == 0 and data.get('data'):
                    return float(data['data']['lastPrice'])
        except Exception as e: print(f"BingX price error: {e}")
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/price", params={"symbol": f"{sym}USDT"}, timeout=5)
        if r.status_code == 200: return float(r.json()["price"])
    except Exception as e: print(f"Binance Futures price error: {e}")
    pair = KRAKEN_PAIR.get(sym)
    if pair:
        try:
            r = requests.get("https://api.kraken.com/0/public/Ticker", params={"pair": pair}, timeout=5)
            if r.status_code == 200: return float(list(r.json()["result"].values())[0]["c"][0])
        except Exception as e: print(f"Kraken price error: {e}")
    return None

KRAKEN_INT = {"D": 1440, "4H": 240, "1H": 60, "15m": 15}
KRAKEN_PAIR = {"BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "XRP": "XRPUSD", "DOGE": "DOGEUSD"}

TF_PROFILE = {
    "15m": {"candle_min": 15, "ttl_candles": 8, "style": "скальпинг", "valid_hours": 8},
    "1H": {"candle_min": 60, "ttl_candles": 8, "style": "интрадей", "valid_hours": 24},
    "4H": {"candle_min": 240, "ttl_candles": 8, "style": "свинг", "valid_hours": 72},
    "D": {"candle_min": 1440, "ttl_candles": 6, "style": "позиция", "valid_hours": 168},
}

def post_setup_to_vip(s, link, sl, tp, entry_price):
    print(f"\n{'='*50}\n📤 ПУБЛИКАЦИЯ СЕТАПА {s['id']} В VIP\n{'='*50}")
    prof = TF_PROFILE.get(s["tf"], TF_PROFILE["4H"])
    valid_hours = prof.get("valid_hours", 24)
    s.update({"sl": sl, "tp": tp, "link": link, "entry_price": entry_price,
              "expires_entry": _time.time() + (valid_hours * 3600), "status": "pending"})
    emo = "" if s["dir"] == "long" else "🔴"
    d_txt = "LONG" if s["dir"] == "long" else "SHORT"
    exp_str = datetime.fromtimestamp(s["expires_entry"]).strftime("%d.%m %H:%M")
    risk = abs(entry_price - sl)
    reward = abs(tp - entry_price)
    rr = reward / risk if risk > 0 else 0
    cap = f"""{emo} *СЕТАП {d_txt}* · {s['sym']}USDT · {s['tf']} · {prof['style']}

🎯 *Вход:* `{entry_price:,.2f}`
🛡 *SL:* `{sl:,.2f}`
 *TP:* `{tp:,.2f}`
 *R:R:* 1:{rr:.1f}

👉 [Перейти на BingX]({link})

⏳ *Актуально до:* {exp_str} МСК
_Если цена не дойдет до входа — сетап будет аннулирован_

⚠️ _Не является финансовой рекомендацией. DYOR._"""
    print(f"📝 Текст готов. Отправляем в {CHAT}, топик {VIP_TOPIC}...")
    try:
        r = send_text_safe({"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "parse_mode": "Markdown"}, cap)
        print(f"✅ Результат: {r}")
        if r.get("ok"):
            s["vip_chat"] = r["result"]["chat"]["id"]
            s["vip_msg"] = r["result"]["message_id"]
            print(f"✅ Сетап опубликован! Message ID: {s['vip_msg']}")
        else:
            print(f"❌ Ошибка: {r}")
            for aid in ADMIN_IDS:
                tg("sendMessage", data={"chat_id": aid, "text": f"❌ Ошибка публикации сетапа {s['id']} в VIP:\n{r}"})
    except Exception as e:
        print(f" КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        for aid in ADMIN_IDS:
            tg("sendMessage", data={"chat_id": aid, "text": f"❌ Критическая ошибка при публикации сетапа {s['id']}:\n{str(e)}"})
    BX["active"][s["id"]] = s
    bx_save()
    print(f"✅ Сетап {s['id']} сохранен в active\n{'='*50}\n")

    # --- СОХРАНЯЕМ В ЛЕНТУ МИНИ-АППА ---
    feed_file = DATA_DIR + "/miniapp_feed.json"
    try:
        if os.path.exists(feed_file):
            with open(feed_file, "r") as f: feed = json.load(f)
        else: feed = []
        
        feed.insert(0, {
            "id": s["id"],
            "sym": s["sym"],
            "dir": s["dir"],
            "entry": s["entry_price"],
            "sl": s["sl"],
            "tp": s["tp"],
            "chart": s.get("chart_image", ""),
            "time": _time.time()
        })
        
        with open(feed_file, "w") as f: json.dump(feed[:30], f, indent=2)
    except Exception as e: 
        print("⚠️ Ошибка сохранения в ленту:", e)

def close_setup(sid, result):
    s = BX["active"].pop(sid, None)
    if not s: return
    s["status"] = "closed"
    s["close_result"] = result
    head = {"tp": "🎯 TP ВЗЯТ", "sl": "🛑 SL СРАБОТАЛ", "exp": "⏳ ИСТЕК", "admin_cancel": "❌ ОТМЕНЕНО"}.get(result, "ЗАКРЫТ")
    entry = s.get("entry_price", 0)
    exit_price = s["tp"] if result == "tp" else s["sl"]
    pnl_pct = ((exit_price - entry) / entry * 100) if s["dir"] == "long" else ((entry - exit_price) / entry * 100)
    pnl_sign = "+" if pnl_pct > 0 else ""
    
    try:
        try:
            stats = get_stats_for_api()
            winrate = stats.get('winrate', 0.0)
        except:
            winrate = 0.0
        
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT balance FROM global_stats WHERE id = 1')
            row = cursor.fetchone()
            balance = row['balance'] if row else 10000.0
            conn.close()
            pnl_usd_val = round(balance * (pnl_pct / 100), 2)
        except:
            pnl_usd_val = 0.0
        
        img_buf = make_pnl_card(s['sym'], s['dir'], result, pnl_pct, pnl_usd_val, winrate)
        
        cap = f"""{head} · {s['sym']}USDT · {s['tf']}
⏱ В работе: {(_time.time() - s.get('entry_time', s['created'])) / 3600:.1f} ч
📊 Результат: {pnl_sign}{pnl_pct:.2f}% (${pnl_usd_val:+,.2f})

📲 _Сохрани и поделись этим результатом!_"""
        
        if s.get("vip_msg"):
            try: 
                tg("editMessageCaption", data={
                    "chat_id": s["vip_chat"], 
                    "message_id": s["vip_msg"], 
                    "caption": f"{head} · {s['sym']}USDT\nРезультат: {pnl_sign}{pnl_pct:.2f}%", 
                    "parse_mode": "Markdown"
                })
            except: pass
        
        tg("sendPhoto", data={
            "chat_id": CHAT, 
            "message_thread_id": VIP_TOPIC, 
            "caption": cap, 
            "parse_mode": "Markdown"
        }, files={"photo": ("pnl_card.png", img_buf, "image/png")})
        
    except Exception as e:
        print(f"⚠️ Ошибка генерации PnL картинки: {e}")
        cap = f"""{head} · {s['sym']}USDT · {s['tf']}
⏱ В работе: {(_time.time() - s.get('entry_time', s['created'])) / 3600:.1f} ч
📊 Результат: {pnl_sign}{pnl_pct:.2f}%
🛡 SL: {s['sl']:,.2f} | 💰 TP: {s['tp']:,.2f}"""
        tg("sendMessage", data={"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "text": f"📊 {cap}", "parse_mode": "Markdown"})

    for aid in ADMIN_IDS:
        tg("sendMessage", data={"chat_id": aid, "text": f"⚙️ Сетап {sid} закрыт: {head}\nРезультат: {pnl_sign}{pnl_pct:.2f}%"})
    
    save_stat(s, result, pnl_pct, s.get('author_id', 0))
    bx_save()


def bx_watch_step():
    now = _time.time()
    
    # ==========================================
    # 1. ПРОВЕРКА АДМИНСКИХ СЕТАПОВ
    # ==========================================
    for sid in list(BX["active"].keys()):
        s = BX["active"][sid]
        try:
            klines = requests.get("https://api.binance.com/api/v3/klines", params={"symbol": f"{s['sym']}USDT", "interval": "1m", "limit": 3}, timeout=5).json()
            if not isinstance(klines, list) or len(klines) < 1:
                continue
                
            candles = [{'high': float(k[2]), 'low': float(k[3]), 'close': float(k[4]), 'time': k[0]} for k in klines]
            last_candle = candles[-2] if len(candles) >= 2 else candles[-1]
            price = last_candle['close']
            buf_frac = 0.0005
            
            if s.get("status") == "pending":
                entry = s["entry_price"]
                reached = False
                skipped_tp = False
                
                if s["dir"] == "long":
                    if price >= entry * (1 - buf_frac): reached = True
                    if not reached and price >= s["tp"] * (1 - buf_frac): skipped_tp = True
                else:
                    if price <= entry * (1 + buf_frac): reached = True
                    if not reached and price <= s["tp"] * (1 + buf_frac): skipped_tp = True
                
                if skipped_tp:
                    BX["active"].pop(sid, None)
                    save_stat(s, "skipped_tp", 0.0)
                    bx_save()
                    continue
                    
                if now > s.get("expires_entry", 0):
                    if not s.get("asked_extend"):
                        s["asked_extend"] = True
                        bx_save()
                        kb = {"inline_keyboard": [[{"text": "✅ Продлить (24ч)", "callback_data": f"conf:{sid}"}, {"text": "❌ Закрыть", "callback_data": f"cncl:{sid}"}]]}
                        for aid in ADMIN_IDS:
                            tg("sendMessage", data={"chat_id": aid, "text": f"⏳ *СЕТАП ТРЕБУЕТ РЕШЕНИЯ* · {s['sym']}USDT\n🎯 Вход: `{s['entry_price']:,.2f}`\n📍 Цена: `{price:,.2f}`", "parse_mode": "Markdown", "reply_markup": kb})
                    continue
                    
                if reached:
                    s["status"] = "active"
                    s["entry_time"] = now
                    s["entry_price"] = price 
                    bx_save()
                    try: 
                        tg("sendMessage", data={"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "text": f"✅ *СЕТАП АКТИВИРОВАН* · {s['sym']}USDT\n🎯 Вход пройден! Цена: `{price:,.2f}`", "parse_mode": "Markdown", "reply_to_message_id": s.get("vip_msg")})
                    except: pass
                    
            elif s.get("status") == "active":
                result = None
                if s["dir"] == "long":
                    if price >= s["tp"] * (1 - buf_frac): result = "tp"
                    elif price <= s["sl"] * (1 + buf_frac): result = "sl"
                else:
                    if price <= s["tp"] * (1 + buf_frac): result = "tp"
                    elif price >= s["sl"] * (1 - buf_frac): result = "sl"
                
                if result:
                    print(f"🎯 #{sid}: {result.upper()} @ {price:,.2f}")
                    close_setup(sid, result)
        except Exception as e:
            print(f"⚠️ Ошибка проверки {s.get('sym')}: {e}")
            continue

    # ==========================================
    # 2. ПРОВЕРКА ПОЛЬЗОВАТЕЛЬСКИХ СЕТАПОВ (ОДОБРЕННЫХ)
    # ==========================================
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, user_name, sym, dir, entry, sl, tp, status, created_at FROM user_setups WHERE status IN ('approved', 'active')")
        user_setups = cursor.fetchall()
        conn.close()

        for us in user_setups:
            setup_id = us['id']
            user_id = us['user_id']
            user_name = us['user_name']
            sym = us['sym']
            direction = us['dir']
            entry = float(us['entry'])
            sl = float(us['sl'])
            tp = float(us['tp'])
            status = us['status']
            created_at = float(us['created_at'])

            try:
                klines = requests.get("https://api.binance.com/api/v3/klines", params={"symbol": f"{sym}USDT", "interval": "1m", "limit": 2}, timeout=5).json()
                if not isinstance(klines, list) or len(klines) < 1:
                    continue
                price = float(klines[-1][4]) 

                # Правило 4: Напоминание через 24 часа
                if status == 'approved' and (now - created_at) > 86400:
                    conn = get_db(); cursor = conn.cursor()
                    cursor.execute("UPDATE user_setups SET status = 'expired' WHERE id = ?", (setup_id,))
                    conn.commit(); conn.close()
                    msg = f"⏰ *Сетап истек!* · {sym} {direction.upper()}\n\nПрошли 24 часа, а цена так и не дошла до входа ({entry}).\nСетап автоматически закрыт."
                    tg("sendMessage", data={"chat_id": user_id, "text": msg, "parse_mode": "Markdown"})
                    continue

                # Правило 5: Цена достигла ТП до входа
                if status == 'approved':
                    missed = False
                    if direction == 'long' and price >= tp: missed = True
                    elif direction == 'short' and price <= tp: missed = True

                    if missed:
                        conn = get_db(); cursor = conn.cursor()
                        cursor.execute("UPDATE user_setups SET status = 'missed' WHERE id = ?", (setup_id,))
                        conn.commit(); conn.close()
                        msg = f"🚀 *Сетап упущен!* · {sym} {direction.upper()}\n\nЦена достигла TP ({tp}), так и не задев вход ({entry})."
                        tg("sendMessage", data={"chat_id": user_id, "text": msg, "parse_mode": "Markdown"})
                        tg("sendMessage", data={"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "text": f"🚀 *УПУЩЕННЫЙ СЕТАП* · {sym} {direction.upper()}\n👤 Трейдер: {user_name}\nЦена ушла в ТП ({tp}) без входа ({entry}).", "parse_mode": "Markdown"})
                        continue

                    # Правило 1: Ждем точку входа СТРОГО
                    entry_hit = False
                    if direction == 'long' and price <= entry: entry_hit = True
                    elif direction == 'short' and price >= entry: entry_hit = True

                    if entry_hit:
                        conn = get_db(); cursor = conn.cursor()
                        cursor.execute("UPDATE user_setups SET status = 'active' WHERE id = ?", (setup_id,))
                        conn.commit(); conn.close()
                        msg = f"✅ *Сетап АКТИВИРОВАН!* · {sym} {direction.upper()}\n\nЦена вошла в позицию: {price}\n🛡 SL: {sl} | 💰 TP: {tp}"
                        tg("sendMessage", data={"chat_id": user_id, "text": msg, "parse_mode": "Markdown"})
                        continue

                # Правило 2 и 3: Следим за SL/TP
                elif status == 'active':
                    result = None
                    if direction == 'long':
                        if price >= tp: result = 'closed_tp'
                        elif price <= sl: result = 'closed_sl'
                    else:
                        if price <= tp: result = 'closed_tp'
                        elif price >= sl: result = 'closed_sl'

                    if result:
                        conn = get_db(); cursor = conn.cursor()
                        cursor.execute("UPDATE user_setups SET status = ? WHERE id = ?", (result, setup_id))
                        conn.commit(); conn.close()

                        pnl_pct = ((tp - entry) / entry * 100) if direction == 'long' else ((entry - tp) / entry * 100)
                        sign = "+" if result == 'closed_tp' else ""
                        res_text = "🎯 TAKE PROFIT" if result == 'closed_tp' else "🛑 STOP LOSS"
                        exit_price = tp if result == 'closed_tp' else sl

                        public_msg = f"""{res_text} · {sym} {direction.upper()}
👤 Трейдер: {user_name}
📊 Результат: {sign}{pnl_pct:.2f}%
🎯 Вход: {entry} | 🚪 Выход: {exit_price}"""
                        tg("sendMessage", data={"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "text": public_msg, "parse_mode": "Markdown"})
                        
                        private_msg = f"""{res_text} · {sym} {direction.upper()}
📊 Ваш результат: {sign}{pnl_pct:.2f}%
🎯 Вход: {entry} | 🚪 Выход: {exit_price}
Спасибо, что делитесь сетапами в My Trading Club! 🐾"""
                        tg("sendMessage", data={"chat_id": user_id, "text": private_msg, "parse_mode": "Markdown"})

            except Exception as e:
                print(f"⚠️ Ошибка проверки сетапа {setup_id} ({sym}): {e}")
                continue
    except Exception as e:
        print(f"⚠️ Ошибка цикла пользовательских сетапов: {e}")



def bx_watch_loop():
    while True:
        try: bx_watch_step()
        except Exception as e: print("WATCH LOOP:", e)
        _time.sleep(60)

# --- YOUTUBE AUTOPOSTER ---
def get_last_yt_video():
    try:
        if os.path.exists(YT_LAST_FILE):
            with open(YT_LAST_FILE, "r") as f: return json.load(f).get("last_id", "")
    except: pass
    return ""

def save_last_yt_video(vid):
    try:
        with open(YT_LAST_FILE, "w") as f: json.dump({"last_id": vid}, f)
    except Exception as e: print("YT SAVE FAIL:", e)

def check_youtube_feed():
    if YT_CHANNEL_ID == "UCC71uNPC5AA9wFGvlPL1Iig" or not YT_CHANNEL_ID.startswith("UC"):
        return # Не запускаем, если ID не вставлен
    try:
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={YT_CHANNEL_ID}"
        r = requests.get(rss_url, timeout=10)
        if r.status_code == 200:
            xml_text = r.text
            vid_match = re.search(r'<yt:videoId>(.*?)</yt:videoId>', xml_text)
            # Гибкая регулярка: ловит и с CDATA, и без
            title_match = re.search(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', xml_text)
            link_match = re.search(r'<link rel="alternate" href="(.*?)"/>', xml_text)
            
            if vid_match and title_match and link_match:
                new_vid = vid_match.group(1)
                title = title_match.group(1)
                link = link_match.group(1)
                
                last_vid = get_last_yt_video()
                if not last_vid:
                    save_last_yt_video(new_vid) # Первый запуск, просто запоминаем
                    return
                
                if new_vid != last_vid:
                    save_last_yt_video(new_vid)
                    msg = f"""🎥 *НОВОЕ ВИДЕО НА КАНАЛЕ!*

📌 *{title}*

👉 [Смотреть на YouTube]({link})

@MyTradingClub"""
                    tg("sendMessage", data={"chat_id": CHAT, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": False})
                    print(f"✅ YouTube видео отправлено: {new_vid}")
    except Exception as e:
        print(f"⚠️ YouTube check error: {e}")

def yt_watch_loop():
    while True:
        try:
            check_youtube_feed()
        except Exception as e:
            print("YT WATCH LOOP:", e)
        _time.sleep(900) # Проверка каждые 15 минут

def get_daily_data(coin_id):
    try:
        r = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true", timeout=5)
        if r.status_code == 200:
            data = r.json().get(coin_id, {})
            return data.get('usd', 0), data.get('usd_24h_change', 0)
    except:
        pass
    return 0, 0

def send_vip_quote(msg):
    keyboard = {
        "inline_keyboard": [
            [{"text": "📊 Fear & Greed Index", "callback_data": "fear_greed"}]
        ]
    }
    
    tg("sendMessage", data={
        "chat_id": "-1002026400906",
        "message_thread_id": VIP_TOPIC,
        "text": msg,
        "parse_mode": "Markdown",
        "reply_markup": keyboard
    })
    
    tg("sendMessage", data={
        "chat_id": "-1001208487435",
        "text": msg,
        "parse_mode": "Markdown",
        "reply_markup": keyboard
    })


def load_users_stats():
    import os
    try:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, "w") as f:
                json.dump({"all_users": [], "daily": {}, "weekly": {}, "monthly": {}, "button_clicks": {}}, f)
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return {"all_users": [], "daily": {}, "weekly": {}, "monthly": {}, "button_clicks": {}}

def save_users_stats(data):
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"⚠️ Ошибка сохранения users_stats: {e}")

def track_user(uid, action="message"):
    """Отслеживает уникального пользователя и его действия"""
    stats = load_users_stats()
    
    # Добавляем в общий список (если еще нет)
    if uid not in stats["all_users"]:
        stats["all_users"].append(uid)
        print(f"✅ Новый пользователь: {uid}")
    
    # Считаем по периодам
    today = datetime.now().strftime("%Y-%m-%d")
    week = datetime.now().strftime("%Y-W%U")
    month = datetime.now().strftime("%Y-%m")
    
    if today not in stats["daily"]:
        stats["daily"][today] = []
    if uid not in stats["daily"][today]:
        stats["daily"][today].append(uid)
    
    if week not in stats["weekly"]:
        stats["weekly"][week] = []
    if uid not in stats["weekly"][week]:
        stats["weekly"][week].append(uid)
    
    if month not in stats["monthly"]:
        stats["monthly"][month] = []
    if uid not in stats["monthly"][month]:
        stats["monthly"][month].append(uid)
    
    # Считаем клики по кнопкам
    if action not in stats["button_clicks"]:
        stats["button_clicks"][action] = 0
    stats["button_clicks"][action] += 1
    
    save_users_stats(stats)
    return stats

def get_users_report():
    """Возвращает отчет по пользователям"""
    stats = load_users_stats()
    total = len(stats["all_users"])
    
    today = datetime.now().strftime("%Y-%m-%d")
    week = datetime.now().strftime("%Y-W%U")
    month = datetime.now().strftime("%Y-%m")
    
    daily_active = len(stats["daily"].get(today, []))
    weekly_active = len(stats["weekly"].get(week, []))
    monthly_active = len(stats["monthly"].get(month, []))
    
    return {
        "total": total,
        "daily": daily_active,
        "weekly": weekly_active,
        "monthly": monthly_active,
        "buttons": stats["button_clicks"]
    }


import re
from urllib.parse import urlparse


def get_user_trust_level(user_id):
    """Определяет уровень доверия пользователя на основе ЕГО истории"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Считаем успешные сделки КОНКРЕТНОГО пользователя
    cursor.execute("SELECT COUNT(*) FROM trade_history WHERE user_id = ? AND result = 'TP'", (user_id,))
    wins = cursor.fetchone()[0]
    
    # Считаем общее количество сделок пользователя
    cursor.execute("SELECT COUNT(*) FROM trade_history WHERE user_id = ? AND result IN ('TP', 'SL', 'manual')", (user_id,))
    total_trades = cursor.fetchone()[0]
    
    conn.close()
    
    winrate = (wins / total_trades * 100) if total_trades > 0 else 0
    
    # Логика уровней (MVP)
    if wins >= 10 and winrate >= 60:
        return {"level": 2, "name": "Alpha", "badge": "🥇", "color": "#ffd700", "can_use_stars": True}
    elif wins >= 3:
        return {"level": 1, "name": "Трейдер", "badge": "", "color": "#c0c0c0", "can_use_stars": False}
    else:
        return {"level": 0, "name": "Новичок", "badge": "", "color": "#cd7f32", "can_use_stars": False}

def validate_setup_links(text):
    """
    Жесткая проверка ссылок. 
    Разрешены ТОЛЬКО ссылки на TradingView.
    """
    if not text:
        return True, "OK"
    
    # 1. Нормализация текста (убираем невидимые символы и попытки обхода)
    # Zero-width spaces, которые используют для склеивания ссылок
    text = text.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '').replace('\ufeff', '')
    # Исправление замененных букв (hxxp -> http)
    text = text.replace('hxxp', 'http').replace('hXXp', 'http').replace('hтtp', 'http')
    
    # 2. Ищем все URL в тексте
    urls = re.findall(r'https?://\S+', text)
    
    if not urls:
        return True, "OK" # Если ссылок нет вообще — пропускаем
        
    # 3. Проверяем каждую ссылку
    for url in urls:
        try:
            # Очищаем URL от знаков препинания в конце (.,;:!?)
            url = url.rstrip('.,;:!?')
            parsed = urlparse(url)
            domain = parsed.netloc.lower().replace('www.', '')
            
            #  ЖЕСТКОЕ ПРАВИЛО: только TradingView
            if domain != 'tradingview.com':
                return False, f"Разрешены только ссылки на TradingView! Обнаружен запрещенный домен: {domain}"
                
        except Exception:
            return False, "Некорректный формат ссылки"
            
    return True, "OK"

def handle_update(up):
    # 🔥 СУПЕР-ОТЛАДКА
    print("="*60)
    print(f"📥 ПОЛУЧЕНО ОБНОВЛЕНИЕ")
    print("="*60)

    cb = up.get("callback_query")
    if cb:
        uid = cb["from"]["id"]
        data = cb.get("data", "")
        
        print(f"🔘 НАЖАТА КНОПКА!")
        print(f"   👤 User ID: {uid}")
        print(f"    Data: '{data}'")
        print(f"   👑 Текущие ADMIN_IDS: {ADMIN_IDS}")
        print(f"   🛡️ is_admin({uid}) = {uid in ADMIN_IDS}")

        try:
            track_user(uid, action=f"button:{data}")
        except Exception as e:
            print(f"⚠️ Ошибка в track_user: {e}")

        if not is_admin(uid):
            print(f" ОТКАЗ: Пользователь {uid} не является админом!")
            tg("answerCallbackQuery", data={"callback_query_id": cb["id"], "text": "Не твои кнопки 😼"})
            return

        print(f"✅ ДОСТУП РАЗРЕШЕН! Обработка data='{data}'...")
        tg("answerCallbackQuery", data={"callback_query_id": cb["id"], "text": "ok"})
        
        if data.startswith("bx:"):
            BX["wait_link"][str(uid)] = data[3:]
            bx_save()
            tg("sendMessage", data={"chat_id": uid, "text": "🔗 Вставь ссылку BingX, а следующей строкой ВХОД, SL и TP:\nhttps://...\n79000 78000 81000"})
        elif data.startswith("skip:"):
            BX["pending"].pop(data[5:], None)
            bx_save()
            tg("sendMessage", data={"chat_id": uid, "text": "❌ Пропущено."})
        elif data.startswith("conf:"):
            sid = data[5:]
            s = BX["active"].get(sid)
            if s:
                s["expires_entry"] = _time.time() + (24 * 3600)
                s["asked_extend"] = False
                bx_save()
                tg("sendMessage", data={"chat_id": uid, "text": f"✅ Сетап #{sid} продлён на 24 часа"})
        elif data.startswith("cncl:"):
            sid = data[5:]
            s = BX["active"].pop(sid, None)
            if s:
                s["status"] = "closed"
                s["close_result"] = "admin_cancel"
                save_stat(s, "expired", 0.0)
                bx_save()
                cap = f"""🚫 *ОТМЕНЕНО АДМИНОМ* · {s['sym']}USDT · {s['tf']}
_Сетап признан неактуальным._"""
                if s.get("vip_msg"):
                    try: tg("editMessageCaption", data={"chat_id": s["vip_chat"], "message_id": s["vip_msg"], "caption": cap, "parse_mode": "Markdown"})
                    except: pass
                tg("sendMessage", data={"chat_id": uid, "text": f"🚫 Сетап #{sid} закрыт админом"})

        elif data.startswith("approve_setup:"):
            setup_id = data[14:]
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_setups WHERE id = ?", (setup_id,))
            row = cursor.fetchone()
            if row:
                # Обновляем статус
                cursor.execute("UPDATE user_setups SET status = 'approved' WHERE id = ?", (setup_id,))
                conn.commit()
                
                # Формируем сообщение для канала (можно доработать до постинга в VIP)
                dir_emoji = "🟢" if row['dir'] == "long" else "🔴"
                cap = f"""{dir_emoji} *СЕТАП ОТ АВТОРА* · {row['sym']}USDT

👤 Трейдер: {row['user_name']}
🎯 Вход: `{row['entry']}`
🛡 SL: `{row['sl']}` | 💰 TP: `{row['tp']}`
🔗 График: {row['tv_link']}

_Сетап прошел модерацию и добавлен в ленту!_"""
                
                # Отправляем в канал (опционально, или просто обновляем статус для Mini App)
                tg("sendMessage", data={"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "text": cap, "parse_mode": "Markdown"})
                
                tg("editMessageText", data={
                    "chat_id": cb["message"]["chat"]["id"],
                    "message_id": cb["message"]["message_id"],
                    "text": f"✅ Сетап {setup_id} ОДОБРЕН и опубликован!"
                })
            conn.close()
            
        elif data.startswith("reject_setup:"):
            setup_id = data[13:]
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE user_setups SET status = 'rejected' WHERE id = ?", (setup_id,))
            conn.commit()
            conn.close()
            
            tg("editMessageText", data={
                "chat_id": cb["message"]["chat"]["id"],
                "message_id": cb["message"]["message_id"],
                "text": f"❌ Сетап {setup_id} ОТКЛОНЕН."
            })
            # Тут можно добавить отправку уведомления пользователю о причине отказа
        
        elif data == "fear_greed":
            print("   🔄 Запускаем fear_greed...")
            try:
                r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
                if r.status_code == 200:
                    data_fg = r.json().get('data', [])
                    if data_fg:
                        value = int(data_fg[0]['value'])
                        label = data_fg[0]['value_classification']
                        timestamp = int(data_fg[0]['timestamp'])
                        date_str = datetime.fromtimestamp(timestamp).strftime('%d.%m.%Y')
                        gauge_buf = make_fear_greed_gauge(value, label)
                        caption = f"""📊 **Индекс Страха и Жадности**

Значение: **{value}** ({label})
Дата: {date_str}

📉 **0-25:** Extreme Fear
🟠 **26-45:** Fear
⚖️ **46-55:** Neutral
📈 **56-75:** Greed
🔥 **76-100:** Extreme Greed

_Индекс показывает настроение рынка_"""
                        chat_id = cb.get("message", {}).get("chat", {}).get("id")
                        if not chat_id:
                            chat_id = uid
                        send_data = {
                            "chat_id": chat_id,
                            "caption": caption,
                            "parse_mode": "Markdown"
                        }
                        message_thread_id = cb.get("message", {}).get("message_thread_id")
                        if message_thread_id:
                            send_data["message_thread_id"] = message_thread_id
                        
                        print(f"   📤 Отправляем фото...")
                        res = tg("sendPhoto", data=send_data, files={"photo": ("fear_greed.png", gauge_buf, "image/png")})
                        print(f"   📬 Ответ: {res}")
            except Exception as e:
                print(f"❌ ОШИБКА в fear_greed: {e}")
                import traceback
                traceback.print_exc()
                tg("sendMessage", data={"chat_id": uid, "text": f"⚠️ Ошибка: {e}"})
        elif data == "gen_vip_post":
            print("   🔄 Запускаем gen_vip_post...")
            stats = load_stats()
            total = stats.get("total", 0)
            wins = stats.get("wins", 0)
            losses = stats.get("losses", 0)
            winrate = round((wins / total) * 100, 1) if total > 0 else 0
            vip_post = f"""📊 *MTC Trading Platform*

 *Статистика:*
• Сделок: {total}
• Винрейт: {winrate}%
• TP: {wins} | SL: {losses}

🎯 *Стратегия:* CHoCH + FVG
 *ТФ:* 4H → 15m, 1H → 5m

 Жми кнопку ниже, чтобы открыть дашборд!"""
            kb = {"inline_keyboard": [[{"text": "🚀 Открыть Дашборд", "web_app": {"url": "https://web-production-eadde.up.railway.app/dashboard"}}]]}
            tg("sendMessage", data={"chat_id": uid, "text": vip_post, "parse_mode": "Markdown", "reply_markup": kb})
            tg("sendMessage", data={"chat_id": uid, "text": "ℹ️ *Это сообщение можно переслать в VIP-канал!*\n\nПросто зажми сообщение и выбери 'Переслать'.", "parse_mode": "Markdown"})
        return

    # ========== ОБРАБОТКА СООБЩЕНИЙ ==========
    msg = up.get("message")
    if msg:
        uid = msg["from"]["id"]
        txt = msg.get("text", "")
        track_user(uid, action="message")
        chat_type = msg.get("chat", {}).get("type")
        is_private = chat_type == "private"
        is_group_chat = chat_type in ("supergroup", "group") and is_admin(uid)

        if is_private or is_group_chat:
            if txt.strip().startswith("/start"):
                # 1. Проверяем наличие Deep Link аргумента
                parts = txt.strip().split(" ")
                deep_link_arg = parts[1] if len(parts) > 1 else None
                
                if deep_link_arg and deep_link_arg.startswith("setup_"):
                    setup_id = deep_link_arg.replace("setup_", "")
                    s = BX["active"].get(setup_id) or BX["pending"].get(setup_id)
                    
                    if s:
                        emo = "🟢" if s["dir"] == "long" else "🔴"
                        kb = {"inline_keyboard": [[
                            {"text": "🚀 Открыть Дашборд и повторить", "web_app": {"url": "https://web-production-eadde.up.railway.app/dashboard"}}
                        ]]}
                        viral_text = f"""🔥 *Трейдер открыл сетап:*
{emo} **{s['sym']} USDT** · {s['dir'].upper()}
Таймфрейм: {s['tf']}

Хочешь получать такие сигналы первым и отслеживать рынок? 
Жми кнопку ниже, чтобы начать! 👇"""
                        tg("sendMessage", data={"chat_id": uid, "text": viral_text, "parse_mode": "Markdown", "reply_markup": kb})
                        return
                
                # 2. Стандартный /start
                kb = {"inline_keyboard": [
                    [{"text": "🚀 Открыть Дашборд", "web_app": {"url": "https://web-production-eadde.up.railway.app/dashboard"}}],
                    [{"text": "📝 Сгенерировать пост для VIP", "callback_data": "gen_vip_post"}],
                    [{"text": "📊 Fear & Greed Index", "callback_data": "fear_greed"}]
                ]}
                
                if is_admin(uid):
                    welcome_text = """*Привет, Админ!*

Добро пожаловать в *MTC Trading Platform*!

🎯 *Возможности платформы:*
• Сигналы CHoCH + FVG в реальном времени
• Автоматический анализ рынка
• Статистика и аналитика сделок

*Используй кнопки ниже:*
• "Открыть Дашборд" — твой личный кабинет
• "Сгенерировать пост для VIP" — создай красивый пост
• "Fear & Greed Index" — индекс страха и жадности

_Платформа в разработке. Следим за прогрессом!_"""
                else:
                    welcome_text = """*Привет!*

Добро пожаловать в *MTC Trading Platform*!

Здесь ты найдёшь:
• Актуальную статистику сделок
• Разборы сигналов
• Аналитику рынка

Жми кнопку ниже, чтобы открыть дашборд!"""
                
                tg("sendMessage", data={"chat_id": uid, "text": welcome_text, "parse_mode": "Markdown", "reply_markup": kb})
                return

            if txt.strip() == "/stats" and is_admin(uid):
                stats = load_stats()
                if stats["total"] == 0:
                    tg("sendMessage", data={"chat_id": uid, "text": "📊 Статистика пока пуста."})
                    return
                win_rate = (stats["wins"] / stats["total"]) * 100 if stats["total"] > 0 else 0
                last_5 = stats["history"][-5:]
                history_text = "\n".join([f"• {h['date']} | {h['sym']} {h['tf']} {h['dir'].upper()} → **{h['result']}** ({h['pnl']}%)" for h in last_5])
                report = f"""📊 *ОТЧЕТ MY TRADING CLUB*

 *Всего:* {stats['total']}
🟢 *TP:* {stats['wins']} ({win_rate:.1f}%)
🔴 *SL:* {stats['losses']}
 *Пропуск:* {stats['skipped']}
⏳ *Истекло:* {stats['expired']}
 *Общий PnL:* {stats.get('pnl', 0)}%

📜 *Последние 5:*
{history_text}"""
                tg("sendMessage", data={"chat_id": uid, "text": report, "parse_mode": "Markdown"})
                return

            if txt.strip() == "/active" and is_admin(uid):
                active = BX.get("active", {})
                if not active:
                    tg("sendMessage", data={"chat_id": uid, "text": "📭 Нет активных сетапов"})
                else:
                    lines = []
                    for sid, s in active.items():
                        lines.append(f"🔹 *#{sid}* · {s['sym']} {s['tf']} {s['dir'].upper()}")
                        lines.append(f"   Вход: `{s['entry_price']:,.2f}` | SL: `{s['sl']:,.2f}` | TP: `{s['tp']:,.2f}`")
                        lines.append(f"   Статус: `{s.get('status', '?')}`\n")
                    msg_text = "📋 *АКТИВНЫЕ СЕТАПЫ:*\n\n" + "\n".join(lines)
                    tg("sendMessage", data={"chat_id": uid, "text": msg_text, "parse_mode": "Markdown"})
                return

            if txt.strip() == "/quotes" and is_admin(uid):
                btc_p, btc_c = get_daily_data("bitcoin")
                eth_p, eth_c = get_daily_data("ethereum")
                sol_p, sol_c = get_daily_data("solana")
                bnb_p, bnb_c = get_daily_data("binancecoin")
                xrp_p, xrp_c = get_daily_data("ripple")
                doge_p, doge_c = get_daily_data("dogecoin")
                ada_p, ada_c = get_daily_data("cardano")
                gold_p, gold_c = get_daily_data("gold")
                
                try:
                    rates = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5).json()
                    usd_rub = rates["rates"]["RUB"]
                    usd_eur = rates["rates"]["EUR"]
                    usd_rub_change = "+0.00%"
                    usd_eur_change = "+0.00%"
                except:
                    usd_rub, usd_eur = 0, 0
                    usd_rub_change, usd_eur_change = "N/A", "N/A"
                
                try:
                    global_data = requests.get("https://api.coingecko.com/api/v3/global", timeout=5).json()["data"]
                    total_cap = global_data["total_market_cap"]["usd"]
                    btc_dominance = global_data["market_cap_percentage"]["btc"]
                    market_change = global_data.get("market_cap_change_percentage_24h_usd", 0)
                except:
                    total_cap, btc_dominance, market_change = 0, 0, 0
                
                try:
                    fng_data = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5).json()["data"][0]
                    fng_value = fng_data["value"]
                    fng_label = fng_data["value_classification"]
                except:
                    fng_value, fng_label = 0, "N/A"
                
                def fmt_crypto(p, c):
                    sign = " +" if c >= 0 else " "
                    return f"`{p:>10,.0f}$` ({sign}{abs(c):>5.2f}%)"
                
                def fmt_small(p, c):
                    sign = "🟢 +" if c >= 0 else " "
                    return f"`{p:>10,.2f}$` ({sign}{abs(c):>5.2f}%)"
                
                def fmt_rate(val, change):
                    return f"`{val:>12.2f}` ({change})"
                
                msg = f"""📊 **КОТИРОВКИ НА СЕГОДНЯ**
📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}

💎 *КРИПТОВАЛЮТЫ:*
  ₿ BTC: {fmt_crypto(btc_p, btc_c)}
  ♦ ETH: {fmt_crypto(eth_p, eth_c)}
  ◎ SOL: {fmt_crypto(sol_p, sol_c)}
  🟡 BNB: {fmt_crypto(bnb_p, bnb_c)}
  ✕ XRP: {fmt_small(xrp_p, xrp_c)}
  🐕 DOGE: {fmt_small(doge_p, doge_c)}
   ADA: {fmt_crypto(ada_p, ada_c)}

💱 *ВАЛЮТЫ:*
  USD/RUB: {fmt_rate(usd_rub, usd_rub_change)}
  USD/EUR: {fmt_rate(usd_eur, usd_eur_change)}

📊 *РЫНОК:*
  Total Cap: `{total_cap/1e9:>8.1f} B$` ({'🟢 +' if market_change > 0 else ' '}{abs(market_change):.2f}%)
  BTC Dom: `{btc_dominance:.1f}%`
  Strategy: `{fng_value}` ({fng_label})

🥇 *ЗОЛОТО:*
   Gold: {fmt_crypto(gold_p, gold_c)}

_Данные: CoinGecko, Alternative.me_"""
                
                send_vip_quote(msg)
                tg("sendMessage", data={"chat_id": uid, "text": "✅ Котировки с кнопкой Fear & Greed отправлены в каналы!"})
                return
                
            if txt.strip() == "/users" and is_admin(uid):
                report = get_users_report()
                msg = f"""👥 **СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ**

📊 **Всего уникальных:** {report['total']}

📈 **Активные:**
• Сегодня: {report['daily']}
• За неделю: {report['weekly']}
• За месяц: {report['monthly']}

🔘 **Популярные кнопки:**"""
                
                sorted_buttons = sorted(report['buttons'].items(), key=lambda x: x[1], reverse=True)[:10]
                for btn, count in sorted_buttons:
                    msg += f"\n• {btn}: {count}"
                
                tg("sendMessage", data={"chat_id": uid, "text": msg, "parse_mode": "Markdown"})
                return

            if txt.startswith("/force_close ") and is_admin(uid):
                parts = txt.split()
                if len(parts) >= 2:
                    sid = parts[1]
                    s = BX["active"].pop(sid, None)
                    if s:
                        s["status"] = "closed"
                        s["close_result"] = "admin_cancel"
                        save_stat(s, "expired", 0.0)
                        bx_save()
                        cap = f"🎛 *ОТМЕНЕНО АДМИНОМ* · {s['sym']}USDT · {s['tf']}\n_Закрыто вручную._"
                        if s.get("vip_msg"):
                            try:
                                tg("editMessageCaption", data={"chat_id": s["vip_chat"], "message_id": s["vip_msg"], "caption": cap, "parse_mode": "Markdown"})
                            except:
                                pass
                        tg("sendMessage", data={"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "text": f"🎛 {cap}", "parse_mode": "Markdown"})
                        tg("sendMessage", data={"chat_id": uid, "text": f"✅ Сетап #{sid} закрыт вручную"})
                    else:
                        tg("sendMessage", data={"chat_id": uid, "text": f"❌ Сетап #{sid} не найден"})
                return

            if txt.startswith('/manual_close ') and is_admin(uid):
                parts = txt.split()
                if len(parts) >= 3:
                    sid = parts[1]
                    try:
                        manual_price = float(parts[2])
                        s = BX["active"].pop(sid, None)
                        if s:
                            s["status"] = "closed"
                            s["close_result"] = "manual"
                            entry = s["entry_price"]
                            pnl_pct = (entry - manual_price) / entry * 100 if s["dir"] == "short" else (manual_price - entry) / entry * 100
                            pnl_sign = "+" if pnl_pct > 0 else ""
                            save_stat(s, "manual", pnl_pct)
                            bx_save()
                            cap = f"""🔧 *РУЧНОЕ ЗАКРЫТИЕ* · {s['sym']}USDT · {s['tf']}
📊 Цена закрытия: `{manual_price:,.2f}`
📈 Результат: {pnl_sign}{pnl_pct:.2f}%"""
                            if s.get("vip_msg"):
                                try: tg("editMessageCaption", data={"chat_id": s["vip_chat"], "message_id": s["vip_msg"], "caption": cap, "parse_mode": "Markdown"})
                                except: pass
                            tg("sendMessage", data={"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "text": f"⚠️ {cap}", "parse_mode": "Markdown"})
                            tg("sendMessage", data={"chat_id": uid, "text": f"✅ Сетап #{sid} закрыт вручную @ {manual_price:,.2f}\nPnL: {pnl_sign}{pnl_pct:.2f}%"})
                        else:
                            tg("sendMessage", data={"chat_id": uid, "text": f"❌ Сетап #{sid} не найден"})
                    except ValueError:
                        tg("sendMessage", data={"chat_id": uid, "text": "❌ Неверная цена. Формат: /manual_close ID ЦЕНА"})
                return

        if is_admin(uid) and str(uid) in BX.get("wait_link", {}):
            sid = BX["wait_link"].pop(str(uid))
            s = BX["pending"].pop(sid, None)
            if s:
                m_url = re.search(r"https?://\S+", txt)
                nums = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", re.sub(r"https?://\S+", "", txt))]
                if m_url and len(nums) >= 3:
                    entry_price = nums[0]
                    lo, hi = sorted(nums[1:3])
                    sl, tp = (lo, hi) if s["dir"] == "long" else (hi, lo)
                    s["id"] = sid
                    post_setup_to_vip(s, m_url.group(0), sl, tp, entry_price)
                    tg("sendMessage", data={"chat_id": uid, "text": f"✅ Сетап {sid} в VIP!\nВход: {entry_price}\nSL: {sl}\nTP: {tp}"})



def tg(method, **kw):
    for attempt in range(3):
        try:
            session = requests.Session()
            url = f"https://api.telegram.org/bot{TOKEN}/{method}"
            # 🔧 МАГИЯ: если есть 'data' и нет 'files', используем 'json=' для правильной отправки кнопок
            if 'data' in kw and 'files' not in kw:
                kw['json'] = kw.pop('data')
            r = session.post(url, **kw, timeout=10)
            return r.json()
        except Exception as e:
            if attempt < 2: _time.sleep(2)
    return {"ok": False}

@app.route("/tg_webhook", methods=["POST"])
def tg_webhook():
    try:
        update = request.get_json()
        if update:
            handle_update(update)
        return jsonify({"ok": True})
    except Exception as e:
        print(f"WEBHOOK ERR: {e}")
        return jsonify({"ok": True})

def normalize_chat(raw):
    s = str(raw)
    if "-1002026400906" in s: return "-1002026400906"
    if "-1001208487435" in s: return "-1001208487435"
    return s

def fetch_df(symbol="BTC", tf="1H"):
    rows = None
    pair = KRAKEN_PAIR.get(symbol)
    if pair and tf in KRAKEN_INT:
        try:
            r = requests.get("https://api.kraken.com/0/public/OHLC", params={"pair": pair, "interval": KRAKEN_INT[tf]}, timeout=10)
            arr = [v for k, v in r.json()["result"].items() if k != "last"][0]
            rows = [(int(k[0])*1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in arr]
        except: pass
    if not rows or len(rows) < 60:
        try:
            tf_map = {"15m": "15m", "1H": "1h", "4H": "4h", "D": "1d"}
            r = requests.get(f"https://api.binance.com/api/v3/klines", params={"symbol": f"{symbol}USDT", "interval": tf_map.get(tf, "1h"), "limit": 100}, timeout=10)
            rows = [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in r.json()]
        except: pass
    if not rows: raise ValueError("no data")
    df = pd.DataFrame(rows, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["ts"], unit="ms")
    return df.set_index("Date")

def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)

def make_chart(df, title="BTC/USD", level=None):
    df = df.tail(90).copy()
    apds = [mpf.make_addplot(rsi(df["Close"]), panel=1, ylabel="RSI", color="#7e57c2")]
    if level is not None:
        df["LEVEL"] = level
        apds.append(mpf.make_addplot(df["LEVEL"], color="#ffb300", width=1.4, linestyle="--"))
    mc = mpf.make_marketcolors(up="#ffffff", down="#000000", edge={"up": "#000000", "down": "#000000"}, wick="#000000")
    st = mpf.make_mpf_style(marketcolors=mc, gridstyle=":", gridcolor="#e0e0e0", y_on_right=True, facecolor="#ffffff", edgecolor="#ffffff")
    buf = io.BytesIO()
    fig, axlist = mpf.plot(df, type="candle", volume=False, style=st, addplot=apds, title=title, figsize=(8, 4.6), returnfig=True)
    fig.text(0.5, 0.5, "My Trading Club | BingX Dozor", ha='center', va='center', fontsize=24, color='black', alpha=0.15, fontweight='black', transform=fig.transFigure)
    fig.savefig(buf, format="png", dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf

def make_pnl_card(sym, direction, result, pnl_pct, pnl_usd, winrate):
    """Генерирует красивую карточку результата для репоста в соцсети"""
    import matplotlib.pyplot as plt
    import io
    
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    fig.patch.set_facecolor('#0f172a')
    ax.axis('off')
    
    is_win = result in ['tp', 'manual'] and pnl_pct > 0
    color = '#22c55e' if is_win else '#ef4444'
    result_text = "✅ TAKE PROFIT" if result == "tp" else "🛑 STOP LOSS" if result == "sl" else "⚠️ ЗАКРЫТО"
    
    ax.text(0.5, 0.85, "MTC TRADING CLUB", ha='center', va='center', fontsize=14, color='#94a3b8', fontweight='bold')
    ax.text(0.5, 0.72, f"{sym.upper()} USDT · {direction.upper()}", ha='center', va='center', fontsize=26, color='white', fontweight='black')
    ax.text(0.5, 0.52, result_text, ha='center', va='center', fontsize=22, color=color, fontweight='bold')
    
    pnl_usd_text = f"${pnl_usd:+,.2f}" if pnl_usd != 0 else ""
    ax.text(0.5, 0.32, f"{pnl_pct:+.2f}%  {pnl_usd_text}", ha='center', va='center', fontsize=32, color='white', fontweight='bold')
    ax.text(0.5, 0.12, f"Винрейт стратегии: {winrate:.1f}%  |  Не является фин. рекомендацией", ha='center', va='center', fontsize=10, color='#64748b')
    
    ax.add_patch(plt.Rectangle((0.05, 0.05), 0.9, 0.9, fill=False, edgecolor=color, linewidth=3, transform=fig.transFigure))
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='#0f172a')
    plt.close(fig)
    buf.seek(0)
    return buf

def make_fear_greed_gauge(value, label):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Wedge
    import numpy as np
    import io
    
    fig, ax = plt.subplots(figsize=(8, 6), dpi=150)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')
    
    if value <= 25:
        color, label_color = '#ff3b30', 'Extreme Fear'
    elif value <= 45:
        color, label_color = '#ff9500', 'Fear'
    elif value <= 55:
        color, label_color = '#ffcc00', 'Neutral'
    elif value <= 75:
        color, label_color = '#a2e000', 'Greed'
    else:
        color, label_color = '#00e676', 'Extreme Greed'
    
    ax.add_patch(Wedge((5, 5), 4, 0, 180, width=0.8, facecolor=color, edgecolor='white', linewidth=2))
    ax.add_patch(Wedge((5, 5), 4, 0, 180, width=0.8, facecolor='none', edgecolor='gray', linewidth=1, linestyle='--'))
    
    angle = (value / 100 * 180)
    ax.arrow(5, 5, 3.5 * np.cos(np.radians(180 - angle)), 3.5 * np.sin(np.radians(180 - angle)), width=0.15, color='white', length_includes_head=True, head_width=0.4, head_length=0.5)
    
    ax.text(5, 5, str(value), ha='center', va='center', fontsize=48, fontweight='bold', color='white')
    ax.text(5, 3.5, label_color, ha='center', va='center', fontsize=16, fontweight='bold', color='white')
    ax.text(5, 1.5, 'Fear & Greed Index', ha='center', va='center', fontsize=12, color='white', alpha=0.8)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close(fig)
    buf.seek(0)
    return buf

def send_text_safe(base, text):
    chunks = [text[i:i+4000] for i in range(0, max(len(text), 1), 4000)] or [""]
    for c in chunks:
        r = tg("sendMessage", data=dict(base, text=c))
        if r.get("ok"): return r
    return {"ok": False}

def _photo_meta(buf):
    buf.seek(0)
    head = buf.read(12)
    if head.startswith(b"\xff\xd8\xff"): return "photo.jpg", "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"): return "photo.png", "image/png"
    return "photo.jpg", "application/octet-stream"

def send_photo(base, caption, buf):
    r = tg("sendPhoto", data=dict(base, caption=caption), files={"photo": _photo_meta(buf)})
    if r.get("ok"): return r
    desc = r.get("description", "").lower()
    if "caption is too long" in desc:
        tg("sendPhoto", data=dict(base, caption=""), files={"photo": _photo_meta(buf)})
        return send_text_safe(base, caption)
    return r

def base_sym(symbol):
    s = (symbol or "").upper()
    for b in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        if b in s: return b
    return None

@app.route("/tv", methods=["POST"])
def tv():
    try:
        data = request.get_json(force=True, silent=True) or {}
        print(f"📥 ПОЛУЧЕН СИГНАЛ ОТ TRADINGVIEW: {data}") # <-- Это покажет нам точные данные
        
        text = data.get("text", "")
        kind = data.get("kind", "")
        chat = normalize_chat(data.get("chat_id", CHAT))
        tg_base = {"chat_id": chat, "parse_mode": data.get("parse_mode", "Markdown")}
        
        try:
            if data.get("message_thread_id"): 
                tg_base["message_thread_id"] = int(data.get("message_thread_id"))
        except: 
            pass
            
        if chat == "-1002026400906" and "message_thread_id" not in tg_base: 
            tg_base["message_thread_id"] = VIP_TOPIC
        
        if kind == "choch":
            sym = base_sym(data.get("symbol")) or "BTC"
            
            # БЕЗОПАСНОЕ ПРЕОБРАЗОВАНИЕ ЦЕНЫ (заменяем запятую на точку, если TV ее прислал)
            level_raw = data.get("level")
            level = None
            if level_raw:
                try:
                    level = float(str(level_raw).replace(',', '.'))
                except ValueError:
                    print(f"⚠️ Не удалось преобразовать уровень в число: {level_raw}")
            
            tf_raw = str(data.get("tf", "60"))
            # Расширенная карта таймфреймов на все случаи
            tf_map = {"240": "4H", "60": "1H", "15": "15m", "5": "5m", "D": "D", "1H": "1H", "4H": "4H", "1D": "D"}
            tf = tf_map.get(tf_raw, "1H")
            
            # Более надежное определение направления (учитывает регистр)
            text_upper = text.upper()
            direction = "long" if ("БЫЧИЙ" in text_upper or "LONG" in text_upper or "BUY" in text_upper) else "short"
            
            # Отправляем сообщение в канал
            send_text_safe(tg_base, text)
            
            # Создаем сетап
            sid = new_pending(sym, tf, direction, level)
            kb = {"inline_keyboard": [[{"text": f"🔷 BingX · {sym}USDT", "url": f"https://bingx.com/ru/perpetual/{sym}-USDT"}], [{"text": "✅ Сетап готов", "callback_data": f"bx:{sid}"}, {"text": "❌ Пропустить", "callback_data": f"skip:{sid}"}]]}
            admin_msg = f"*НОВЫЙ CHoCH СИГНАЛ*\n\n{text}\n\n_Создай сетап и отправь боту: ссылку, вход, SL и TP_"
            for aid in ADMIN_IDS:
                tg("sendMessage", data={"chat_id": aid, "parse_mode": "Markdown", "text": admin_msg, "reply_markup": kb})
            
            print(f"✅ CHoCH #{sid} успешно создан: {sym} {tf} {direction.upper()} (Level: {level})")
            return "ok"
        else:
            print(f"⚠️ Получен сигнал с неизвестным kind: {kind}")
            send_text_safe(tg_base, text)
            return "ok"
            
    except Exception as e: 
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА В /tv: {e}")
        import traceback
        traceback.print_exc()
        return "ok"

def setup_webhook():
    try:
        r = tg("setWebhook", data={"url": WEBHOOK_URL, "allowed_updates": ["message", "callback_query"], "max_connections": 40})
        if r.get("ok"): print("✅ Webhook установлен!")
        else: print(f"⚠️ Ошибка webhook: {r}")
    except Exception as e: print(f"️ Webhook error: {e}")

@app.route('/dashboard')
def dashboard_page():
    return render_template('dashboard.html')


@app.route('/api/stats', methods=['GET'])
def api_stats():
    stats = load_stats()
    total = stats.get("total", 0)
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    skipped = stats.get("skipped", 0)
    expired = stats.get("expired", 0)
    pnl = stats.get("pnl", 0.0)
    pnl_usd = stats.get("pnl_usd", 0.0)
    deposit = stats.get("deposit", 10000.0)
    balance = stats.get("balance", 10000.0)
    winrate = round((wins / total) * 100, 1) if total > 0 else 0
    return jsonify({
        "role": "admin", 
        "total": total, 
        "wins": wins, 
        "losses": losses, 
        "skipped": skipped, 
        "expired": expired, 
        "winrate": winrate, 
        "pnl": pnl,
        "pnl_usd": pnl_usd,
        "deposit": deposit,
        "balance": balance,
        "history": stats.get("history", []), 
        "active_setups_count": len(BX.get('active', {}))
    })

@app.route('/api/youtube', methods=['GET'])
def api_youtube():
    try:
        # Парсим HTML страницы НАШЕГО канала
        url = f"https://www.youtube.com/@MyTradingClub/videos"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        r = requests.get(url, headers=headers, timeout=10)
        
        if r.status_code == 200:
            videos = []
            # Ищем все видео на странице
            video_urls = re.findall(r'/watch\?v=([a-zA-Z0-9_-]{11})', r.text)
            
            # Ищем заголовки видео
            titles = re.findall(r'"title":{"runs":\[{"text":"([^"]+)"}\]', r.text)
            
            # Берем первые 12 уникальных видео
            seen = set()
            idx = 0
            for vid_id in video_urls:
                if vid_id not in seen and len(vid_id) == 11:
                    seen.add(vid_id)
                    title = titles[idx] if idx < len(titles) else f"Видео {vid_id}"
                    videos.append({
                        "id": vid_id,
                        "title": title,
                        "link": f"https://www.youtube.com/watch?v={vid_id}",
                        "thumbnail": f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"
                    })
                    idx += 1
                    if len(videos) >= 12:
                        break
            
            return jsonify(videos)
        
        return jsonify([])
    except Exception as e:
        print(f"YouTube API error: {e}")
        return jsonify([])

@app.route('/api/active_setups', methods=['GET'])
def api_active_setups():
    setups = []
    for sid, s in BX.get('active', {}).items():
        setups.append({'id': sid, 'sym': s.get('sym'), 'tf': s.get('tf'), 'dir': s.get('dir'), 'entry_price': s.get('entry_price'), 'status': s.get('status')})
    return jsonify(setups)

@app.route('/api/analyses', methods=['GET'])
def api_all_analyses():
    analyses = get_all_analyses()
    return jsonify(list(analyses.values()))

@app.route('/api/analysis/<setup_id>', methods=['GET', 'POST', 'DELETE'])
def api_analysis(setup_id):
    if request.method == 'GET':
        analysis = get_analysis(setup_id)
        if analysis:
            analysis['views'] = analysis.get('views', 0) + 1
            save_analysis(setup_id, analysis)
            return jsonify(analysis)
        return jsonify({"error": "Analysis not found"}), 404
    
    if request.method in ('POST', 'DELETE'):
        data = request.json
        admin_uid = data.get('admin_uid')
        if not admin_uid or int(admin_uid) not in ADMIN_IDS:
            return jsonify({"error": "Unauthorized"}), 403
        
        if request.method == 'POST':
            setup = BX.get('active', {}).get(setup_id) or BX.get('pending', {}).get(setup_id)
            analysis_data = {
                "setup_id": setup_id,
                "symbol": setup.get('sym') if setup else data.get('symbol'),
                "tf": setup.get('tf') if setup else data.get('tf'),
                "direction": setup.get('dir') if setup else data.get('direction'),
                "entry": setup.get('entry_price') if setup else data.get('entry'),
                "exit": data.get('exit'),
                "result": data.get('result'),
                "pnl": data.get('pnl'),
                "analysis_text": data.get('analysis_text', ''),
                "chart_image": data.get('chart_image', ''),
                "created_by": int(admin_uid),
                "created_at": _time.time(),
                "views": 0
            }
            save_analysis(setup_id, analysis_data)
            return jsonify({"ok": True, "setup_id": setup_id})
        
        elif request.method == 'DELETE':
            if delete_analysis(setup_id):
                return jsonify({"ok": True})
            return jsonify({"error": "Not found"}), 404

@app.route('/api/coin_analysis', methods=['GET', 'POST'])
def api_coin_analysis():
    if request.method == 'GET':
        return jsonify(load_coin_analyses())
    
    if request.method == 'POST':
        data = request.json
        admin_uid = data.get('admin_uid')
        if not admin_uid or int(admin_uid) not in ADMIN_IDS:
            return jsonify({"error": "Unauthorized"}), 403
        
        analysis_id = data.get('id') or str(_time.time())
        analysis_data = {
            "id": analysis_id,
            "symbol": data.get('symbol', ''),
            "tf1_link": data.get('tf1_link', ''),
            "tf2_link": data.get('tf2_link', ''),
            "tf3_link": data.get('tf3_link', ''),
            "tf4_link": data.get('tf4_link', ''),
            "chart_image": data.get('chart_image', ''),
            "tf1_screenshot": data.get('tf1_screenshot', ''),
            "tf2_screenshot": data.get('tf2_screenshot', ''),
            "tf3_screenshot": data.get('tf3_screenshot', ''),
            "tf4_screenshot": data.get('tf4_screenshot', ''),
            "tf1_comment": data.get('tf1_comment', ''),
            "tf2_comment": data.get('tf2_comment', ''),
            "tf3_comment": data.get('tf3_comment', ''),
            "tf4_comment": data.get('tf4_comment', ''),
            "description": data.get('description', ''),
            "bingx_link": data.get('bingx_link', ''),
            "created_by": int(admin_uid),
            "created_at": _time.time(),
            "updated_at": _time.time()
        }
        save_coin_analysis(analysis_id, analysis_data)
        return jsonify({"ok": True, "id": analysis_id})

@app.route('/api/coin_analysis/<analysis_id>', methods=['DELETE', 'PUT'])
def api_coin_analysis_item(analysis_id):
    if request.method == 'DELETE':
        data = request.json or {}
        admin_uid = data.get('admin_uid')
        if not admin_uid or int(admin_uid) not in ADMIN_IDS:
            return jsonify({"error": "Unauthorized"}), 403
        if delete_coin_analysis(analysis_id):
            return jsonify({"ok": True})
        return jsonify({"error": "Not found"}), 404
    
    if request.method == 'PUT':
        data = request.json
        admin_uid = data.get('admin_uid')
        if not admin_uid or int(admin_uid) not in ADMIN_IDS:
            return jsonify({"error": "Unauthorized"}), 403
        
        existing = get_coin_analysis(analysis_id)
        if not existing:
            return jsonify({"error": "Not found"}), 404
        
        existing.update({
            "symbol": data.get('symbol', existing.get('symbol')),
            "tf1_link": data.get('tf1_link', existing.get('tf1_link')),
            "tf2_link": data.get('tf2_link', existing.get('tf2_link')),
            "tf3_link": data.get('tf3_link', existing.get('tf3_link')),
            "chart_image": data.get('chart_image', existing.get('chart_image')),
            "description": data.get('description', existing.get('description')),
            "bingx_link": data.get('bingx_link', existing.get('bingx_link')),
            "updated_at": _time.time()
        })
        save_coin_analysis(analysis_id, existing)
        return jsonify({"ok": True})
def parse_upscale_news():
    """Парсим анонсы с канала Upscale News"""
    try:
        url = "https://t.me/s/upscale_news_ru"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, 'html.parser')
            announcements = []
            for msg in soup.find_all('div', class_='tgme_widget_message_text')[:10]:
                text = msg.get_text().strip()
                if text and len(text) > 20:
                    announcements.append({
                        "source": "Upscale News",
                        "title": text[:300],
                        "url": "https://t.me/upscale_news_ru",
                        "time": _time.time()
                    })
            return announcements
    except Exception as e:
        print(f" Ошибка парсинга Upscale News: {e}")
    return []

@app.route('/api/upscale_news')
def api_upscale_news():
    """API для получения анонсов Upscale"""
    announcements = parse_upscale_news()
    return jsonify(announcements)

@app.route('/api/miniapp_feed', methods=['GET'])
def api_miniapp_feed():
    """Возвращает ленту сетапов: активные админские + одобренные пользовательские"""
    setups = []
    
    # 1. Сначала добавляем активные сетапы админа (из памяти BX)
    active_setups = BX.get('active', {})
    for sid, s in active_setups.items():
        if s.get('status') in ['pending', 'active']:
            author_id = s.get('author_id', 0) 
            trust = get_user_trust_level(author_id)
            is_premium = s.get('is_premium', False)
            
            setups.append({
                'id': sid,
                'sym': s.get('sym', 'N/A'),
                'dir': s.get('dir', 'long'),
                'entry': '***' if is_premium else s.get('entry_price', 'N/A'),
                'sl': '***' if is_premium else s.get('sl', 'N/A'),
                'tp': '***' if is_premium else s.get('tp', 'N/A'),
                'chart': s.get('chart_image', ''),
                'author': trust['name'],
                'author_badge': trust['badge'],
                'author_color': trust['color'],
                'is_premium': is_premium,      # <-- ЗАПЯТАЯ ЗДЕСЬ ОБЯЗАТЕЛЬНА
                'user_id': author_id           # <-- ПРАВИЛЬНАЯ ПЕРЕМЕННАЯ (не row!)
            })

    # 2. ДОБАВЛЯЕМ ОДОБРЕННЫЕ ПОЛЬЗОВАТЕЛЬСКИЕ СЕТАПЫ ИЗ БАЗЫ ДАННЫХ
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, user_id, user_name, sym, dir, entry, sl, tp, tv_link
            FROM user_setups 
            WHERE status = 'approved'
            ORDER BY created_at DESC
        ''')
        rows = cursor.fetchall()
        conn.close()
        
        for row in rows:
            setups.append({
                'id': f"user_{row['id']}", 
                'sym': row['sym'],
                'dir': row['dir'],
                'entry': row['entry'],
                'sl': row['sl'],
                'tp': row['tp'],
                'chart': row['tv_link'] or '',
                'author': row['user_name'] or 'Трейдер',
                'author_badge': '🥉', 
                'author_color': '#c0c0c0',
                'is_premium': False,
                'user_id': row['user_id']      # <-- А вот здесь row['user_id'] уместен!
            })
    except Exception as e:
        print(f"⚠️ Ошибка загрузки одобренных сетапов из БД: {e}")

    return jsonify(setups)


@app.route('/api/create_user_setup', methods=['POST'])
def create_user_setup():
    try:
        data = request.json or {}
        print(f"📥 Получены данные: {data}")
        
        user_id = data.get('user_id') or 0
        user_name = str(data.get('user_name', 'Аноним'))
        sym = str(data.get('sym', '')).upper().strip()
        direction = str(data.get('dir', '')).lower()
        
        try:
            entry = float(data.get('entry', 0))
            sl = float(data.get('sl', 0))
            tp = float(data.get('tp', 0))
        except (TypeError, ValueError) as e:
            print(f"⚠️ Ошибка парсинга цен: {e}, data={data}")
            return jsonify({"error": f"Неверные цены: {e}"}), 400
        
        tv_link = str(data.get('tv_link', '')).strip()
        
        print(f"📝 Сетап: {sym} {direction} entry={entry} sl={sl} tp={tp} user={user_id}")
        
        # 1. Базовые проверки
        if not sym:
            return jsonify({"error": "Укажи монету"}), 400
        if entry <= 0 or sl <= 0 or tp <= 0:
            return jsonify({"error": "Цены должны быть положительными"}), 400
        if direction == 'long' and sl >= entry:
            return jsonify({"error": "Для LONG SL должен быть ниже входа"}), 400
        if direction == 'short' and sl <= entry:
            return jsonify({"error": "Для SHORT SL должен быть выше входа"}), 400
            
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        if risk == 0:
            return jsonify({"error": "SL не может равняться входу"}), 400
            
        rr = reward / risk
        if rr < 0.5 or rr > 10:
            return jsonify({"error": f"R:R должен быть от 1:0.5 до 1:10 (сейчас 1:{rr:.2f})"}), 400
            
        # 2. ПРОВЕРКА: ЕСТЬ ЛИ МОНЕТА НА BINANCE FUTURES
        try:
            r = requests.get(f"https://fapi.binance.com/fapi/v1/exchangeInfo?symbol={sym}USDT", timeout=3)
            if r.status_code != 200 or not r.json().get('symbols'):
                return jsonify({"error": f"Монета {sym}USDT не найдена на Binance Futures. Проверь тикер (например, BTC, ETH, SOL)!"}), 400
        except Exception as e:
            # Если Binance временно недоступен, мы не блокируем пользователя, но пишем в лог
            print(f"⚠️ Не удалось проверить монету на Binance: {e}")
            
        # 3. Проверка ссылок
        is_valid, error_msg = validate_setup_links(tv_link)
        if not is_valid:
            return jsonify({"error": error_msg}), 400
            
        # 4. Сохранение в БД
        setup_id = f"usr_{int(_time.time())}_{user_id}"
        print(f"💾 Сохраняем в БД: {setup_id}")
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO user_setups (id, user_id, user_name, sym, dir, entry, sl, tp, tv_link, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_moderation', ?)
        ''', (setup_id, int(user_id), user_name, sym, direction, entry, sl, tp, tv_link, _time.time()))
        conn.commit()
        conn.close()
        print(f"✅ Сохранено в БД")
        
        # 5. Уведомление админам
        try:
            dir_emoji = "🟢 LONG" if direction == "long" else "🔴 SHORT"
            admin_msg = f"""🆕 *НОВЫЙ СЕТАП НА МОДЕРАЦИИ*

👤 Автор: {user_name} (`{user_id}`)
💎 Монета: *{sym}USDT* {dir_emoji}
🎯 Вход: `{entry}`
🛡 SL: `{sl}` | 💰 TP: `{tp}`
📊 R:R: 1:{(reward/risk):.1f}
🔗 TV: {tv_link or 'Нет'}"""
            
            kb = {"inline_keyboard": [
                [{"text": "✅ Одобрить", "callback_data": f"approve_setup:{setup_id}"}, 
                 {"text": "❌ Отклонить", "callback_data": f"reject_setup:{setup_id}"}]
            ]}
            
            print(f"📤 Отправляем админам: {ADMIN_IDS}")
            for aid in ADMIN_IDS:
                tg("sendMessage", data={"chat_id": aid, "text": admin_msg, "parse_mode": "Markdown", "reply_markup": kb})
            print(f"✅ Админам отправлено")
        except Exception as e:
            print(f"⚠️ Ошибка отправки админам: {e}")
            
        return jsonify({"ok": True, "setup_id": setup_id, "message": "Отправлено на модерацию!"})
        
    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА create_user_setup: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/pending_setups', methods=['GET'])
def api_pending_setups():
    """Возвращает все сетапы на модерации (только для админов)"""
    try:
        admin_uid = request.args.get('admin_uid', type=int)
        if not admin_uid or admin_uid not in ADMIN_IDS:
            return jsonify({"error": "Unauthorized"}), 403
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, user_id, user_name, sym, dir, entry, sl, tp, tv_link, status, created_at
            FROM user_setups 
            WHERE status = 'pending_moderation'
            ORDER BY created_at DESC
        ''')
        rows = cursor.fetchall()
        conn.close()
        
        setups = []
        for row in rows:
            setups.append({
                'id': row['id'],
                'user_id': row['user_id'],
                'user_name': row['user_name'],
                'sym': row['sym'],
                'dir': row['dir'],
                'entry': row['entry'],
                'sl': row['sl'],
                'tp': row['tp'],
                'tv_link': row['tv_link'],
                'created_at': row['created_at']
            })
        
        return jsonify(setups)
    except Exception as e:
        print(f"Ошибка получения pending сетапов: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/approve_setup/<setup_id>', methods=['POST'])
def api_approve_setup(setup_id):
    """Одобрить сетап (только для админов)"""
    try:
        data = request.json or {}
        admin_uid = data.get('admin_uid')
        if not admin_uid or int(admin_uid) not in ADMIN_IDS:
            return jsonify({"error": "Unauthorized"}), 403
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE user_setups SET status = 'approved' WHERE id = ?", (setup_id,))
        conn.commit()
        conn.close()
        
        return jsonify({"ok": True, "message": "Сетап одобрен"})
    except Exception as e:
        print(f"Ошибка одобрения сетапа: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/reject_setup/<setup_id>', methods=['POST'])
def api_reject_setup(setup_id):
    """Отклонить сетап (только для админов)"""
    try:
        data = request.json or {}
        admin_uid = data.get('admin_uid')
        if not admin_uid or int(admin_uid) not in ADMIN_IDS:
            return jsonify({"error": "Unauthorized"}), 403
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE user_setups SET status = 'rejected' WHERE id = ?", (setup_id,))
        conn.commit()
        conn.close()
        
        return jsonify({"ok": True, "message": "Сетап отклонен"})
    except Exception as e:
        print(f"Ошибка отклонения сетапа: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/close_user_setup/<setup_id>', methods=['POST'])
def api_close_user_setup(setup_id):
    """Автор может закрыть свой активный сетап по текущей или заданной цене"""
    try:
        data = request.json or {}
        user_id = data.get('user_id')
        close_price = data.get('close_price')  # Может быть None (тогда берем текущую)
        reason = data.get('reason', 'Ручное закрытие автором')
        
        if not user_id:
            return jsonify({"error": "Не указан user_id"}), 400
        
        # Получаем сетап из БД
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_setups WHERE id = ?", (setup_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return jsonify({"error": "Сетап не найден"}), 404
        
        # Проверка авторства
        if int(row['user_id']) != int(user_id):
            conn.close()
            return jsonify({"error": "Это не ваш сетап"}), 403
        
        # Проверка статуса (только active можно закрыть вручную)
        # Проверка статуса (можно закрыть approved и active)
        if row['status'] not in ['approved', 'active']:
            conn.close()
            return jsonify({"error": f"Сетап нельзя закрыть (статус: {row['status']})"}), 400
        
        sym = row['sym']
        direction = row['dir']
        entry = float(row['entry'])
        sl = float(row['sl'])
        tp = float(row['tp'])
        user_name = row['user_name']
        
        # Если цена не указана — берем текущую с Binance
        if not close_price or close_price == 'current':
            try:
                klines = requests.get(
                    "https://api.binance.com/api/v3/klines", 
                    params={"symbol": f"{sym}USDT", "interval": "1m", "limit": 2}, 
                    timeout=5
                ).json()
                if isinstance(klines, list) and len(klines) >= 1:
                    close_price = float(klines[-1][4])
                else:
                    conn.close()
                    return jsonify({"error": "Не удалось получить текущую цену с Binance"}), 500
            except Exception as e:
                conn.close()
                return jsonify({"error": f"Ошибка получения цены: {str(e)}"}), 500
        else:
            close_price = float(close_price)
        
        # Рассчитываем PnL
        if direction == 'long':
            pnl_pct = ((close_price - entry) / entry) * 100
        else:
            pnl_pct = ((entry - close_price) / entry) * 100
        
        sign = "+" if pnl_pct > 0 else ""
        
        # Обновляем статус в БД
        cursor.execute("UPDATE user_setups SET status = 'closed_manual' WHERE id = ?", (setup_id,))
        conn.commit()
        conn.close()
        
        # Уведомление в канал
        public_msg = f"""✋ *РУЧНОЕ ЗАКРЫТИЕ* · {sym} {direction.upper()}
👤 Трейдер: {user_name}
📊 Цена закрытия: {close_price}
📈 Результат: {sign}{pnl_pct:.2f}%
 Причина: {reason}"""
        tg("sendMessage", data={"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "text": public_msg, "parse_mode": "Markdown"})
        
        # Уведомление автору
        private_msg = f"""✋ *Ваш сетап закрыт вручную*

{sym} {direction.upper()}
 Вход: {entry}
🚪 Закрытие: {close_price}
📊 Результат: {sign}{pnl_pct:.2f}%
📝 Причина: {reason}

Спасибо за активность в My Trading Club! 🐾"""
        tg("sendMessage", data={"chat_id": user_id, "text": private_msg, "parse_mode": "Markdown"})
        
        return jsonify({
            "ok": True, 
            "message": f"Сетап закрыт по цене {close_price}",
            "pnl_pct": round(pnl_pct, 2),
            "close_price": close_price
        })
        
    except Exception as e:
        print(f"❌ Ошибка закрытия сетапа: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/fear_greed')
def api_fear_greed():
    """Получаем Индекс Страха и Жадности"""
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
        if r.status_code == 200:
            data = r.json().get('data', [])
            if data:
                return jsonify(data[0])
        return jsonify({"error": "Failed to fetch"})
    except Exception as e:
        print(f"Fear & Greed API error: {e}")
        return jsonify({"error": str(e)})
@app.route('/api/market_data')
def api_market_data():
    """Получаем общий обзор рынка с CoinGecko"""
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=5)
        if r.status_code == 200:
            data = r.json().get('data', {})
            market_cap = data.get('total_market_cap', {}).get('usd', 0)
            btc_dominance = data.get('market_cap_percentage', {}).get('btc', 0)
            market_cap_change = data.get('market_cap_change_percentage_24h_usd', 0)
            
            return jsonify({
                "market_cap": f"${market_cap / 1e12:.2f}T", # В триллионах
                "btc_dominance": f"{btc_dominance:.1f}%",
                "trend": "up" if market_cap_change > 0 else "down",
                "trend_value": f"{abs(market_cap_change):.2f}%"
            })
        return jsonify({"error": "Failed to fetch"})
    except Exception as e:
        print(f"Market Data API error: {e}")
        return jsonify({"error": str(e)})

@app.route('/api/derivatives_data')
def api_derivatives_data():
    """Funding Rates + Ликвидации + RSI"""
    try:
        # 1. Funding Rates с Binance
        funding_r = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=5)
        funding_data = {}
        if funding_r.status_code == 200:
            for item in funding_r.json()[:10]:  # Топ-10 по funding
                symbol = item['symbol'].replace('USDT', '')
                rate = float(item['lastFundingRate']) * 100
                if abs(rate) > 0.005:  # Показываем только экстремальные (>0.005%)
                    funding_data[symbol] = {
                        'rate': f"{rate:.4f}%",
                        'next': datetime.fromtimestamp(int(item['nextFundingTime']/1000)).strftime('%H:%M'),
                        'extreme': '🔴' if rate > 0.01 else '🟢' if rate < -0.01 else '🟡'
                    }
        
        # 2. RSI для BTC и ETH на 4H и 1D
        rsi_data = {}
        for coin in ['BTC', 'ETH']:
            for tf, interval in [('4H', '4h'), ('1D', '1d')]:
                try:
                    klines = requests.get(
                        f"https://api.binance.com/api/v3/klines",
                        params={'symbol': f'{coin}USDT', 'interval': interval, 'limit': 100},
                        timeout=5
                    ).json()
                    closes = [float(k[4]) for k in klines]
                    # Считаем RSI
                    gains = []
                    losses = []
                    for i in range(1, len(closes)):
                        diff = closes[i] - closes[i-1]
                        if diff > 0:
                            gains.append(diff)
                            losses.append(0)
                        else:
                            gains.append(0)
                            losses.append(abs(diff))
                    avg_gain = sum(gains[-14:]) / 14
                    avg_loss = sum(losses[-14:]) / 14
                    rs = avg_gain / avg_loss if avg_loss > 0 else 0
                    rsi = 100 - (100 / (1 + rs))
                    rsi_data[f'{coin}_{tf}'] = {
                        'value': round(rsi, 1),
                        'signal': '🔴 Overbought' if rsi > 70 else '🟢 Oversold' if rsi < 30 else '🟡 Neutral',
                        'divergence': 'possible' if (rsi > 70 and coin == 'BTC') else 'none'
                    }
                except:
                    pass
        
        return jsonify({
            'funding': funding_data,
            'rsi': rsi_data
        })
    except Exception as e:
        print(f"Derivatives API error: {e}")
        return jsonify({"error": str(e)})

@app.route('/api/liquidations')
def api_liquidations():
    """Получаем данные о ликвидациях с Binance"""
    try:
        # Binance API для ликвидаций (последние 50)
        r = requests.get("https://fapi.binance.com/fapi/v1/allForceOrders?limit=50", timeout=5)
        if r.status_code == 200:
            data = r.json()
            liq_data = []
            for order in data:
                liq_data.append({
                    'symbol': order['symbol'].replace('USDT', ''),
                    'side': 'LONG' if order['side'] == 'SELL' else 'SHORT',  # LONG ликвидация = продажа
                    'price': float(order['price']),
                    'qty': float(order['origQty']),
                    'value': float(order['price']) * float(order['origQty']),
                    'time': datetime.fromtimestamp(order['time']/1000).strftime('%H:%M:%S')
                })
            return jsonify(liq_data)
        return jsonify([])
    except Exception as e:
        print(f"Liquidations API error: {e}")
        return jsonify([])

@app.route('/api/check_vip', methods=['GET'])
def check_vip():
    """Проверяет, подписан ли пользователь на VIP канал"""
    init_data = request.headers.get('X-Telegram-Init-Data', '')
    try:
        import urllib.parse
        data = dict(urllib.parse.parse_qsl(init_data))
        user = json.loads(data.get('user', '{}'))
        user_id = user.get('id')
        
        if not user_id:
            return jsonify({"is_vip": False})
        
        # Запрашиваем статус участника в Telegram API (используем CHAT как VIP канал)
        r = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getChatMember", 
            params={"chat_id": CHAT, "user_id": user_id},
            timeout=5
        )
        res = r.json()
        
        if res.get("ok"):
            status = res["result"]["status"]
            # member, administrator, creator - всё это считается активной подпиской
            if status in ["member", "administrator", "creator"]:
                return jsonify({"is_vip": True})
                
        return jsonify({"is_vip": False})
    except Exception as e:
        print(f"Check VIP error: {e}")
        return jsonify({"is_vip": False})


if __name__ == "__main__":
    import os
    import threading
    
    # 🚀 ЗАПУСКАЕМ ЦИКЛ СЛЕЖКИ ЗА ЦЕНАМИ В ОТДЕЛЬНОМ ПОТОКЕ!
    threading.Thread(target=bx_watch_loop, daemon=True).start()
    print("✅ Цикл слежки за сетапами запущен! Бот следит за TP/SL.")
    
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
