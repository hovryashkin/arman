import os
import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
from flask import Flask, request

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

# Словарь для хранения последнего вопроса
last_questions = {}

def ask_openrouter_question():
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты доброжелательный и понимающий собеседник, твоя главная задача расположить к себе. "
                    "Ты задаёшь ровно один короткий и интересный вопрос, чтобы лучше узнать собеседника. "
                    "Задавай уникальные вопросы на новые темы, не повторяй по смыслу предыдущие. "
                    "Отвечай только одним вопросом без списка, нумерации или лишних слов. "
                    "Вопросы должны быть только на русском языке и без ошибок."
                )
            }
        ],
        "max_tokens": 1000,
        "temperature": 0.8,
        "top_p": 0.95
    }
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    result = response.json()
    question = result["choices"][0]["message"]["content"].strip()
    return question.split("\n")[0]

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Привет! Хочу задать тебе пару вопросов")
    ask_ai_question(message.chat.id)

def ask_ai_question(chat_id):
    try:
        question = ask_openrouter_question()
        bot.send_message(chat_id, question)
        # Сохраняем только в память, не в таблицу
        last_questions[chat_id] = question
    except Exception as e:
        bot.send_message(chat_id, f"Ошибка при получении вопроса от ИИ: {str(e)}")

@bot.message_handler(func=lambda m: True)
def handle_answer(message):
    question = last_questions.get(message.chat.id, "Вопрос неизвестен")
    answer = message.text
    user = message.from_user

    # Сохраняем сразу вопрос+ответ в таблицу
    sheet.append_row([
        user.id,
        user.first_name or "",
        user.username or "",
        question,
        answer
    ])

    bot.send_message(message.chat.id, "Ответ записан! Вот следующий вопрос:")
    ask_ai_question(message.chat.id)

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
