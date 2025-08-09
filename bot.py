import os
import telebot
import time

# Получаем токен из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

# Список заготовленных вопросов
questions = [
    "Как у тебя настроение?",
    "Что ты сегодня ел?",
    "Какая твоя любимая песня?",
    "Какой фильм тебе нравится?",
    "О чём ты сейчас думаешь?"
]

# Отправляем вопросы по команде /start
@bot.message_handler(commands=['start'])
def send_questions(message):
    for q in questions:
        bot.send_message(message.chat.id, q)
        time.sleep(2)  # задержка между вопросами

# Запускаем бота
if __name__ == "__main__":
    bot.polling(none_stop=True)
