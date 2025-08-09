import os
import requests
import telebot
from flask import Flask, request

TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
APP_URL = os.getenv("APP_URL")  # https://твой-проект.onrender.com

bot = telebot.TeleBot(TOKEN)
server = Flask(__name__)

# ===== AI функция через OpenRouter =====
def get_ai_question():
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {"role": "user", "content": "Задай один короткий и дружелюбный вопрос на русском языке для собеседника."}
        ]
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()

# ===== Команда /start =====
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Привет! Я буду задавать тебе вопросы 🤖")
    ask_question(message.chat.id)

# ===== Задаем вопрос =====
def ask_question(chat_id):
    try:
        question = get_ai_question()
        bot.send_message(chat_id, question)
    except Exception as e:
        bot.send_message(chat_id, f"Ошибка при генерации вопроса: {e}")

# ===== Ответ на текст =====
@bot.message_handler(func=lambda message: True)
def handle_answer(message):
    # Тут позже можно добавить отправку в Google Таблицу
    bot.send_message(message.chat.id, "Спасибо за ответ! Вот еще вопрос:")
    ask_question(message.chat.id)

# ===== Webhook =====
@server.route('/' + TOKEN, methods=['POST'])
def getMessage():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "!", 200

@server.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=APP_URL + TOKEN)
    return "!", 200

if __name__ == "__main__":
    server.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
