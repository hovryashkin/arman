import os
import telebot
from telebot import types
import requests
from flask import Flask, request
from collections import defaultdict, deque
from datetime import datetime, timedelta
import pytz
import sqlite3
import threading
import time
from praytimes import PrayTimes
from apscheduler.schedulers.background import BackgroundScheduler

# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

RENDER_URL = os.getenv("RENDER_URL", "https://your-app.onrender.com")
KZ = pytz.timezone("Asia/Almaty")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_hist = defaultdict(lambda: deque(maxlen=8))
user_cache = {}

# ================= DB (SQLite fallback) =================

conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    lat REAL,
    lng REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS prayers (
    user_id INTEGER,
    date TEXT,
    fajr INT DEFAULT 0,
    dhuhr INT DEFAULT 0,
    asr INT DEFAULT 0,
    maghrib INT DEFAULT 0,
    isha INT DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS streak (
    user_id INTEGER PRIMARY KEY,
    count INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    text TEXT,
    time TEXT,
    sent INT DEFAULT 0
)
""")

conn.commit()

# ================= UI =================

def menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🕌 Намаз", "🤖 AI")
    kb.add("📍 Локация", "⏰ Напоминание")
    return kb

def namaz_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Фаджр", "Зухр", "Аср")
    kb.add("Магриб", "Иша")
    kb.add("⬅️ Назад")
    return kb

# ================= USER =================

def get_loc(uid):
    cursor.execute("SELECT lat,lng FROM users WHERE user_id=?", (uid,))
    row = cursor.fetchone()
    return row if row else (43.238949, 76.889709)

# ================= NAMAZ =================

def calc_times(uid):
    lat, lng = get_loc(uid)

    pt = PrayTimes('MWL')
    now = datetime.now(KZ)

    t = pt.getTimes((lat, lng), now, 5)

    return t

# ================= PRAY LOGIC =================

def mark(uid, p):
    today = str(datetime.now(KZ).date())

    cursor.execute("""
    INSERT OR IGNORE INTO prayers (user_id,date,fajr,dhuhr,asr,maghrib,isha)
    VALUES (?,?,?,?,?,?,?)
    """, (uid, today, 0,0,0,0,0))

    cursor.execute(f"""
    UPDATE prayers SET {p}=1
    WHERE user_id=? AND date=?
    """, (uid, today))

    conn.commit()

def full(uid):
    today = str(datetime.now(KZ).date())

    cursor.execute("""
    SELECT fajr,dhuhr,asr,maghrib,isha
    FROM prayers WHERE user_id=? AND date=?
    """, (uid, today))

    r = cursor.fetchone()
    return r and all(r)

# ================= AI =================

def ai(uid, text):
    user_hist[uid].append({"role": "user", "content": text})

    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
        json={
            "model": "meta-llama/llama-3-8b-instruct",
            "messages": list(user_hist[uid])
        }
    )

    return r.json()["choices"][0]["message"]["content"]

# ================= REMINDERS =================

def reminder_worker():
    while True:
        now = datetime.now(KZ)

        cursor.execute("""
        SELECT id,user_id,text,time FROM reminders WHERE sent=0
        """)

        rows = cursor.fetchall()

        for r in rows:
            try:
                t = datetime.strptime(r[3], "%Y-%m-%d %H:%M")

                if abs((t - now).total_seconds()) < 20:
                    bot.send_message(r[1], f"⏰ {r[2]}")
                    cursor.execute("UPDATE reminders SET sent=1 WHERE id=?", (r[0],))
                    conn.commit()
            except:
                pass

        time.sleep(15)

threading.Thread(target=reminder_worker, daemon=True).start()

# ================= PRAYER AUTO =================

scheduler = BackgroundScheduler()

def auto_prayer():
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()

    for (uid,) in users:
        try:
            t = calc_times(uid)
            now = datetime.now(KZ)

            for name, val in t.items():
                try:
                    dt = datetime.strptime(val, "%H:%M").replace(
                        year=now.year, month=now.month, day=now.day
                    )

                    if abs((dt - now).total_seconds()) < 40:
                        bot.send_message(uid, f"🕌 {name.upper()}")
                except:
                    pass
        except:
            pass

scheduler.add_job(auto_prayer, "interval", seconds=30)
scheduler.start()

# ================= HANDLERS =================

@bot.message_handler(commands=["start"])
def start(m):
    bot.send_message(m.chat.id, "v3 бот активен", reply_markup=menu())

@bot.message_handler(content_types=["location"])
def loc(m):
    uid = m.from_user.id

    cursor.execute("""
    INSERT OR REPLACE INTO users (user_id,lat,lng)
    VALUES (?,?,?)
    """, (uid, m.location.latitude, m.location.longitude))

    conn.commit()

    bot.send_message(m.chat.id, "📍 Локация сохранена")

@bot.message_handler(func=lambda m: True)
def msg(m):
    uid = m.from_user.id
    text = m.text

    if text == "🕌 Намаз":
        bot.send_message(m.chat.id, "Меню", reply_markup=namaz_menu())
        return

    if text == "⬅️ Назад":
        bot.send_message(m.chat.id, "Меню", reply_markup=menu())
        return

    if text == "📍 Локация":
        bot.send_message(m.chat.id, "Отправь геолокацию")
        return

    if text == "⏰ Напоминание":
        bot.send_message(m.chat.id, "Формат: /rem 2026-04-15 18:30 текст")
        return

    if text.startswith("/rem"):
        try:
            _, d, t, *txt = text.split()
            txt = " ".join(txt)

            cursor.execute("""
            INSERT INTO reminders (user_id,text,time)
            VALUES (?,?,?)
            """, (uid, txt, f"{d} {t}"))

            conn.commit()
            bot.send_message(m.chat.id, "⏰ добавлено")
        except:
            bot.send_message(m.chat.id, "ошибка")
        return

    mapping = {
        "Фаджр": "fajr",
        "Зухр": "dhuhr",
        "Аср": "asr",
        "Магриб": "maghrib",
        "Иша": "isha"
    }

    if text in mapping:
        mark(uid, mapping[text])

        if full(uid):
            bot.send_message(m.chat.id, "🔥 все намазы выполнены")

        return

    try:
        bot.send_message(m.chat.id, ai(uid, text))
    except:
        bot.send_message(m.chat.id, "AI error")

# ================= WEBHOOK =================

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(
        request.get_data().decode("utf-8")
    )
    bot.process_new_updates([update])
    return "ok"

@app.route("/")
def index():
    return "ok"

# ================= RUN =================

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}/webhook/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))