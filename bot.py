import os
import telebot
from telebot import types
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
from flask import Flask, request
import qrcode
from io import BytesIO

# === Настройки ===
TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CREDENTIALS_FILE = "/etc/secrets/credentials.json"

# === Google Sheets авторизация ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open("Zarina Answers").sheet1

# === Telegram Bot ===
bot = telebot.TeleBot(TOKEN)

def get_openrouter_answer(user_question):
    """
    Отправляем вопрос пользователя в OpenRouter и получаем ответ
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://github.com/Arman",  # можно любой URL
        "X-Title": "ZarinaBot",
        "Content-Type": "application/json"
    }
    data = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты флирт-бот 💋. Отвечай всегда на русском языке, тепло, игриво и слегка романтично. "
                    "Будь понимающим, добавляй нотку флирта и эмоций, но избегай пошлости. "
                    "Ответы должны быть короткими, естественными, будто пишет человек. "
                    "Можешь использовать смайлики для настроения ❤️😉✨."
                )
            },
            {
                "role": "user",
                "content": user_question
            }
        ],
        "max_tokens": 3000,
        "temperature": 0.8,
        "top_p": 0.95
    }

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    result = response.json()
    return result["choices"][0]["message"]["content"].strip()

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Привет! Задай мне любой вопрос 💬")

@bot.message_handler(commands=["donate"])
def donate(message):
    keyboard = types.InlineKeyboardMarkup()
    kaspi_number = "+77089871147"   # 👉 вставь сюда свой номер Kaspi
    pay_button = types.InlineKeyboardButton(
        "💳 Оплатить через Kaspi",
        url=f"https://kaspi.kz/pay/{kaspi_number}"
    )
    keyboard.add(pay_button)

    # Генерация QR-кода
    qr_data = f"https://kaspi.kz/pay/{kaspi_number}"
    qr_img = qrcode.make(qr_data)

    bio = BytesIO()
    qr_img.save(bio, format="PNG")
    bio.seek(0)

    bot.send_photo(
        message.chat.id,
        photo=bio,
        caption=f"Спасибо за поддержку ❤️\n\nKaspi Gold: `{kaspi_number}`",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: True)
def handle_question(message):
    user = message.from_user
    question = message.text

    try:
        # Получаем ответ от OpenRouter
        answer = get_openrouter_answer(question)

        # Отправляем пользователю
        bot.send_message(message.chat.id, answer)

        # Сохраняем в таблицу
        sheet.append_row([
            user.id,
            user.first_name or "",
            user.username or "",
            question,
            answer
        ])

    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка при получении ответа: {str(e)}")

# === Flask Webhook ===
app = Flask(__name__)

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)