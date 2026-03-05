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

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CREDENTIALS_FILE = "/etc/secrets/credentials.json"

RENDER_URL = "https://arman-c2rh.onrender.com"

# ================= GOOGLE SHEETS =================

def connect_sheet():
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        creds = ServiceAccountCredentials.from_json_keyfile_name(
            CREDENTIALS_FILE, scope
        )

        client = gspread.authorize(creds)
        sheet = client.open("Zarina Answers").sheet1

        print("Google Sheets подключен")

        return sheet

    except Exception as e:
        print("Ошибка Google Sheets:", e)
        return None


sheet = connect_sheet()

# ================= TELEGRAM =================

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# память диалога
user_histories = defaultdict(lambda: deque(maxlen=20))

# ================= OPENROUTER =================

def get_openrouter_answer(user_id, user_question):

    user_histories[user_id].append(
        {"role": "user", "content": user_question}
    )

    messages = [
        {
            "role": "system",
            "content": (
                "Ты романтичный флиртующий парень 💋 "
                "Отвечай коротко (1-2 предложения). "
                "Будь игривым, теплым, немного загадочным. "
                "Используй иногда ❤️😉✨"
            )
        }
    ] + list(user_histories[user_id])

    try:

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
                "max_tokens": 200
            },
            timeout=30
        )

        print("OPENROUTER STATUS:", response.status_code)

        response.raise_for_status()

        answer = response.json()["choices"][0]["message"]["content"]

        user_histories[user_id].append(
            {"role": "assistant", "content": answer}
        )

        return answer

    except Exception as e:
        print("OpenRouter ошибка:", e)
        return "Хмм… я задумался о тебе и немного завис ❤️ Напиши ещё раз."


# ================= КОМАНДЫ =================

@bot.message_handler(commands=["start"])
def start(message):

    bot.send_message(
        message.chat.id,
        "Привет ❤️ Я скучал… Напиши мне что-нибудь 😉"
    )


@bot.message_handler(commands=["donate"])
def donate(message):

    keyboard = types.InlineKeyboardMarkup()

    kaspi_number = "77089871147"
    amount = 1000

    kaspi_link = f"https://kaspi.kz/pay/{kaspi_number}?amount={amount}"

    pay_button = types.InlineKeyboardButton(
        "💳 Поддержать через Kaspi",
        url=kaspi_link
    )

    keyboard.add(pay_button)

    qr = qrcode.make(kaspi_link)

    bio = BytesIO()
    qr.save(bio, format="PNG")
    bio.seek(0)

    bot.send_photo(
        message.chat.id,
        photo=bio,
        caption=f"Спасибо за поддержку ❤️\nKaspi: {kaspi_number}",
        reply_markup=keyboard
    )


# ================= СООБЩЕНИЯ =================

@bot.message_handler(func=lambda m: True)
def handle_message(message):

    user = message.from_user
    text = message.text

    answer = get_openrouter_answer(user.id, text)

    bot.send_message(message.chat.id, answer)

    # запись в таблицу
    try:

        if sheet:

            sheet.append_row([
                user.id,
                user.first_name or "",
                user.username or "",
                text,
                answer
            ])

            print("Ответ записан в таблицу")

    except Exception as e:

        print("Ошибка записи в Google Sheets:", e)


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

    print("Запуск бота...")

    bot.remove_webhook()

    bot.set_webhook(url=f"{RENDER_URL}/webhook/{TOKEN}")

    port = int(os.environ.get("PORT", 5000))

    app.run(host="0.0.0.0", port=port)