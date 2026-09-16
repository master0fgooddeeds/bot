import os, io, re, time as _time, threading, hashlib, calendar, requests, json
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
matplotlib.use("Agg")
import mplfinance as mpf
from datetime import datetime, timedelta
from flask import Flask, request
from flask import render_template, jsonify

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
                json.dump({"total": 0, "wins": 0, "losses": 0, "skipped": 0, "expired": 0, "pnl": 0.0, "history": []}, f)
        with open(STATS_FILE, "r") as f: return json.load(f)
    except: return {"total": 0, "wins": 0, "losses": 0, "skipped": 0, "expired": 0, "pnl": 0.0, "history": []}

def load_analyses():
    import os
    try:
        if not os.path.exists(ANALYSES_FILE):
            with open(ANALYSES_FILE, "w") as f:
                json.dump({}, f)
        with open(ANALYSES_FILE, "r") as f: return json.load(f)
    except: return {}

def save_stat(setup, result, pnl):
    stats = load_stats()
    stats["total"] += 1
    status_text = {"tp": "TP", "sl": "SL", "skipped_tp": "Пропуск", "expired": "Истек", "admin_cancel": "Отмена"}.get(result, "Неизвестно")
    if result == "tp": stats["wins"] += 1
    elif result == "sl": stats["losses"] += 1
    elif result == "skipped_tp": stats["skipped"] += 1
    elif result in ["expired", "admin_cancel"]: stats["expired"] += 1
    
    stats["pnl"] = round(stats["pnl"] + pnl, 2)
    stats["history"].append({"date": datetime.now().strftime("%d.%m.%Y"), "sym": setup["sym"], "tf": setup["tf"], "dir": setup["dir"], "result": status_text, "pnl": round(pnl, 2)})
    
    if len(stats["history"]) > 1000:
        stats["history"] = stats["history"][-1000:]
    
    with open(STATS_FILE, "w") as f: json.dump(stats, f, indent=2)

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
    head = {"tp": "🎯 TP ВЗЯТ", "sl": " SL СРАБОТАЛ", "exp": "⏳ ИСТЕК", "admin_cancel": "❌ ОТМЕНЕНО"}.get(result, "ЗАКРЫТ")
    entry = s.get("entry_price", 0)
    exit_price = s["tp"] if result == "tp" else s["sl"]
    pnl_pct = ((exit_price - entry) / entry * 100) if s["dir"] == "long" else ((entry - exit_price) / entry * 100)
    pnl_sign = "+" if pnl_pct > 0 else ""
    cap = f"""{head} · {s['sym']}USDT · {s['tf']}
 В работе: {(_time.time() - s.get('entry_time', s['created'])) / 3600:.1f} ч
📊 Результат: {pnl_sign}{pnl_pct:.2f}%
 SL: {s['sl']:,.2f} | 💰 TP: {s['tp']:,.2f}"""
    if s.get("vip_msg"):
        try: tg("editMessageCaption", data={"chat_id": s["vip_chat"], "message_id": s["vip_msg"], "caption": cap, "parse_mode": "Markdown"})
        except: pass
    tg("sendMessage", data={"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "text": f" {cap}", "parse_mode": "Markdown"})
    for aid in ADMIN_IDS:
        tg("sendMessage", data={"chat_id": aid, "text": f" Сетап {sid} закрыт: {head}\nРезультат: {pnl_sign}{pnl_pct:.2f}%"})
    save_stat(s, result, pnl_pct)
    bx_save()

def bx_watch_step():
    now = _time.time()
    for sid in list(BX["active"].keys()):
        s = BX["active"][sid]
        price = get_price(s["sym"])
        if not price: 
            print(f"⚠️ Не удалось получить цену для {s['sym']}")
            continue
        
        print(f"📊 #{sid} {s['sym']} {s['dir'].upper()}: цена={price:,.2f} | вход={s['entry_price']:,.2f} | TP={s['tp']:,.2f} | SL={s['sl']:,.2f}")
        
        buf_frac = 0.0005  # Уменьшил буфер до 0.05% для точности
        
        if s.get("status") == "pending":
            entry = s["entry_price"]
            reached, skipped_tp = False, False
            
            # ПРАВИЛЬНАЯ ЛОГИКА ВХОДА:
            if s["dir"] == "long":
                # LONG: ждём ОТКАТА вниз до входа
                if price >= s["tp"] * (1 - buf_frac): 
                    skipped_tp = True  # Улетел на TP без входа
                elif price <= entry * (1 + buf_frac): 
                    reached = True  # Цена опустилась до входа
            else:
                # SHORT: ждём ПОДЪЁМА до входа
                if price <= s["tp"] * (1 + buf_frac): 
                    skipped_tp = True  # Улетел на TP без входа
                elif price >= entry * (1 - buf_frac): 
                    reached = True  # Цена поднялась до входа
            
            if skipped_tp:
                cap = f"""⚠️ *СЕТАП АННУЛИРОВАН* · {s['sym']}USDT · {s['tf']}

🚀 *Причина:* Цена достигла TP, не задев вход.
 *Ожидаемый вход:* `{entry:,.2f}`
📍 *Текущая цена:* `{price:,.2f}`"""
                if s.get("vip_msg"):
                    try: tg("editMessageCaption", data={"chat_id": s["vip_chat"], "message_id": s["vip_msg"], "caption": cap, "parse_mode": "Markdown"})
                    except: pass
                BX["active"].pop(sid, None)
                save_stat(s, "skipped_tp", 0.0)
                bx_save()
                print(f"️ Сетап {sid} аннулирован: улетел на ТП")
                continue
                
            if now > s.get("expires_entry", 0):
                if not s.get("asked_extend"):
                    s["asked_extend"] = True
                    bx_save()
                    kb = {"inline_keyboard": [[{"text": "✅ Продлить (24ч)", "callback_data": f"conf:{sid}"}, {"text": "❌ Закрыть", "callback_data": f"cncl:{sid}"}]]}
                    admin_msg = f"⏳ *СЕТАП ТРЕБУЕТ РЕШЕНИЯ* · {s['sym']}USDT · {s['tf']}\n\n⏰ Время вышло.\n🎯 Вход: `{s['entry_price']:,.2f}`\n📍 Цена: `{price:,.2f}`\n\n_Что делаем?_"
                    for aid in ADMIN_IDS:
                        tg("sendMessage", data={"chat_id": aid, "text": admin_msg, "parse_mode": "Markdown", "reply_markup": json.dumps(kb)})
                    print(f" Сетап {sid} ждёт решения админа")
                continue
                
            if reached:
                s["status"] = "active"
                s["entry_time"] = now
                bx_save()
                print(f"✅ Сетап {sid} АКТИВИРОВАН @ {price:,.2f}")
                active_cap = f"""✅ *СЕТАП АКТИВИРОВАН* · {s['sym']}USDT · {s['tf']}

🎯 Вход пройден! Цена: `{price:,.2f}`
🛡 *STOP LOSS:* `{s['sl']:,.2f}`
💰 *TAKE PROFIT:* `{s['tp']:,.2f}`

🛡 Бот следит за SL и TP до победного конца!"""
                try: 
                    tg("sendMessage", data={"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "text": active_cap, "parse_mode": "Markdown", "reply_to_message_id": s.get("vip_msg")})
                except: pass
                
        elif s.get("status") == "active":
            result = None
            
            # ПРАВИЛЬНАЯ ЛОГИКА TP/SL:
            if s["dir"] == "long":
                # LONG: TP когда цена ПОДНЯЛАСЬ, SL когда цена УПАЛА
                if price >= s["tp"] * (1 - buf_frac): 
                    result = "tp"
                elif price <= s["sl"] * (1 + buf_frac): 
                    result = "sl"
            else:
                # SHORT: TP когда цена УПАЛА, SL когда цена ПОДНЯЛАСЬ
                if price <= s["tp"] * (1 + buf_frac): 
                    result = "tp"
                elif price >= s["sl"] * (1 - buf_frac): 
                    result = "sl"
                    
            if result:
                print(f" #{sid}: {result.upper()} @ {price:,.2f}")
                close_setup(sid, result)

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

def handle_update(up):
    cb = up.get("callback_query")
    if cb:
        uid = cb["from"]["id"]
        data = cb.get("data", "")
        if not is_admin(uid):
            tg("answerCallbackQuery", data={"callback_query_id": cb["id"], "text": "Не твои кнопки 😼"})
            return
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
                cap = f""" *ОТМЕНЕНО АДМИНОМ* · {s['sym']}USDT · {s['tf']}
_Сетап признан неактуальным._"""
                if s.get("vip_msg"):
                    try: tg("editMessageCaption", data={"chat_id": s["vip_chat"], "message_id": s["vip_msg"], "caption": cap, "parse_mode": "Markdown"})
                    except: pass
                tg("sendMessage", data={"chat_id": uid, "text": f" Сетап #{sid} закрыт админом"})
        elif data == "gen_vip_post":
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
⚙️ *ТФ:* 4H → 15m, 1H → 5m

 Жми кнопку ниже, чтобы открыть дашборд!"""
            kb = {"inline_keyboard": [[{"text": " Открыть Дашборд", "web_app": {"url": "https://web-production-eadde.up.railway.app/dashboard"}}]]}
            tg("sendMessage", data={"chat_id": uid, "text": vip_post, "parse_mode": "Markdown", "reply_markup": json.dumps(kb)})
            tg("sendMessage", data={"chat_id": uid, "text": "ℹ️ *Это сообщение можно переслать в VIP-канал!*\n\nПросто зажми сообщение и выбери 'Переслать'.", "parse_mode": "Markdown"})
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
                    kb = {"inline_keyboard": [[{"text": "📊 Открыть Дашборд", "web_app": {"url": "https://web-production-eadde.up.railway.app/dashboard"}}], [{"text": "📢 Сгенерировать пост для VIP", "callback_data": "gen_vip_post"}]]}
                    welcome_text = """*Привет, Админ!*

Добро пожаловать в *MTC Trading Platform*!

🎯 *Возможности платформы:*
• Сигналы CHoCH + FVG в реальном времени
• Автоматический анализ рынка
• Статистика и аналитика сделок

📊 *Используй кнопки ниже:*
• "Открыть Дашборд" — твой личный кабинет
• "Сгенерировать пост для VIP" — создай красивый пост для пересылки в канал

_Платформа в разработке. Следим за прогрессом!_"""
                    tg("sendMessage", data={"chat_id": uid, "text": welcome_text, "parse_mode": "Markdown", "reply_markup": json.dumps(kb)})
                else:
                    kb = {"inline_keyboard": [[{"text": " Открыть Дашборд", "web_app": {"url": "https://web-production-eadde.up.railway.app/dashboard"}}]]}
                    welcome_text = """*Привет!*

Добро пожаловать в *MTC Trading Platform*!

Здесь ты найдёшь:
• Актуальную статистику сделок
• Разборы сигналов
• Аналитику рынка

Жми кнопку ниже, чтобы открыть дашборд!"""
                    tg("sendMessage", data={"chat_id": uid, "text": welcome_text, "parse_mode": "Markdown", "reply_markup": json.dumps(kb)})
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
 *SL:* {stats['losses']}
 *Пропуск:* {stats['skipped']}
 *Истекло:* {stats['expired']}
 *Общий PnL:* {stats.get('pnl', 0)}%

 *Последние 5:*
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
                    msg_text = " *АКТИВНЫЕ СЕТАПЫ:*\n\n" + "\n".join(lines)
                    tg("sendMessage", data={"chat_id": uid, "text": msg_text, "parse_mode": "Markdown"})
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
                        cap = f" *ОТМЕНЕНО АДМИНОМ* · {s['sym']}USDT · {s['tf']}\n_Закрыто вручную._"
                        if s.get("vip_msg"):
                            try:
                                tg("editMessageCaption", data={"chat_id": s["vip_chat"], "message_id": s["vip_msg"], "caption": cap, "parse_mode": "Markdown"})
                            except:
                                pass
                        tg("sendMessage", data={"chat_id": CHAT, "message_thread_id": VIP_TOPIC, "text": f"🎛 {cap}", "parse_mode": "Markdown"})
                        tg("sendMessage", data={"chat_id": uid, "text": f"✅ Сетап #{sid} закрыт вручную"})
                    else:
                        tg("sendMessage", data={"chat_id": uid, "text": f" Сетап #{sid} не найден"})
                return

            if txt.startswith("/test_setup ") and is_admin(uid):
                parts = txt.split()
                if len(parts) >= 4:
                    sym = parts[1].upper()
                    tf = parts[2]
                    direction = parts[3].lower()
                    sid = new_pending(sym, tf, direction, None)
                    kb = {"inline_keyboard": [[{"text": f" BingX · {sym}USDT", "url": f"https://bingx.com/ru/perpetual/{sym}-USDT"}], [{"text": "✅ Сетап готов", "callback_data": f"bx:{sid}"}, {"text": "❌ Пропустить", "callback_data": f"skip:{sid}"}]]}
                    tg("sendMessage", data={"chat_id": uid, "text": f" *ТЕСТОВЫЙ СЕТАП #{sid}*\n\n{sym} {tf} {direction}\n\nНажми 'Сетап готов' и отправь данные.", "parse_mode": "Markdown", "reply_markup": json.dumps(kb)})
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
            kb = {"inline_keyboard": [[{"text": f" BingX · {sym}USDT", "url": f"https://bingx.com/ru/perpetual/{sym}-USDT"}], [{"text": "✅ Сетап готов", "callback_data": f"bx:{sid}"}, {"text": "❌ Пропустить", "callback_data": f"skip:{sid}"}]]}
            admin_msg = f" *НОВЫЙ CHoCH СИГНАЛ*\n\n{text}\n\n_Создай сетап и отправь боту: ссылку, вход, SL и TP_"
            for aid in ADMIN_IDS:
                tg("sendMessage", data={"chat_id": aid, "parse_mode": "Markdown", "text": admin_msg, "reply_markup": json.dumps(kb)})
            print(f"✅ CHoCH #{sid} создан")
            return "ok"
    except Exception as e: print(f" CHoCH ERROR: {e}")
    send_text_safe(tg_base, text)
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

@app.route('/api/stats')
def api_stats():
    stats = load_stats()
    total = stats.get("total", 0)
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    skipped = stats.get("skipped", 0)
    expired = stats.get("expired", 0)
    pnl = stats.get("pnl", 0.0)
    winrate = round((wins / total) * 100, 1) if total > 0 else 0
    return jsonify({"role": "admin", "total": total, "wins": wins, "losses": losses, "skipped": skipped, "expired": expired, "winrate": winrate, "pnl": pnl, "history": stats.get("history", []), "active_setups_count": len(BX.get('active', {}))})

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
    """Возвращает активные сетапы для ленты мини-аппа напрямую из памяти"""
    setups = []
    active_setups = BX.get('active', {})
    
    for sid, s in active_setups.items():
        # Показываем только те, что в работе или ожидают входа
        if s.get('status') in ['pending', 'active']:
            setups.append({
                'id': sid,
                'sym': s.get('sym', 'N/A'),
                'dir': s.get('dir', 'long'),
                'entry': s.get('entry_price', 'N/A'),
                'sl': s.get('sl', 'N/A'),
                'tp': s.get('tp', 'N/A'),
                'chart': s.get('chart_image', s.get('chart', ''))
            })
    
    return jsonify(setups)
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
if __name__ == "__main__":
    import os
    import threading
    
    # 🚀 ЗАПУСКАЕМ ЦИКЛ СЛЕЖКИ ЗА ЦЕНАМИ В ОТДЕЛЬНОМ ПОТОКЕ!
    threading.Thread(target=bx_watch_loop, daemon=True).start()
    print("✅ Цикл слежки за сетапами запущен! Бот следит за TP/SL.")
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
