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

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CREDENTIALS_FILE = "/etc/secrets/credentials.json"

RENDER_URL = "https://arman-c2rh.onrender.com"

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

# ================= ВОПРОСЫ ДНЕВНИКА =================

diary_questions = [
    "Как прошёл твой день? 😊",
    "Что сегодня сделало тебя счастливой? ❤️",
    "О чём ты сегодня много думала?",
    "Что сегодня было самым приятным моментом?",
    "Что тебя сегодня немного расстроило?"
]

# ================= OPENROUTER =================

def get_openrouter_answer(user_id, user_question):

    user_histories[user_id].append(
        {"role": "user", "content": user_question}
    )

    messages = [
        {
            "role": "system",
            "content": (
                "Ты — заботливый, нежный и теплый человек "
                "Отвечай коротко исключительно на русском языке (1-3 предложения), "
                "тепло, слегка флиртуй. Без пошлости. Можно использовать ❤️😉✨"
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
            "temperature": 1.0,
            "top_p": 0.95
        }
    )

    response.raise_for_status()

    answer = response.json()["choices"][0]["message"]["content"]

    user_histories[user_id].append(
        {"role": "assistant", "content": answer}
    )

    return answer

# ================= КОМАНДЫ =================

@bot.message_handler(commands=["start"])
def start(message):

    known_users.add(message.from_user.id)

    bot.send_message(
        message.chat.id,
        "Привет ❤️ Я скучал... Напиши мне что-нибудь 😉"
    )

@bot.message_handler(commands=["donate"])
def donate(message):

    keyboard = types.InlineKeyboardMarkup()

    kaspi_number = "77089871147"
    amount = 1000

    kaspi_link = f"https://kaspi.kz/pay/{kaspi_number}?amount={amount}"

    pay_button = types.InlineKeyboardButton(
        "💳 Оплатить через Kaspi",
        url=kaspi_link
    )

    keyboard.add(pay_button)

    qr_img = qrcode.make(kaspi_link)

    bio = BytesIO()
    qr_img.save(bio, format="PNG")
    bio.seek(0)

    bot.send_photo(
        message.chat.id,
        photo=bio,
        caption=(
            f"Спасибо за поддержку ❤️\n\n"
            f"Kaspi: `{kaspi_number}`\n"
            f"Сумма: {amount} ₸"
        ),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# ================= СООБЩЕНИЯ =================

@bot.message_handler(func=lambda m: True)
def handle_message(message):

    user = message.from_user
    question = message.text or "нет текста"

    known_users.add(user.id)

    diary_mode = False
    if user.id in user_waiting_diary:
        diary_mode = True
        user_waiting_diary.remove(user.id)

    try:

        answer = get_openrouter_answer(user.id, question)

        bot.send_message(message.chat.id, answer)

        if sheet:

            try:

                sheet.append_row([
                    str(datetime.now()),
                    str(user.id),
                    str(user.first_name or ""),
                    str(user.username or ""),
                    str(question),
                    str(answer),
                    "diary" if diary_mode else "chat"
                ])

                print("Ответ записан в таблицу")

            except Exception as e:

                print("Google Sheets error:", e)

    except Exception as e:

        print("OpenRouter error:", e)

        bot.send_message(
            message.chat.id,
            "Ой... что-то пошло не так 😔 Попробуй ещё раз."
        )

# ================= АВТОСООБЩЕНИЯ =================

def auto_messages():

    while True:

        now = datetime.now().strftime("%H:%M")

        if now == "09:00":

            for user in known_users:

                try:
                    bot.send_message(
                        user,
                        "Доброе утро ☀️ Я только проснулся и уже думаю о тебе ❤️"
                    )
                except:
                    pass

            time.sleep(60)

        if now == "20:00":

            for user in known_users:

                try:

                    q = random.choice(diary_questions)

                    bot.send_message(user, "💌 Вопрос дня:\n\n" + q)

                    user_waiting_diary.add(user)

                except:
                    pass

            time.sleep(60)

        if now == "22:00":

            for user in known_users:

                try:
                    bot.send_message(
                        user,
                        "Спокойной ночи 🌙 Надеюсь ты сегодня улыбалась..."
                    )
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