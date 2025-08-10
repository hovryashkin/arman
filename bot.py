import os
import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import time

# === Настройки ===
TOKEN = os.getenv("BOT_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
CREDENTIALS_FILE = "/etc/secrets/credentials.json"
HF_MODEL = "gpt2"  # Заменяй на нужную модель Hugging Face

# === Авторизация Google Sheets ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open("Zarina Answers").sheet1

# === Telegram Bot ===
bot = telebot.TeleBot(TOKEN)

headers = {
    "Authorization": f"Bearer {HF_API_TOKEN}",
    "Content-Type": "application/json"
}

def ask_ai_question(chat_id):
    prompt = "Придумай один интересный вопрос для викторины."

    data = {
        "inputs": prompt,
        "options": {"wait_for_model": True}
    }

    try:
        response = requests.post(
            f"https://api-inference.huggingface.co/models/{HF_MODEL}",
            headers=headers,
            json=data
        )

        if response.status_code == 503:
            # Модель ещё загружается — подождать и повторить
            time.sleep(3)
            return ask_ai_question(chat_id)

        if response.status_code != 200:
            bot.send_message(chat_id, "Ошибка при получении вопроса от ИИ.")
            return

        output = response.json()
        if isinstance(output, dict) and output.get("error"):
            bot.send_message(chat_id, "Ошибка модели: " + output["error"])
            return

        question = output[0]["generated_text"] if isinstance(output, list) else str(output)
        bot.send_message(chat_id, question)
        sheet.append_row([chat_id, question, "вопрос"])
    except Exception as e:
        bot.send_message(chat_id, "Произошла ошибка: " + str(e))

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Привет! Я буду задавать тебе вопросы.")
    ask_ai_question(message.chat.id)

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
