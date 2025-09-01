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

# Храним историю сообщений: user_id -> очередь (до 10 сообщений)
user_histories = defaultdict(lambda: deque(maxlen=10))

def get_openrouter_answer(user_id, user_question):
    """
    Отправляем вопрос пользователя в OpenRouter с учётом контекста
    """
    # Добавляем новое сообщение в историю
    user_histories[user_id].append({"role": "user", "content": user_question})

    # Формируем массив сообщений (системное + история)
    messages = [
        {
            "role": "system",
            "content": (
                "Ты флирт-бот 💋. Отвечай всегда на русском языке, тепло, игриво и слегка романтично. "
                "Будь понимающим, добавляй нотку флирта и эмоций, но избегай пошлости. "
                "Ответы должны быть короткими, естественными, будто пишет человек. "
                "Можешь использовать смайлики для настроения ❤️😉✨."
            )
        }
    ] + list(user_histories[user_id])

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://github.com/Arman",
        "X-Title": "ZarinaBot",
        "Content-Type": "application/json"
    }
    data = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.8,
        "top_p": 0.95
    }

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    result = response.json()
    answer = result["choices"][0]["message"]["content"].strip()

    # Сохраняем ответ в историю
    user_histories[user_id].append({"role": "assistant", "content": answer})

    return answer

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Привет! Задай мне любой вопрос 💬")
@bot.message_handler(commands=["donate"])
def donate(message):
    keyboard = types.InlineKeyboardMarkup()

    kaspi_card = "4400430385306623"  # твоя карта
    amounts = [1000, 2000, 5000]     # суммы доната

    # Генерируем кнопки для выбора суммы
    for amount in amounts:
        btn = types.InlineKeyboardButton(f"💳 {amount}₸", callback_data=f"donate_{amount}")
        keyboard.add(btn)

    bot.send_message(
        message.chat.id,
        "Выбери сумму для доната ❤️",
        reply_markup=keyboard
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("donate_"))
def process_donate(call):
    amount = call.data.split("_")[1]
    kaspi_card = "4400430385306623"
    link = f"https://kaspi.kz/pay/{kaspi_card}?amount={amount}"

    # Генерация QR-кода
    qr_img = qrcode.make(link)
    bio = BytesIO()
    qr_img.save(bio, format="PNG")
    bio.seek(0)

    bot.send_photo(
        call.message.chat.id,
        photo=bio,
        caption=f"Спасибо за поддержку ❤️\n\nКарта: `{kaspi_card}`\nСумма: {amount}₸",
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: True)
def handle_question(message):
    user = message.from_user
    question = message.text

    try:
        # Получаем ответ от OpenRouter с памятью
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