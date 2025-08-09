import os
import telebot
import openai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import random

# Настройки токенов из переменных окружения
TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

bot = telebot.TeleBot(TOKEN)
openai.api_key = OPENAI_API_KEY

# --- Настройка Google Sheets ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = os.environ.get("GOOGLE_SHEETS_CREDS")  # JSON ключ как строка
if creds_json:
    import json
    creds_dict = json.loads(creds_json)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open("Ответы бота").sheet1
else:
    sheet = None

# --- Функция генерации вопроса через GPT ---
def generate_question():
    prompt = "Сгенерируй один интересный вопрос для пользователя по любым темам."
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "system", "content": prompt}]
    )
    return response.choices[0].message["content"]

# --- Логика бота ---
@bot.message_handler(commands=["start"])
def start(message):
    question = generate_question()
    bot.send_message(message.chat.id, f"Привет! Вот твой вопрос:\n\n{question}")

@bot.message_handler(func=lambda msg: True)
def handle_answer(message):
    user_answer = message.text

    # Сохраняем ответ в Google Таблицу
    if sheet:
        sheet.append_row([message.from_user.username or "", user_answer])

    # Отправляем следующий вопрос
    next_question = generate_question()
    bot.send_message(message.chat.id, f"Спасибо за ответ!\n\nСледующий вопрос:\n{next_question}")

# Flask для Webhook
from flask import Flask, request
app = Flask(__name__)

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def home():
    return "Бот работает!", 200

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
