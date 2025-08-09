
import os
import telebot
import gspread
from datetime import datetime
from openai import OpenAI
from flask import Flask, request

# === Переменные окружения ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
APP_URL = os.getenv("APP_URL")  # https://твой-проект.onrender.com
CREDENTIALS_PATH = "/etc/secrets/credentials.json"
SPREADSHEET_NAME = "Zarina Answers"

# === Инициализация бота и API ===
bot = telebot.TeleBot(BOT_TOKEN)
client = OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")

# Подключаем Google Sheets
gc = gspread.service_account(filename=CREDENTIALS_PATH)
sheet = gc.open(SPREADSHEET_NAME).sheet1

# Flask-приложение для webhook
app = Flask(__name__)

# Сохраняем последний вопрос для каждого пользователя
last_question = {}

# Функция генерации вопроса через ИИ
def get_ai_question():
    prompt = "Задай один короткий и личный вопрос на русском языке девушке."
    response = client.chat.completions.create(
        model="mistralai/mistral-7b-instruct",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

# Команда /question — прислать вопрос
@bot.message_handler(commands=["question"])
def ask_question(message):
    q = get_ai_question()
    last_question[message.chat.id] = q
    bot.send_message(message.chat.id, q)

# Обработка ответа на вопрос
@bot.message_handler(func=lambda m: m.chat.id in last_question)
def save_answer(message):
    question = last_question.pop(message.chat.id)
    answer = message.text
    sheet.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), question, answer])
    bot.send_message(message.chat.id, "Ответ записан! ✅")

# Маршрут для получения обновлений от Telegram
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

# Главная страница (для проверки)
@app.route("/", methods=["GET"])
def index():
    return "Бот работает!", 200

if __name__ == "__main__":
    import requests
    # Убираем старый webhook и ставим новый
    bot.remove_webhook()
    bot.set_webhook(url=f"{APP_URL}/{BOT_TOKEN}")
    # Запускаем Flask-сервер
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
