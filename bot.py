import os
import telebot
from flask import Flask, request

# Настройки
TOKEN = os.environ.get("TOKEN")  # Токен бота (установи в Render в Environment Variables)
APP_URL = os.environ.get("APP_URL")  # https://твой-проект.onrender.com

bot = telebot.TeleBot(TOKEN)
server = Flask(__name__)

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start_message(message):
    bot.send_message(message.chat.id, "Привет! Я бот, который всегда онлайн на Render 😊")

# Обработчик текстовых сообщений
@bot.message_handler(func=lambda m: True)
def echo_all(message):
    bot.send_message(message.chat.id, f"Ты написал: {message.text}")

# Webhook маршрут
@server.route(f"/webhook/{TOKEN}", methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "ok", 200

# Главная страница (для проверки)
@server.route("/")
def index():
    return "Бот работает!", 200

if __name__ == "__main__":
    # Ставим webhook при запуске
    bot.remove_webhook()
    bot.set_webhook(url=f"{APP_URL}/webhook/{TOKEN}")

    # Flask слушает порт Render
    port = int(os.environ.get("PORT", 5000))
    server.run(host="0.0.0.0", port=port)

