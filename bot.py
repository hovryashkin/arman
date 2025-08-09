import os
import telebot
import gspread
import requests
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request

# === Настройки ===
TOKEN = os.getenv("BOT_TOKEN")
HF_API_KEY = os.getenv("HF_API_KEY")  # токен Hugging Face
CREDENTIALS_FILE = "/etc/secrets/credentials.json"
MODEL_ID = "gpt2"  # можно поменять на другую модель

# === Авторизация Google Sheets ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open("Zarina Answers").sheet1

# === Telegram Bot ===
bot = telebot.TeleBot(TOKEN)

# Функция для запроса к Hugging Face
def hf_generate(prompt):
    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    payload = {"inputs": prompt, "parameters": {"max_new_tokens": 50}}
    response = requests.post(f"https://api-inference.huggingface.co/models/{MODEL_ID}", 
                             headers=headers, json=payload)
    result = response.json()
    if isinstance(result, dict) and "error" in result:
        return "Ошибка: модель ещё загружается, попробуйте позже."
    return result[0]["generated_text"]

@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Привет! Я буду задавать тебе вопросы.")
    ask_ai_question(message.chat.id)

def ask_ai_question(chat_id):
    prompt = "Придумай один интересный вопрос для викторины."
    question = hf_generate(prompt)
    bot.send_message(chat_id, question)
    sheet.append_row([chat_id, question, "вопрос"])

@bot.message_handler(func=lambda m: True)
def handle_answer(message):
    sheet.append_row([message.chat.id, message.text, "ответ"])
    bot.send_message(message.chat.id, "Ответ записан! Вот следующий вопрос:")
    ask_ai_question(message.chat.id)

# === Flask Webhook ===
app = Flask(__name__)

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
