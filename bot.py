import os
import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

# === Настройки ===
TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")  # токен Hugging Face
CREDENTIALS_FILE = "/etc/secrets/credentials.json"

# === Авторизация Google Sheets ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open("Zarina Answers").sheet1

# === Telegram Bot ===
bot = telebot.TeleBot(TOKEN)

HF_API_URL = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3"
HEADERS = {"Authorization": f"Bearer {HF_TOKEN}"}

def generate_question():
    prompt = "Придумай один интересный вопрос для девушки."
    response = requests.post(
        HF_API_URL,
        headers=HEADERS,
        json={"inputs": prompt}
    )
    if response.status_code == 200:
        result = response.json()
        if isinstance(result, list) and "generated_text" in result[0]:
            return result[0]["generated_text"]
        elif isinstance(result, dict) and "generated_text" in result:
            return result["generated_text"]
        else:
            return "Не удалось сгенерировать вопрос."
    else:
        return f"Ошибка API: {response.status_code}"

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Привет! Я буду задавать тебе вопросы.")
    ask_ai_question(message.chat.id)

def ask_ai_question(chat_id):
    question = generate_question()
    bot.send_message(chat_id, question)
    sheet.append_row([chat_id, question, "вопрос"])

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
