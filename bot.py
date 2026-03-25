import os
import telebot
from telebot import types
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
from flask import Flask, request
import qrcode
from io import BytesIO
from collections import defaultdict, deque
from datetime import datetime
import threading
import time
import random
import pytz

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CREDENTIALS_FILE = "/etc/secrets/credentials.json"

RENDER_URL = "https://arman-c2rh.onrender.com"
KZ_TIMEZONE = pytz.timezone("Asia/Almaty")

# ================= GOOGLE SHEETS =================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

sheet = None

try:
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        CREDENTIALS_FILE, scope
    )
    client = gspread.authorize(creds)
    sheet = client.open("Zarina Answers").sheet1
except Exception as e:
    print("Sheets error:", e)

# ================= TELEGRAM =================

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

user_histories = defaultdict(lambda: deque(maxlen=10))
known_users = set()

# ===== СОСТОЯНИЯ =====

user_test_state = {}
user_test_answers = {}
user_relation_mode = set()

# ===== КНОПКИ =====

def kb_ab():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("A", "B")
    return kb

def kb_yesno():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Да", "Нет")
    return kb

def kb_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔁 Пройти ещё раз", "💔 Отношения")
    return kb

# ===== ВОПРОСЫ =====

test_questions = [
    "Ты чаще:\nA) привязываешься\nB) держишь дистанцию",
    "Если человек тебе дорог:\nA) показываешь\nB) скрываешь",
    "Ты бы простил измену?\nA) да\nB) нет",
    "Ты больше:\nA) логика\nB) эмоции",
    "Боишься потерять людей?\nA) да\nB) нет",
    "Ты чаще страдаешь молча?\nA) да\nB) нет"
]

relation_questions = [
    "В отношениях ты:\nA) любишь сильнее\nB) держишь баланс",
    "Если человек отдаляется:\nA) догоняешь\nB) отпускаешь",
    "Ты ревнивый?\nA) да\nB) нет",
    "Проверяешь человека?\nA) да\nB) нет",
    "Боишься быть брошенным?\nA) да\nB) нет"
]

reaction_phrases = [
    "Хм… неожиданно 👀",
    "Ты не такой простой 😏",
    "Интересный выбор...",
    "Я начинаю тебя понимать",
    "Это многое говорит о тебе"
]

# ================= OPENROUTER =================

def ai_answer(uid, text):

    user_histories[uid].append({"role": "user", "content": text})

    messages = [{
        "role": "system",
        "content": (
            "Ты дерзкий, тёплый и немного флиртующий. "
            "Иногда ссылайся на прошлые сообщения. "
            "Отвечай коротко (1-2 предложения)."
        )
    }] + list(user_histories[uid])

    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
        json={"model": "meta-llama/llama-3-8b-instruct", "messages": messages}
    )

    ans = r.json()["choices"][0]["message"]["content"]
    user_histories[uid].append({"role": "assistant", "content": ans})
    return ans

# ================= START =================

@bot.message_handler(commands=["start"])
def start(m):

    uid = m.from_user.id
    known_users.add(uid)

    bot.send_message(
        m.chat.id,
        "Я задам тебе 6 вопросов\nи скажу кто ты на самом деле 😏\n\nГотов?",
        reply_markup=kb_yesno()
    )

    user_test_state[uid] = "start"

# ================= ЛОГИКА =================

@bot.message_handler(func=lambda m: True)
def msg(m):

    uid = m.from_user.id
    text = (m.text or "").lower()

    # ===== МЕНЮ =====

    if text == "🔁 пройти ещё раз":
        user_test_state[uid] = "start"
        bot.send_message(m.chat.id, "Ещё раз? 😏", reply_markup=kb_yesno())
        return

    if text == "💔 отношения":
        user_relation_mode.add(uid)
        user_test_state[uid] = 0
        user_test_answers[uid] = []
        bot.send_message(m.chat.id, "Окей… давай честно 😏")
        bot.send_message(m.chat.id, relation_questions[0], reply_markup=kb_ab())
        return

    # ===== ТЕСТ =====

    if uid in user_test_state:

        state = user_test_state[uid]

        if state == "start":

            if text == "да":
                user_test_state[uid] = 0
                user_test_answers[uid] = []
                bot.send_message(m.chat.id, test_questions[0], reply_markup=kb_ab())
            else:
                bot.send_message(m.chat.id, "Ладно… зря 😏")
                del user_test_state[uid]
            return

        if isinstance(state, int):

            if text not in ["a", "b", "а", "б"]:
                return

            user_test_answers[uid].append(text)

            next_q = state + 1
            qs = relation_questions if uid in user_relation_mode else test_questions

            if next_q < len(qs):

                user_test_state[uid] = next_q

                bot.send_message(m.chat.id, random.choice(reaction_phrases))
                time.sleep(0.7)

                bot.send_message(m.chat.id, qs[next_q], reply_markup=kb_ab())
                return

            # ===== ВАУ ЭФФЕКТ =====

            bot.send_chat_action(m.chat.id, "typing")
            time.sleep(1.5)
            bot.send_message(m.chat.id, "Интересно...")
            time.sleep(1)
            bot.send_chat_action(m.chat.id, "typing")
            time.sleep(1.5)

            answers = user_test_answers[uid]
            a = sum(1 for x in answers if x in ["a","а"])
            b = len(answers)-a
            score = a-b

            percent = int((a / len(answers)) * 100)

            # ===== РЕЗУЛЬТАТ =====

            if uid in user_relation_mode:

                if a > b:
                    res = f"Ты любишь сильнее.\nНа {percent}% ты эмоциональный.\nТы отдаёшь больше, чем получаешь."
                else:
                    res = f"Ты осторожен.\nНа {percent}% ты закрытый.\nТы защищаешь себя."

                user_relation_mode.remove(uid)

            else:

                if score >= 3:
                    res = f"Ты очень эмоциональный.\nНа {percent}% ты про чувства.\nТы настоящий."
                elif score >= 1:
                    res = f"Ты баланс.\nНа {percent}% ты про эмоции.\nТы не поверхностный."
                elif score <= -3:
                    res = f"Ты закрытый.\nНа {100-percent}% ты про контроль.\nТы защищаешь себя."
                else:
                    res = f"Ты сложный.\nНа {percent}% тебя сложно понять.\nНо ты цепляешь."

            bot.send_message(m.chat.id, res)

            bot.send_message(
                m.chat.id,
                "Отправь это тому, кто думает что знает тебя 😈"
            )

            bot.send_message(
                m.chat.id,
                "Что дальше?",
                reply_markup=kb_menu()
            )

            del user_test_state[uid]
            del user_test_answers[uid]
            return

    # ===== AI ЧАТ =====

    try:
        answer = ai_answer(uid, text)
        bot.send_message(m.chat.id, answer)
    except:
        bot.send_message(m.chat.id, "Ошибка 😔")

# ================= WEBHOOK =================

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return "ok"

@app.route("/")
def index():
    return "ok"

# ================= RUN =================

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}/webhook/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))