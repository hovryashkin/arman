import os
import telebot
import gspread
from datetime import datetime
from openai import OpenAI

# === Настройки ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CREDENTIALS_PATH = "/etc/secrets/credentials.json"
SPREADSHEET_NAME = "Zarina Answers"

bot = telebot.TeleBot(BOT_TOKEN)
client = OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")

# Подключаем Google Sheets
gc = gspread.service_account(filename=CREDENTIALS_PATH)
sheet = gc.open(SPREADSHEET_NAME).sheet1

# Храним последний вопрос для каждого пользователя
last_question = {}

# Генерация вопроса через ИИ
def get_ai_question():
    prompt = "Задай один короткий и личный вопрос на русском языке девушке."
    response = client.chat.completions.create(
        model="mistralai/mistral-7b-instruct",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

# Команда /question
@bot.message_handler(commands=["question"])
def ask_question(message):
    q = get_ai_question()
    last_question[message.chat.id] = q
    bot.send_message(message.chat.id, q)

# Ответы на вопросы
@bot.message_handler(func=lambda m: m.chat.id in last_question)
def save_answer(message):
    question = last_question.pop(message.chat.id)
    answer = message.text
    sheet.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), question, answer])
    bot.send_message(message.chat.id, "Ответ записан! ✅")

# Запуск бота
if __name__ == "__main__":
    bot.polling(none_stop=True)
