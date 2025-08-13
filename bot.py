import os
import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
from flask import Flask, request

# === Настройки ===
TOKEN = os.getenv("BOT_TOKEN")  # Токен бота
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")  # Ключ OpenRouter
CREDENTIALS_FILE = "/etc/secrets/credentials.json"  # Путь к credentials.json на Render
PORT = int(os.environ.get("PORT", 5000))  # Порт для Render

# === Google Sheets авторизация ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open("Zarina Answers").sheet1

# === Telegram Bot ===
bot = telebot.TeleBot(TOKEN)
last_questions = {}  # Словарь для хранения последнего вопроса

# === Flask для Render ===
app = Flask(__name__)

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
                    "Ты — злой и плохой собеседник, который общается с девушкой по имени Диана. "
                    "Ты задаёшь ровно один короткий и интересный вопрос, чтобы её унизить. "
                    "Отвечай только одним вопросом без списка, нумерации или лишних слов."
                )
            }
        ],
        "max_tokens": 50,
        "temperature": 0.8,
        "top_p": 0.95
    }
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    result = response.json()
    question = result["choices"][0]["message"]["content"].strip()
    question = question.split("\n")[0]
    return question

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Привет, Диана ❤️ Я буду задавать тебе вопросы.")
    ask_ai_question(message.chat.id)

def ask_ai_question(chat_id):
    try:
        question = ask_openrouter_question()
        bot.send_message(chat_id, question)
        sheet.append_row([chat_id, question, "вопрос"])
        last_questions[chat_id] = question
    except Exception as e:
        bot.send_message(chat_id, f"Ошибка: {e}")

@bot.message_handler(func=lambda m: True)
def handle_answer(message):
    chat_id = message.chat.id
    answer = message.text
    if chat_id in last_questions:
        sheet.append_row([chat_id, last_questions[chat_id], answer])
    ask_ai_question(chat_id)

# === Webhook для Render ===
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "Бот работает!", 200

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"{os.getenv('RENDER_EXTERNAL_URL')}/{TOKEN}")
    app.run(host="0.0.0.0", port=PORT)
