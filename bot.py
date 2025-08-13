import os
import telebot
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request

# ==== НАСТРОЙКИ ====
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ==== GOOGLE SHEETS ====
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("/etc/secrets/credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

# ==== ФУНКЦИЯ GPT ====
def generate_question():
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "meta-llama/llama-3-70b-instruct",
        "messages": [
            {
                "role": "system",
                "content": "Ты задаешь только один короткий, личный и осмысленный вопрос на русском языке. Без пояснений, без списка, без викторины."
            },
            {
                "role": "user",
                "content": "Задай один вопрос."
            }
        ],
        "temperature": 0.7
    }

    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    try:
        return result["choices"][0]["message"]["content"].strip()
    except Exception:
        return "Что для тебя сейчас самое важное?"

# ==== ЛОГИКА БОТА ====
@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Привет, давай начнём!")
    question = generate_question()
    bot.send_message(message.chat.id, question)

@bot.message_handler(func=lambda message: True)
def save_answer(message):
    # Сохраняем ответ в Google Таблицу
    sheet.append_row([message.from_user.first_name, message.text])

    # Задаём следующий вопрос
    question = generate_question()
    bot.send_message(message.chat.id, question)

# ==== WEBHOOK ====
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "Бот работает!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
