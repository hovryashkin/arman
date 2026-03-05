import os
import telebot
from telebot import types
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
from flask import Flask, request
from collections import defaultdict, deque
from datetime import datetime
import threading
import time

# ================= НАСТРОЙКИ =================
TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CREDENTIALS_FILE = "/etc/secrets/credentials.json"
RENDER_URL = "https://arman-c2rh.onrender.com"
SPREADSHEET_NAME = "Zarina Answers"
QUESTION_INTERVAL = 5  # секунд между вопросами

# ================= GOOGLE SHEETS =================
def connect_sheet():
    try:
        scope = ["https://spreadsheets.google.com/feeds",
                 "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open(SPREADSHEET_NAME).sheet1
        print("✅ Google Sheets подключен")
        return sheet
    except Exception as e:
        print("❌ Ошибка Google Sheets:", e)
        return None

sheet = connect_sheet()

def write_to_sheet(user, question, answer):
    if not sheet:
        print("⚠️ Таблица не инициализирована, запись пропущена")
        return False
    try:
        next_row = len(sheet.get_all_values()) + 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.update(f"A{next_row}", user.id)
        sheet.update(f"B{next_row}", user.first_name or "")
        sheet.update(f"C{next_row}", user.username or "")
        sheet.update(f"D{next_row}", question)
        sheet.update(f"E{next_row}", answer)
        sheet.update(f"F{next_row}", timestamp)
        print(f"✅ Записано: user_id={user.id}, question='{question}', answer='{answer}'")
        return True
    except Exception as e:
        print("❌ Ошибка записи в Google Sheets:", e)
        return False

# ================= TELEGRAM =================
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
user_histories = defaultdict(lambda: deque(maxlen=20))

# ================= OPENROUTER =================
def get_openrouter_answer(user_id, user_question):
    user_histories[user_id].append({"role": "user", "content": user_question})
    messages = [
        {
            "role": "system",
            "content": (
                "Ты романтичный флиртующий парень 💋 "
                "Отвечай коротко (1-2 предложения). "
                "Будь игривым, теплым, немного загадочным. "
                "Используй иногда ❤️😉✨"
            )
        }
    ] + list(user_histories[user_id])

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "meta-llama/llama-3-8b-instruct",
                "messages": messages,
                "temperature": 1.0,
                "max_tokens": 200
            },
            timeout=30
        )
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"].strip()
        user_histories[user_id].append({"role": "assistant", "content": answer})
        return answer
    except Exception as e:
        print("❌ OpenRouter ошибка:", e)
        return "Хмм… я задумался о тебе ❤️ Напиши ещё раз."

# ================= АВТОМАТИЧЕСКИЕ ВОПРОСЫ =================
def ask_questions_loop(chat_id, user):
    while True:
        question = get_openrouter_answer(user.id, "Сгенерируй короткий личный вопрос для девушки на русском")
        msg = bot.send_message(chat_id, question)
        # ждем ответ от пользователя
        bot.register_next_step_handler(msg, handle_autoreply, question, user)
        time.sleep(QUESTION_INTERVAL)  # пауза между вопросами

def handle_autoreply(message, question, user):
    answer = message.text
    bot.send_message(message.chat.id, "Спасибо за ответ ❤️")
    write_to_sheet(user, question, answer)

# ================= КОМАНДЫ =================
@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Привет ❤️ Я буду задавать тебе вопросы один за другим 😉")
    user = message.from_user
    # запускаем отдельный поток для бесконечного цикла вопросов
    threading.Thread(target=ask_questions_loop, args=(message.chat.id, user), daemon=True).start()

# ================= WEBHOOK =================
@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def index():
    return "Bot is running 🟢", 200

# ================= ЗАПУСК =================
if __name__ == "__main__":
    print("Запуск бота...")
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}/webhook/{TOKEN}")
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)