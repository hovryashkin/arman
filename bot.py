import os
import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import json

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

# Многострочный промт с описанием, какие вопросы задаёт ИИ
system_message = (
    "Ты — доброжелательный и понимающий собеседник, который задаёт девушке по имени Зарина вопросы, чтобы лучше узнать её. "
    "Вопросы должны быть разнообразными — о семье, творчестве, интересах, с юмором, философские и душевные. "
    "Зарина — человек с биополярным расстройством, поэтому твои вопросы должны быть лёгкими, поддерживающими, "
    "чтобы немного поднимать ей настроение, дарить позитив и тепло. "
    "Задавай вопросы так, чтобы Зарина чувствовала себя комфортно и интересно, избегай тяжёлых или тревожных тем."
)

def ask_openrouter_question():
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {"role": "system", "content": system_message}
        ],
        "max_tokens": 100,
        "temperature": 0.7,
        "top_p": 0.95
    }
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    result = response.json()
    question = result["choices"][0]["message"]["content"]
    return question

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Привет! Я буду задавать тебе вопросы.")
    ask_ai_question(message.chat.id)

def ask_ai_question(chat_id):
    try:
        question = ask_openrouter_question()
        bot.send_message(chat_id, question)
        # Сохраняем в таблицу вопрос с пустым ответом (пока ответ не получен)
        sheet.append_row([chat_id, question, ""])
    except Exception as e:
        bot.send_message(chat_id, f"Ошибка: {str(e)}")

@bot.message_handler(func=lambda m: True)
def handle_answer(message):
    # Получаем последний вопрос из таблицы, чтобы связать с ответом
    records = sheet.get_all_records()
    last_question = ""
    for row in reversed(records):
        if row["Ответ"] == "":
            last_question = row["Вопрос"]
            break
    # Записываем ответ вместе с вопросом
    sheet.append_row([message.chat.id, last_question, message.text])
    bot.send_message(message.chat.id, "Ответ записан! Вот следующий вопрос:")
    ask_ai_question(message.chat.id)

# === Flask Webhook ===
if __name__ == "__main__":
    from flask import Flask, request
    app = Flask(__name__)

    @app.route(f"/webhook/{TOKEN}", methods=["POST"])
    def webhook():
        json_str = request.get_data().decode("UTF-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "OK", 200

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
