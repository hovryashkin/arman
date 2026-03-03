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
    user_histories[user_id].append({"role": "user", "content": user_question})

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
            "messages": messages
        }
    )

    print(response.status_code)
    print(response.text)

    response.raise_for_status()

    answer = response.json()["choices"][0]["message"]["content"]

    user_histories[user_id].append({"role": "assistant", "content": answer})

    return answer

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Привет солнце! Рад что ты написала❤️")
@bot.message_handler(commands=["donate"])
def donate(message):
    keyboard = types.InlineKeyboardMarkup()
    kaspi_number = "77089871147"   # номер телефона, привязанный к Kaspi
    amount = 1000                  # сумма по умолчанию (можно менять)
    kaspi_link = f"https://kaspi.kz/pay/{kaspi_number}?amount={amount}"

    pay_button = types.InlineKeyboardButton("💳 Оплатить через Kaspi", url=kaspi_link)
    keyboard.add(pay_button)

    # Генерация QR-кода
    qr_img = qrcode.make(kaspi_link)
    bio = BytesIO()
    qr_img.save(bio, format="PNG")
    bio.seek(0)

    bot.send_photo(
        message.chat.id,
        photo=bio,
        caption=(
            f"Спасибо за поддержку ❤️\n\n"
            f"Kaspi Gold (по номеру): `{kaspi_number}`\n"
            f"Сумма: {amount} ₸"
        ),
        reply_markup=keyboard,
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