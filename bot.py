import os
import telebot
from telebot import types
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
from flask import Flask, request
import qrcode
from io import BytesIO
from collections import defaultdict, deque
from datetime import datetime
import threading
import time
import random
import pytz

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CREDENTIALS_FILE = "/etc/secrets/credentials.json"

RENDER_URL = "https://arman-c2rh.onrender.com"
KZ_TIMEZONE = pytz.timezone("Asia/Almaty")

# ================= GOOGLE SHEETS =================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

sheet = None

try:
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        CREDENTIALS_FILE, scope
    )
    client = gspread.authorize(creds)
    sheet = client.open("Zarina Answers").sheet1
    print("Google Sheets подключен")
except Exception as e:
    print("Ошибка подключения Google Sheets:", e)

# ================= TELEGRAM + FLASK =================

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_histories = defaultdict(lambda: deque(maxlen=10))
known_users = set()
user_waiting_diary = set()

# ===== ТЕСТ ЛИЧНОСТИ =====

user_test_state = {}
user_test_answers = {}

test_questions = [
    "Ты чаще:\nA) привязываешься\nB) держишь дистанцию",
    "Если человек тебе дорог, ты:\nA) покажешь это\nB) скроешь",
    "Ты бы простил измену?\nA) да\nB) нет",
    "Ты больше:\nA) логика\nB) эмоции",
    "Ты боишься потерять людей?\nA) да\nB) нет",
    "Ты чаще страдаешь молча?\nA) да\nB) нет"
]

# ================= ЗАГРУЗКА ПОЛЬЗОВАТЕЛЕЙ =================

def load_users_from_sheet():
    if not sheet:
        return
    try:
        rows = sheet.get_all_values()
        for row in rows[1:]:
            if len(row) > 1 and row[1]:
                known_users.add(int(row[1]))
        print("Пользователи загружены:", len(known_users))
    except Exception as e:
        print("Ошибка загрузки пользователей:", e)

load_users_from_sheet()

# ================= OPENROUTER =================

def get_openrouter_answer(user_id, user_question):

    user_histories[user_id].append(
        {"role": "user", "content": user_question}
    )

    messages = [
        {
            "role": "system",
            "content": (
                "Ты — немного дерзкий, но заботливый человек. "
                "Отвечай коротко (1-2 предложения), на русском. "
                "Добавляй лёгкий флирт 😏❤️"
            )
        }
    ] + list(user_histories[user_id])

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "meta-llama/llama-3-8b-instruct",
            "messages": messages,
            "temperature": 1.0
        }
    )

    response.raise_for_status()

    answer = response.json()["choices"][0]["message"]["content"]

    user_histories[user_id].append(
        {"role": "assistant", "content": answer}
    )

    return answer

# ================= СТАРТ =================

@bot.message_handler(commands=["start"])
def start(message):

    known_users.add(message.from_user.id)

    bot.send_message(
        message.chat.id,
        "Я задам тебе 6 странных вопросов\n"
        "И скажу, какой ты человек на самом деле 😏\n\n"
        "Готов? (да / нет)"
    )

    user_test_state[message.from_user.id] = "start"

# ================= ОСНОВНАЯ ЛОГИКА =================

@bot.message_handler(func=lambda m: True)
def handle_message(message):

    user_id = message.from_user.id
    text = (message.text or "").lower()

    known_users.add(user_id)

    # ===== ТЕСТ =====

    if user_id in user_test_state:

        state = user_test_state[user_id]

        if state == "start":

            if "да" in text:

                user_test_state[user_id] = 0
                user_test_answers[user_id] = []

                bot.send_message(message.chat.id, test_questions[0])
                return

            else:
                bot.send_message(message.chat.id, "Ладно… но ты многое упустил 😏")
                del user_test_state[user_id]
                return

        if isinstance(state, int):

            if text not in ["a", "b", "а", "б"]:
                bot.send_message(message.chat.id, "Ответь A или B")
                return

            user_test_answers[user_id].append(text)

            next_q = state + 1

            if next_q < len(test_questions):

                user_test_state[user_id] = next_q
                bot.send_message(message.chat.id, test_questions[next_q])
                return

            else:

                answers = user_test_answers[user_id]

                a_count = sum(1 for x in answers if x in ["a", "а"])
                b_count = len(answers) - a_count

                if a_count > b_count:

                    result = (
                        "Ты человек, который сильно привязывается.\n"
                        "Ты чувствуешь глубже, чем показываешь.\n"
                        "Иногда боишься потерять тех, кто тебе дорог."
                    )

                else:

                    result = (
                        "Ты держишь дистанцию.\n"
                        "Не открываешься сразу и защищаешь себя.\n"
                        "Но внутри ты глубже, чем кажешься."
                    )

                bot.send_message(message.chat.id, result)

                bot.send_message(
                    message.chat.id,
                    "Отправь это тому, кто думает, что знает тебя 😈"
                )

                del user_test_state[user_id]
                del user_test_answers[user_id]

                return

    # ===== ОБЫЧНЫЙ ЧАТ =====

    try:

        answer = get_openrouter_answer(user_id, text)

        bot.send_message(message.chat.id, answer)

        if sheet:
            sheet.append_row([
                str(datetime.now(KZ_TIMEZONE)),
                str(user_id),
                str(message.from_user.first_name or ""),
                str(message.from_user.username or ""),
                str(text),
                str(answer),
                "chat"
            ])

    except Exception as e:

        print("Ошибка:", e)

        bot.send_message(
            message.chat.id,
            "Ой... что-то пошло не так 😔"
        )

# ================= АВТОСООБЩЕНИЯ =================

def auto_messages():
    while True:

        now = datetime.now(KZ_TIMEZONE)
        hour = now.strftime("%H:%M")

        if hour.startswith("09:00"):
            for user in known_users:
                try:
                    bot.send_message(user, "Доброе утро ☀️ Я уже думаю о тебе ❤️")
                except:
                    pass
            time.sleep(60)

        if hour.startswith("22:00"):
            for user in known_users:
                try:
                    bot.send_message(user, "Спокойной ночи 🌙")
                except:
                    pass
            time.sleep(60)

        time.sleep(20)

threading.Thread(target=auto_messages, daemon=True).start()

# ================= WEBHOOK =================

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def index():
    return "Bot is running", 200

# ================= ЗАПУСК =================

if __name__ == "__main__":

    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}/webhook/{TOKEN}")

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)