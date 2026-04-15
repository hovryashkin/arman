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

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CREDENTIALS_FILE = "/etc/secrets/credentials.json"

RENDER_URL = "https://arman-c2rh.onrender.com"
KZ_TIMEZONE = pytz.timezone("Asia/Almaty")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_histories = defaultdict(lambda: deque(maxlen=10))

# ================= DB =================

conn = sqlite3.connect("namaz.db", check_same_thread=False)
cursor = conn.cursor()

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
    return kb

def namaz_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Фаджр", "Зухр", "Аср")
    kb.add("Магриб", "Иша")
    kb.add("📊 Статистика", "📈 График")
    kb.add("🏆 Рейтинг")
    kb.add("⬅️ Назад")
    return kb

# ================= НАМАЗ =================

def get_prayer_times():
    pt = PrayTimes('MWL')
    now = datetime.now(KZ_TIMEZONE)

    times = pt.getTimes(
        (43.238949, 76.889709),
        now,
        5
    )

    return {
        "Фаджр": times["fajr"],
        "Зухр": times["dhuhr"],
        "Аср": times["asr"],
        "Магриб": times["maghrib"],
        "Иша": times["isha"]
    }

# ================= ЛОГИКА НАМАЗА =================

def update_prayer(user_id, prayer):
    today = str(datetime.now(KZ_TIMEZONE).date())

    cursor.execute("SELECT * FROM prayers WHERE user_id=? AND date=?", (user_id, today))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO prayers VALUES (?, ?, 0,0,0,0,0)", (user_id, today))

    cursor.execute(f"UPDATE prayers SET {prayer}=1 WHERE user_id=? AND date=?", (user_id, today))
    conn.commit()

def check_full_day(user_id):
    today = str(datetime.now(KZ_TIMEZONE).date())

    cursor.execute("""
    SELECT fajr,dhuhr,asr,maghrib,isha FROM prayers
    WHERE user_id=? AND date=?
    """, (user_id, today))

    row = cursor.fetchone()
    return row and all(row)

def update_streak(user_id):
    today = datetime.now(KZ_TIMEZONE).date()
    yesterday = str(today - timedelta(days=1))

    cursor.execute("""
    SELECT fajr,dhuhr,asr,maghrib,isha FROM prayers
    WHERE user_id=? AND date=?
    """, (user_id, yesterday))

    y = cursor.fetchone()

    if not y or not all(y):
        count = 1
    else:
        cursor.execute("SELECT count FROM streak WHERE user_id=?", (user_id,))
        row = cursor.fetchone()
        count = (row[0] if row else 0) + 1

    cursor.execute("""
    INSERT OR REPLACE INTO streak (user_id, last_day, count)
    VALUES (?, ?, ?)
    """, (user_id, str(today), count))

    conn.commit()

# ================= ГРАФИК =================

def generate_chart(user_id):
    cursor.execute("""
    SELECT date, fajr+dhuhr+asr+maghrib+isha FROM prayers
    WHERE user_id=? ORDER BY date DESC LIMIT 7
    """, (user_id,))

    data = cursor.fetchall()
    data.reverse()

    dates = [d[0] for d in data]
    values = [d[1] for d in data]

    plt.figure()
    plt.plot(dates, values)
    plt.xticks(rotation=45)

    file = f"{user_id}.png"
    plt.savefig(file)
    plt.close()

    return file

# ================= AI =================

def ai_answer(uid, text):
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

# ================= HANDLERS =================

@bot.message_handler(commands=["start"])
def start(m):
    bot.send_message(m.chat.id, "Выбери режим 👇", reply_markup=main_menu())

@bot.message_handler(func=lambda m: True)
def msg(m):
    uid = m.from_user.id
    text = m.text

    if text == "🕌 Намаз":
        bot.send_message(m.chat.id, "Меню намаза", reply_markup=namaz_menu())
        return

    if text == "⬅️ Назад":
        bot.send_message(m.chat.id, "Главное меню", reply_markup=main_menu())
        return

    mapping = {
        "Фаджр": "fajr",
        "Зухр": "dhuhr",
        "Аср": "asr",
        "Магриб": "maghrib",
        "Иша": "isha"
    }

    if text in mapping:
        update_prayer(uid, mapping[text])

        if check_full_day(uid):
            update_streak(uid)

            today = str(datetime.now(KZ_TIMEZONE).date())
            cursor.execute("""
            SELECT fajr,dhuhr,asr,maghrib,isha FROM prayers
            WHERE user_id=? AND date=?
            """, (uid, today))

            row = cursor.fetchone()

            try:
                sheet.append_row([uid, today, *row])
            except:
                pass

            bot.send_message(m.chat.id, "🔥 Все 5 намазов засчитаны!")
        else:
            bot.send_message(m.chat.id, f"Отмечено: {text}")
        return

    if text == "📊 Статистика":
        cursor.execute("SELECT count FROM streak WHERE user_id=?", (uid,))
        row = cursor.fetchone()
        bot.send_message(m.chat.id, f"🔥 Серия дней: {row[0] if row else 0}")
        return

    if text == "📈 График":
        file = generate_chart(uid)
        bot.send_photo(m.chat.id, open(file, "rb"))
        return

    if text == "🏆 Рейтинг":
        cursor.execute("SELECT user_id, count FROM streak ORDER BY count DESC LIMIT 10")
        top = cursor.fetchall()

        msg_text = "🏆 Топ:\n"
        for i, (u, c) in enumerate(top, 1):
            msg_text += f"{i}. {u} — {c}\n"

        bot.send_message(m.chat.id, msg_text)
        return

    # AI
    try:
        answer = ai_answer(uid, text)
        bot.send_message(m.chat.id, answer)
    except:
        bot.send_message(m.chat.id, "Ошибка AI")

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