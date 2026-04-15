import os
import telebot
from telebot import types
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
from flask import Flask, request
from collections import defaultdict, deque
from datetime import datetime, timedelta
import pytz
import sqlite3
import matplotlib.pyplot as plt
from praytimes import PrayTimes
import threading
import time

# ================= CONFIG =================

TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CREDENTIALS_FILE = "/etc/secrets/credentials.json"

RENDER_URL = "https://arman-c2rh.onrender.com"
KZ = pytz.timezone("Asia/Almaty")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_histories = defaultdict(lambda: deque(maxlen=8))

# кеш времени намаза
user_prayer_cache = {}

# ================= DB =================

conn = sqlite3.connect("namaz.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    lat REAL,
    lng REAL,
    ai INTEGER DEFAULT 1
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS prayers (
    user_id INTEGER,
    date TEXT,
    fajr INTEGER,
    dhuhr INTEGER,
    asr INTEGER,
    maghrib INTEGER,
    isha INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS streak (
    user_id INTEGER PRIMARY KEY,
    last_day TEXT,
    count INTEGER
)
""")

conn.commit()

# ================= GOOGLE SHEETS =================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    CREDENTIALS_FILE, scope
)
client = gspread.authorize(creds)
sheet = client.open("Zarina Answers").sheet1

# ================= UI =================

def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🕌 Намаз", "💬 AI")
    kb.add("📍 Локация")
    return kb

def namaz_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Фаджр", "Зухр", "Аср")
    kb.add("Магриб", "Иша")
    kb.add("⬅️ Назад")
    return kb

# ================= USER =================

def get_user_location(uid):
    cursor.execute("SELECT lat,lng FROM users WHERE user_id=?", (uid,))
    row = cursor.fetchone()
    return row if row else (43.238949, 76.889709)

# ================= NAMAZ ENGINE =================

def calc_times(uid):
    lat, lng = get_user_location(uid)

    pt = PrayTimes('MWL')
    now = datetime.now(KZ)

    times = pt.getTimes((lat, lng), now, 5)

    return {
        "fajr": times["fajr"],
        "dhuhr": times["dhuhr"],
        "asr": times["asr"],
        "maghrib": times["maghrib"],
        "isha": times["isha"]
    }

def refresh_cache(uid):
    user_prayer_cache[uid] = calc_times(uid)

# ================= AUTO PRAYER NOTIFICATIONS =================

def prayer_worker():
    while True:
        now = datetime.now(KZ)

        for uid in list(user_prayer_cache.keys()):
            times = user_prayer_cache.get(uid)
            if not times:
                continue

            for name, t in times.items():
                try:
                    pray_time = datetime.strptime(t, "%H:%M").replace(
                        year=now.year, month=now.month, day=now.day
                    )

                    diff = abs((pray_time - now).total_seconds())

                    # отправка за 1 минуту
                    if diff < 30:
                        bot.send_message(uid, f"🕌 Время намаза: {name.upper()}")
                except:
                    continue

        time.sleep(20)

threading.Thread(target=prayer_worker, daemon=True).start()

# ================= AI =================

def ai(uid, text):
    user_histories[uid].append({"role": "user", "content": text})

    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
        json={
            "model": "meta-llama/llama-3-8b-instruct",
            "messages": list(user_histories[uid])
        }
    )

    return r.json()["choices"][0]["message"]["content"]

# ================= PRAYERS LOGIC =================

def mark(uid, prayer):
    today = str(datetime.now(KZ).date())

    cursor.execute("SELECT * FROM prayers WHERE user_id=? AND date=?", (uid, today))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO prayers VALUES (?, ?, 0,0,0,0,0)", (uid, today))

    cursor.execute(f"UPDATE prayers SET {prayer}=1 WHERE user_id=? AND date=?", (uid, today))
    conn.commit()

def full(uid):
    today = str(datetime.now(KZ).date())

    cursor.execute("""
    SELECT fajr,dhuhr,asr,maghrib,isha FROM prayers
    WHERE user_id=? AND date=?
    """, (uid, today))

    row = cursor.fetchone()
    return row and all(row)

# ================= HANDLERS =================

@bot.message_handler(commands=["start"])
def start(m):
    bot.send_message(m.chat.id, "Бот активен", reply_markup=main_menu())

@bot.message_handler(content_types=["location"])
def location(m):
    uid = m.from_user.id

    cursor.execute("""
    INSERT OR REPLACE INTO users (user_id, lat, lng)
    VALUES (?, ?, ?)
    """, (uid, m.location.latitude, m.location.longitude))

    conn.commit()

    refresh_cache(uid)

    bot.send_message(m.chat.id, "📍 Локация обновлена и намаз активирован")

@bot.message_handler(func=lambda m: True)
def msg(m):
    uid = m.from_user.id
    text = m.text

    if text == "🕌 Намаз":
        refresh_cache(uid)
        bot.send_message(m.chat.id, "Меню", reply_markup=namaz_menu())
        return

    if text == "⬅️ Назад":
        bot.send_message(m.chat.id, "Главное меню", reply_markup=main_menu())
        return

    if text == "📍 Локация":
        bot.send_message(m.chat.id, "Отправь геолокацию")
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
            bot.send_message(m.chat.id, "🔥 Все намазы засчитаны!")

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