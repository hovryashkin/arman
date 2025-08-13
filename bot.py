import os
import telebot
import gspread
from flask import Flask, request
from openai import OpenAI
from datetime import datetime

# === Конфигурация ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY")
CREDENTIALS_PATH = "/etc/secrets/credentials.json"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)
client = OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")

# === Подключение к Google Sheets ===
gc = gspread.service_account(filename=CREDENTIALS_PATH)
sheet = gc.open_by_key(SPREADSHEET_KEY).sheet1

# === Генерация вопроса ===
def ask_openrouter_question():
    prompt = (
        "Ты — доброжелательный собеседник, который общается с девушкой по имени Зарина. "
        "Задай ровно один короткий, интересный и позитивный вопрос на русском языке, "
        "чтобы узнать что-то личное или забавное. Без пояснений, только сам вопрос."
    )
    response = client.chat.completions.create(
        model="meta-llama/llama3-70b-instruct",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
        max_tokens=50
    )
    return response.choices[0].message.content.strip()

# === Обработка входящих сообщений ===
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    text = message.text

    # Записываем в Google Sheets
    sheet.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username, text])

    # Генерируем новый вопрос
    question = ask_openrouter_question()
    bot.send_message(user_id, question)

# === Webhook ===
@app.route(f"/webhook/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "Бот запущен и работает!", 200

# === Запуск и установка webhook ===
if __name__ == "__main__":
    WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook/{TELEGRAM_TOKEN}"
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    app.run(host="0.0.0.0", port=10000)
