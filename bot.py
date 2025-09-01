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

# Хранилище диалогов (в оперативке)
user_sessions = {}

def get_openrouter_answer(user_id, user_message):
    """
    Отправляем историю диалога пользователя в OpenRouter и получаем ответ
    """
    if user_id not in user_sessions:
        user_sessions[user_id] = [
            {
                "role": "system",
                "content": (
                    "Ты флирт-бот 💋. Отвечай всегда на русском языке, тепло, игриво и слегка романтично. "
                    "Будь понимающим, добавляй нотку флирта и эмоций, но избегай пошлости. "
                    "Ответы должны быть короткими, естественными, будто пишет человек. "
                    "Можешь использовать смайлики для настроения ❤️😉✨."
                )
            }
        ]
    
    # Добавляем сообщение пользователя
    user_sessions[user_id].append({"role": "user", "content": user_message})

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://github.com/Arman",
        "X-Title": "ZarinaBot",
        "Content-Type": "application/json"
    }
    data = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": user_sessions[user_id],
        "max_tokens": 500,
        "temperature": 0.8,
        "top_p": 0.95
    }

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    result = response.json()
    answer = result["choices"][0]["message"]["content"].strip()

    # Добавляем ответ бота в историю
    user_sessions[user_id].append({"role": "assistant", "content": answer})

    return answer

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Привет! Давай пообщаемся 😉")

@bot.message_handler(commands=["donate"])
def donate(message):
    keyboard = types.InlineKeyboardMarkup()
    kaspi_number = "+77089871147"
    pay_button = types.InlineKeyboardButton(
        "💳 Оплатить через Kaspi",
        url=f"https://kaspi.kz/pay/{kaspi_number}"
    )
    keyboard.add(pay_button)

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
        # Получаем ответ с учетом истории
        answer = get_openrouter_answer(user.id, question)

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
        bot.send_message(message.chat.id, f"Ошибка: {str(e)}")

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