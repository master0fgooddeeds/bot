import io, re, time as _time, threading, hashlib, calendar, requests, json
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
matplotlib.use("Agg")
import mplfinance as mpf
from datetime import datetime, timedelta
from flask import Flask, request

TOKEN = "8845319540:AAHsIvOXzVeaKEBNWYWDIHVRPY9QX4YLSmA"
WEBHOOK_URL = "https://web-production-eadde.up.railway.app/tg_webhook"
app = Flask(__name__)

CHAT = "-1002026400906"
MTC_CHAT = "-1001208487435"
VIP_TOPIC = 2190
LAST = {"text": None, "ts": 0.0}
ADMIN_IDS = []

ACCESS_FILE = "user_access.json"

def load_access():
    try:
        with open(ACCESS_FILE, "r") as f: return json.load(f)
    except: return {}

def save_access():
    global USER_ACCESS
    try:
        with open(ACCESS_FILE, "w") as f: json.dump(USER_ACCESS, f, indent=2)
    except Exception as e: print("ACCESS SAVE FAIL:", e)

USER_ACCESS = load_access()

TOPIC_NAMES = {
    2190: "💎 VIP Сигналы", 1039: "💬 Флудилка", 1: "📢 General",
    2583: "📣 Объявления", 11: "💰 Сделки", 29: "📚 Статьи",
    2: "❓ Вопросы", 3233: "⚠️ Скам", 2581: "📖 Библиотека",
    3112: "⛓️ Блокчейн", 2189: "🎥 Стримы", 2816: "🎤 Саммит",
    2795: "📢 Новости", 133: "🎯 Тейки", 1040: "🔒 Тестовый",
    2710: "Топик 2710", 2767: "Топик 2767", 52: "Топик 52",
    2711: "Топик 2711", 45: "Топик 45", 46: "Топик 46",
    3: "Топик 3", 9: "Топик 9", 43: "Топик 43"
}

def can_access_topic_by_username(username, topic_id):
    username = username.lstrip("@").lower()
    if username in [str(uid) for uid in ADMIN_IDS]: return True
    return topic_id in USER_ACCESS.get(username, {}).get("topics", [])

def grant_access_by_username(username, topic_id, days=30):
    username = username.lstrip("@").lower()
    if username not in USER_ACCESS: USER_ACCESS[username] = {"topics": [], "expires": {}}
    if topic_id not in USER_ACCESS[username]["topics"]: USER_ACCESS[username]["topics"].append(topic_id)
    USER_ACCESS[username]["expires"][str(topic_id)] = _time.time() + (days * 86400)
    save_access()

def revoke_access_by_username(username, topic_id):
    username = username.lstrip("@").lower()
    if username in USER_ACCESS:
        if topic_id in USER_ACCESS[username]["topics"]: USER_ACCESS[username]["topics"].remove(topic_id)
        if str(topic_id) in USER_ACCESS[username]["expires"]: del USER_ACCESS[username]["expires"][str(topic_id)]
        save_access()

def get_user_access_info(username):
    username = username.lstrip("@").lower()
    if username not in USER_ACCESS: return None
    topics = []
    for topic_id in USER_ACCESS[username].get("topics", []):
        exp = USER_ACCESS[username]["expires"].get(str(topic_id), 0)
        days_left = max(0, int((exp - _time.time()) / 86400))
        topics.append({"id": topic_id, "name": TOPIC_NAMES.get(topic_id, f"Топик {topic_id}"), "days_left": days_left})
    return topics

def check_expired_access():
    global USER_ACCESS
    now = _time.time()
    changed = False
    for username, data in list(USER_ACCESS.items()):
        for topic_str, exp_time in list(data.get("expires", {}).items()):
            if now > exp_time:
                topic_id = int(topic_str)
                if topic_id in data.get("topics", []):
                    data["topics"].remove(topic_id)
                    del data["expires"][topic_str]
                    changed = True
    if changed: save_access()

KRAKEN_INT = {"D": 1440, "4H": 240, "1H": 60, "15m": 15}
COIN_GRAN = {"D": 86400, "1H": 3600, "15m": 900}
KRAKEN_PAIR = {"BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "XRP": "XRPUSD", "DOGE": "DOGEUSD"}
COIN_PAIR = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD", "XRP": "XRP-USD", "DOGE": "DOGE-USD"}

TF_PROFILE = {
    "15m": {"candle_min": 15, "ttl_candles": 8, "style": "скальпинг", "valid_hours": 8},
    "1H": {"candle_min": 60, "ttl_candles": 8, "style": "интрадей", "valid_hours": 24},
    "4H": {"candle_min": 240, "ttl_candles": 8, "style": "свинг", "valid_hours": 72},
    "D": {"candle_min": 1440, "ttl_candles": 6, "style": "позиция", "valid_hours": 168},
}

SETUPS_FILE = "bingx_setups.json"
STATS_FILE = "trading_stats.json"
BX = {"pending": {}, "active": {}, "wait_link": {}, "seq": 1}

def bx_load():
    try:
        with open(SETUPS_FILE) as f: BX.update(json.load(f))
    except: pass

def bx_save():
    try:
        with open(SETUPS_FILE, "w") as f: json.dump(BX, f)
    except Exception as e: print("BX SAVE FAIL:", e)

def load_stats():
    try:
        with open(STATS_FILE, "r") as f: return json.load(f)
    except: return {"total": 0, "wins": 0, "losses": 0, "skipped": 0, "expired": 0, "history": []}

def save_stat(setup, result, pnl):
    stats = load_stats()
    stats["total"] += 1
    status_text = {"tp": "TP", "sl": "SL", "skipped_tp": "Пропуск", "expired": "Истек", "admin_cancel": "Отмена"}.get(result, "Неизвестно")
    if result == "tp": stats["wins"] += 1
    elif result == "sl": stats["losses"] += 1
    elif result == "skipped_tp": stats["skipped"] += 1
    elif result in ["expired", "admin_cancel"]: stats["expired"] += 1
    stats["history"].append({"date": datetime.now().strftime("%d.%m.%Y"), "sym": setup["sym"], "tf": setup["tf"], "dir": setup["dir"], "result": status_text, "pnl": round(pnl, 2)})
    if len(stats["history"]) > 100: stats["history"] = stats["history"][-100:]
    with open(STATS_FILE, "w") as f: json.dump(stats, f, indent=2)

def fetch_admins_from_group():
    global ADMIN_IDS
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getChatAdministrators", params={"chat_id": CHAT})
        if r.json().get("ok"):
            ADMIN_IDS = [m["user"]["id"] for m in r.json()["result"] if m["status"] in ("creator", "administrator") and not m["user"].get("is_bot")]
            print(f"👑 Загружено админов: {len(ADMIN_IDS)}")
    except Exception as e: print("⚠️ Не подтянул админов:", e)

bx_load()
fetch_admins_from_group()

def is_admin(uid): return uid in ADMIN_IDS

def new_pending(sym, tf, direction, level):
    sid = str(BX["seq"])
    BX["seq"] += 1
    BX["pending"][sid] = {"sym": sym, "tf": tf, "dir": direction, "level": level, "created": _time.time()}
    bx_save()
    return sid

def get_price(sym):
    pair = KRAKEN_PAIR.get(sym)
    if not pair: return None
    try:
        r = requests.get("https://api.kraken.com/0/public/Ticker", params={"pair": pair}, timeout=10)
        return float(list(r.json()["result"].values())[0]["c"][0])
    except: return None

def post_setup_to_vip(s, link, sl, tp, entry_price):
    prof = TF_PROFILE.get(s["tf"], TF_PROFILE["4H"])
    ttl = prof["candle_min"] * prof["ttl_candles"] * 60
    valid_hours = prof.get("valid_hours", 24)
    s.update({"sl": sl, "tp": tp, "link": link, "entry_price": entry_price,
              "expires": _time.time() + ttl,
              "expires_entry": _time.time() + (valid_hours * 3600),
              "status": "pending"})
    entry = get_price(s["sym"])
    emo = "🟢" if s["dir"] == "long" else "🔴"
    d_txt = "LONG" if s["dir"] == "long" else "SHORT"
    exp_str = datetime.fromtimestamp(s["expires_entry"]).strftime("%d.%m %H:%M")
    risk = abs(entry_price - sl)
    reward = abs(tp - entry_price)
    rr = reward / risk if risk > 0 else 0
    cap = f"""{emo} *СЕТАП {d_txt}* · {s['sym']}USDT · {s['tf']} · {prof['style']}

🎯 *Вход:* `{entry_price:,.2f}`
🛡 *SL:* `{sl:,.2f}`
💰 *TP:* `{tp:,.2f}`
📊 *R:R:* 1:{rr:.1f}

👉 [Перейти на BingX]({link})

⏳ *Актуально до:* {exp_str} МСК
_Если цена не дойдет до входа — сетап будет аннулирован_

⚠️ _Не является финансовой рекомендацией. DYOR._"""
    try:
        buf = make_chart(fetch_df(s["sym"], s["tf"]), title=f"{s['sym']}/USD {s['tf']}", level=entry_price)
        r = send_photo({"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "parse_mode": "Markdown"}, cap, buf)
    except:
        r = send_text_safe({"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "parse_mode": "Markdown"}, cap)
    try:
        s["vip_chat"] = r["result"]["message"]["chat"]["id"]
        s["vip_msg"] = r["result"]["message_id"]
    except: pass
    BX["active"][s["id"]] = s
    bx_save()
    print(f"✅ Сетап {s['id']} опубликован в VIP")

def close_setup(sid, result):
    s = BX["active"].pop(sid, None)
    if not s: return
    s["status"] = "closed"
    s["close_result"] = result
    head = {"tp": "🎯 TP ВЗЯТ", "sl": "🛡 SL СРАБОТАЛ", "exp": "⏳ ИСТЕК", "admin_cancel": "❌ ОТМЕНЕНО"}.get(result, "ЗАКРЫТ")
    entry = s.get("entry_price", 0)
    exit_price = s["tp"] if result == "tp" else s["sl"]
    pnl_pct = ((exit_price - entry) / entry * 100) if s["dir"] == "long" else ((entry - exit_price) / entry * 100)
    pnl_sign = "+" if pnl_pct > 0 else ""
    cap = f"""{head} · {s['sym']}USDT · {s['tf']}
⏱ В работе: {(_time.time() - s.get('entry_time', s['created'])) / 3600:.1f} ч
📊 Результат: {pnl_sign}{pnl_pct:.2f}%
🛡 SL: {s['sl']:,.2f} | 💰 TP: {s['tp']:,.2f}"""
    if s.get("vip_msg"):
        try: tg("editMessageCaption", data={"chat_id": s["vip_chat"], "message_id": s["vip_msg"], "caption": cap, "parse_mode": "Markdown"})
        except: pass
    for aid in ADMIN_IDS:
        tg("sendMessage", data={"chat_id": aid, "text": f"🎛 Сетап {sid} закрыт: {head}\nРезультат: {pnl_sign}{pnl_pct:.2f}%"})
    save_stat(s, result, pnl_pct)
    bx_save()

def bx_watch_step():
    now = _time.time()
    for sid in list(BX["active"].keys()):
        s = BX["active"][sid]
        price = get_price(s["sym"])
        if not price: continue
        buf_frac = 0.001 if s["tf"] in ("15m", "1H") else 0.0
        if s.get("status") == "pending":
            entry = s["entry_price"]
            reached, skipped_tp = False, False
            if s["dir"] == "long":
                if price >= s["tp"] * (1 + buf_frac): skipped_tp = True
                elif price <= entry * (1 + buf_frac): reached = True
            else:
                if price <= s["tp"] * (1 - buf_frac): skipped_tp = True
                elif price >= entry * (1 - buf_frac): reached = True
            if skipped_tp:
                cap = f"""⚠️ *СЕТАП АННУЛИРОВАН* · {s['sym']}USDT · {s['tf']}

🚀 *Причина:* Цена достигла TP, не задев вход.
🎯 *Ожидаемый вход:* `{entry:,.2f}`
📍 *Текущая цена:* `{price:,.2f}`"""
                if s.get("vip_msg"):
                    try: tg("editMessageCaption", data={"chat_id": s["vip_chat"], "message_id": s["vip_msg"], "caption": cap, "parse_mode": "Markdown"})
                    except: pass
                BX["active"].pop(sid, None); save_stat(s, "skipped_tp", 0.0); bx_save()
                print(f"⚠️ Сетап {sid} аннулирован: улетел на ТП")
                continue
            if now > s.get("expires_entry", 0):
                if not s.get("asked_extend"):
                    s["asked_extend"] = True
                    bx_save()
                    kb = {"inline_keyboard": [[{"text": "✅ Продлить (24ч)", "callback_data": f"conf:{sid}"}, {"text": "❌ Закрыть", "callback_data": f"cncl:{sid}"}]]}
                    admin_msg = f"⏳ *СЕТАП ТРЕБУЕТ РЕШЕНИЯ* · {s['sym']}USDT · {s['tf']}\n\n⏱ Время вышло.\n🎯 Вход: `{s['entry_price']:,.2f}`\n📍 Цена: `{price:,.2f}`\n\n_Что делаем?_"
                    for aid in ADMIN_IDS:
                        tg("sendMessage", data={"chat_id": aid, "text": admin_msg, "parse_mode": "Markdown", "reply_markup": json.dumps(kb)})
                    print(f"⏳ Сетап {sid} ждёт решения админа")
                continue
            if reached:
                s["status"] = "active"
                s["entry_time"] = now
                bx_save()
                print(f"✅ Сетап {sid} активирован @ {price:,.2f}")
                active_cap = f"""✅ *СЕТАП АКТИВИРОВАН* · {s['sym']}USDT · {s['tf']}

🎯 Вход пройден! Цена: `{price:,.2f}`
🛡 *STOP LOSS:* `{s['sl']:,.2f}`
💰 *TAKE PROFIT:* `{s['tp']:,.2f}`

🛡 Бот следит за SL и TP до победного конца!"""
                try: tg("sendMessage", data={"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "text": active_cap, "parse_mode": "Markdown", "reply_to_message_id": s.get("vip_msg")})
                except: pass
        elif s.get("status") == "active":
            result = None
            if s["dir"] == "long":
                if price >= s["tp"] * (1 + buf_frac): result = "tp"
                elif price <= s["sl"] * (1 - buf_frac): result = "sl"
            else:
                if price <= s["tp"] * (1 - buf_frac): result = "tp"
                elif price >= s["sl"] * (1 + buf_frac): result = "sl"
            if result:
                print(f"🎯 #{sid}: {result.upper()} @ {price:,.2f}")
                close_setup(sid, result)

def bx_watch_loop():
    while True:
        try: bx_watch_step()
        except Exception as e: print("WATCH LOOP:", e)
        _time.sleep(60)

def handle_update(up):
    cb = up.get("callback_query")
    if cb:
        uid = cb["from"]["id"]
        data = cb.get("data", "")
        if not is_admin(uid):
            tg("answerCallbackQuery", data={"callback_query_id": cb["id"], "text": "Не твои кнопки 😼"}); return
        tg("answerCallbackQuery", data={"callback_query_id": cb["id"], "text": "ok"})
        if data.startswith("bx:"):
            BX["wait_link"][str(uid)] = data[3:]
            tg("sendMessage", data={"chat_id": uid, "text": "🔗 Вставь ссылку BingX, а следующей строкой ВХОД, SL и TP:\nhttps://...\n79000 78000 81000"})
        elif data.startswith("skip:"):
            BX["pending"].pop(data[5:], None); bx_save()
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
                save_stat(s, "expired", 0.0); bx_save()
                cap = f"""❌ *ОТМЕНЕНО АДМИНОМ* · {s['sym']}USDT · {s['tf']}
_Сетап признан неактуальным._"""
                if s.get("vip_msg"):
                    try: tg("editMessageCaption", data={"chat_id": s["vip_chat"], "message_id": s["vip_msg"], "caption": cap, "parse_mode": "Markdown"})
                    except: pass
                tg("sendMessage", data={"chat_id": uid, "text": f"❌ Сетап #{sid} закрыт админом"})
        return

    msg = up.get("message")
    if msg:
        uid = msg["from"]["id"]
        txt = msg.get("text", "")
        chat_type = msg.get("chat", {}).get("type")
        is_private = chat_type == "private"
        is_group_chat = chat_type in ("supergroup", "group") and is_admin(uid)

        if is_private or is_group_chat:
            if txt.strip() == "/start":
                if is_admin(uid):
                    tg("sendMessage", data={"chat_id": uid, "text": f"👑 Привет, Админ!\n\nДоступные команды:\n/stats - статистика\n/active - активные сетапы\n/grant @user TOPIC_ID [ДНИ] - выдать доступ\n/revoke @user TOPIC_ID - отозвать\n/list [TOPIC_ID] - список\n/myaccess - мои подписки\n/force_close ID - закрыть сетап вручную"})
                else:
                    tg("sendMessage", data={"chat_id": uid, "text": "Привет! Я ассистент My Trading Club."})
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

📈 *Всего:* {stats['total']}
🟢 *TP:* {stats['wins']} ({win_rate:.1f}%)
🔴 *SL:* {stats['losses']}
⚪ *Пропуск:* {stats['skipped']}
⏳ *Истекло:* {stats['expired']}

🕒 *Последние 5:*
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
                    msg = "📊 *АКТИВНЫЕ СЕТАПЫ:*\n\n" + "\n".join(lines)
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
                        save_stat(s, "expired", 0.0); bx_save()
                        cap = f"""❌ *ОТМЕНЕНО АДМИНОМ* · {s['sym']}USDT · {s['tf']}
_Закрыто вручную._"""
                        if s.get("vip_msg"):
                            try: tg("editMessageCaption", data={"chat_id": s["vip_chat"], "message_id": s["vip_msg"], "caption": cap, "parse_mode": "Markdown"})
                            except: pass
                        tg("sendMessage", data={"chat_id": uid, "text": f"✅ Сетап #{sid} закрыт вручную"})
                    else:
                        tg("sendMessage", data={"chat_id": uid, "text": f"❌ Сетап #{sid} не найден"})
                return

            if txt.startswith("/grant ") and is_admin(uid):
                parts = txt.split()
                if len(parts) >= 3:
                    grant_access_by_username(parts[1].lstrip("@").lower(), int(parts[2]), int(parts[3]) if len(parts) > 3 else 30)
                    tg("sendMessage", data={"chat_id": uid, "text": f"✅ Доступ выдан {parts[1]}"})
                return

            if txt.startswith("/revoke ") and is_admin(uid):
                parts = txt.split()
                if len(parts) >= 3:
                    revoke_access_by_username(parts[1].lstrip("@").lower(), int(parts[2]))
                    tg("sendMessage", data={"chat_id": uid, "text": f"🚫 Доступ отозван {parts[1]}"})
                return

            if txt.strip() == "/myaccess":
                username = msg["from"].get("username")
                if not username:
                    tg("sendMessage", data={"chat_id": uid, "text": "❌ У вас нет @username"})
                    return
                topics = get_user_access_info(username)
                if not topics:
                    tg("sendMessage", data={"chat_id": uid, "text": "📭 Нет активных подписок"})
                else:
                    topics_list = "\n".join([f"• {t['name']} — {t['days_left']} дн." for t in topics])
                    tg("sendMessage", data={"chat_id": uid, "text": f"📋 Ваши подписки:\n{topics_list}"})
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
            r = session.post(url, **kw, timeout=10)
            return r.json()
        except Exception as e:
            if attempt < 2: _time.sleep(2)
    return {"ok": False}

@app.route("/tg_webhook", methods=["POST"])
def tg_webhook():
    try:
        update = request.get_json()
        if update: handle_update(update)
        return "ok"
    except Exception as e:
        print(f"WEBHOOK ERR: {e}")
        return "ok"

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
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text", "")
    kind = data.get("kind", "")
    chat = normalize_chat(data.get("chat_id", CHAT))
    tg_base = {"chat_id": chat, "parse_mode": data.get("parse_mode", "Markdown")}
    try:
        if data.get("message_thread_id"): tg_base["message_thread_id"] = int(data.get("message_thread_id"))
    except: pass
    if chat == "-1002026400906" and "message_thread_id" not in tg_base: tg_base["message_thread_id"] = VIP_TOPIC

    try:
        if kind == "choch":
            sym = base_sym(data.get("symbol")) or "BTC"
            level = float(data.get("level")) if data.get("level") else None
            tf_raw = str(data.get("tf", "240"))
            tf = {"240": "4H", "60": "1H", "15": "15m", "5": "5m", "D": "D"}.get(tf_raw, "4H")
            direction = "long" if ("Бычий" in text or "LONG" in text) else "short"
            send_text_safe(tg_base, text)
            sid = new_pending(sym, tf, direction, level)
            kb = {"inline_keyboard": [[{"text": f"🚀 BingX · {sym}USDT", "url": f"https://bingx.com/ru/perpetual/{sym}-USDT"}], [{"text": "✅ Сетап готов", "callback_data": f"bx:{sid}"}, {"text": "❌ Пропустить", "callback_data": f"skip:{sid}"}]]}
            admin_msg = f"🔔 *НОВЫЙ CHoCH СИГНАЛ*\n\n{text}\n\n_Создай сетап и отправь боту: ссылку, вход, SL и TP_"
            for aid in ADMIN_IDS:
                tg("sendMessage", data={"chat_id": aid, "parse_mode": "Markdown", "text": admin_msg, "reply_markup": json.dumps(kb)})
            print(f"✅ CHoCH #{sid} создан")
            return "ok"
    except Exception as e:
        print(f"❌ CHoCH ERROR: {e}")

    send_text_safe(tg_base, text)
    return "ok"

def access_check_loop():
    while True:
        try: check_expired_access()
        except: pass
        _time.sleep(3600)

def setup_webhook():
    try:
        r = tg("setWebhook", data={"url": WEBHOOK_URL, "allowed_updates": ["message", "callback_query"], "max_connections": 40})
        if r.get("ok"):
            print("✅ Webhook установлен!")
        else:
            print(f"⚠️ Ошибка webhook: {r}")
    except Exception as e:
        print(f"⚠️ Webhook error: {e}")

if not globals().get("_ALL_STARTED"):
    _ALL_STARTED = True
    setup_webhook()
    threading.Thread(target=bx_watch_loop, daemon=True).start()
    threading.Thread(target=access_check_loop, daemon=True).start()
    print("\n" + "="*50)
    print("✅ БОТ ЗАПУЩЕН (ЧИСТАЯ ВЕРСИЯ)!")
    print(f"👑 Админов: {len(ADMIN_IDS)}")
    print("="*50 + "\n")
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
