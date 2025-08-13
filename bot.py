import os
import telebot
from flask import Flask, request
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import json

# --- Секреты ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GOOGLE_SHEETS_CREDS = os.getenv("GOOGLE_SHEETS_CREDS")  # JSON как строка
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")  # ID твоей таблицы

# --- Настройка бота ---
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- Подключение к Google Sheets ---
creds_dict = json.loads(GOOGLE_SHEETS_CREDS)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

# --- Генерация вопроса ---
def generate_question():
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": "meta-llama/llama-3-70b-instruct",
        "messages": [
            {"role": "system", "content": "Ты задаёшь только один короткий личный вопрос на русском языке, без пояснений."},
            {"role": "user", "content": "Задай вопрос."}
        ]
    }
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
    response = r.json()
    return response["choices"][0]["message"]["content"].strip()

# --- Обработка сообщений ---
@bot.message_handler(commands=['start'])
def start(message):
    question = generate_question()
    bot.send_message(message.chat.id, question)

@bot.message_handler(func=lambda msg: True)
def save_answer(message):
    sheet.append_row([message.from_user.first_name, message.text])
    question = generate_question()
    bot.send_message(message.chat.id, question)

# --- Вебхук ---
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/", methods=['GET'])
def index():
    return "Bot is running!", 200

if __name__ == "__main__":
    # Устанавливаем вебхук при запуске
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
