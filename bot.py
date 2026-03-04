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

RENDER_URL = "https://YOUR_RENDER_URL.onrender.com"  # <-- ЗАМЕНИ НА СВОЙ URL

# ================= GOOGLE SHEETS =================

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    CREDENTIALS_FILE, scope
)
client = gspread.authorize(creds)
sheet = client.open("Zarina Answers").sheet1

# ================= TELEGRAM BOT =================

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Память сообщений
user_histories = defaultdict(lambda: deque(maxlen=10))


# ================= OPENROUTER =================

def get_openrouter_answer(user_id, user_question):
    user_histories[user_id].append(
        {"role": "user", "content": user_question}
    )

    messages = [
        {
            "role": "system",
            "content": "Ты флирт-бот. Отвечай коротко, тепло и романтично на русском."
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
            "temperature": 0.8
        }
    )

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.text)

    response.raise_for_status()

    answer = response.json()["choices"][0]["message"]["content"]

    user_histories[user_id].append(
        {"role": "assistant", "content": answer}
    )

    return answer


# ================= КОМАНДЫ =================

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        "Привет солнце ❤️ Напиши мне что-нибудь..."
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


@bot.message_handler(func=lambda m: True)
def handle_message(message):
    user = message.from_user
    question = message.text

    try:
        answer = get_openrouter_answer(user.id, question)

        bot.send_message(message.chat.id, answer)

        try:
            sheet.append_row([
                user.id,
                user.first_name or "",
                user.username or "",
                question,
                answer
            ])
        except Exception as e:
            print("Ошибка записи в таблицу:", e)

    except Exception as e:
        print("Ошибка OpenRouter:", e)
        bot.send_message(
            message.chat.id,
            f"Ошибка при получении ответа: {str(e)}"
        )


# ================= WEBHOOK =================
@app.route("/set_webhook")
def set_webhook():
    bot.remove_webhook()
    bot.set_webhook(
        url=f"https://arman-c2rh.onrender.com/webhook/{TOKEN}"
    )
    return "Webhook set!"


@app.route("/")
def index():
    return "Bot is running", 200


# ================= ЗАПУСК =================

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}/webhook/{TOKEN}")

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)