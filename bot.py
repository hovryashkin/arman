import os
import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from transformers import pipeline

# === Настройки ===
TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")  # токен Hugging Face
CREDENTIALS_FILE = "/etc/secrets/credentials.json"

# === Авторизация Google Sheets ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open("Zarina Answers").sheet1

# === Авторизация Hugging Face ===
generator = pipeline(
    "text-generation",
    model="gpt2",
    use_auth_token=HF_TOKEN
)

# === Telegram Bot ===
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Привет! Я буду задавать тебе вопросы.")
    ask_ai_question(message.chat.id)

def ask_ai_question(chat_id):
    prompt = "Придумай один интересный вопрос для девушки."
    completion = generator(prompt, max_length=50, num_return_sequences=1)
    question = completion[0]["generated_text"].strip()
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
