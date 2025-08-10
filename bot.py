import os
import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

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

def ask_openrouter_question():
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "mistralai/mistral-7b-instruct",
        "messages": [
            {"role": "system", "content": "Придумай один интересный вопрос для викторины."}
        ],
        "max_tokens": 100,
        "temperature": 0.7,
        "top_p": 0.95
    }
    response = requests.post(url, headers=headers, json=data)

    print("OpenRouter status:", response.status_code)
    print("OpenRouter response:", response.text)

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
        sheet.append_row([chat_id, question, "вопрос"])
    except Exception as e:
        bot.send_message(chat_id, f"Ошибка при получении вопроса от ИИ: {str(e)}")

@bot.message_handler(func=lambda m: True)
def handle_answer(message):
    sheet.append_row([message.chat.id, message.text, "ответ"])
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
