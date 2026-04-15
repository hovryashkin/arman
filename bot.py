import os
import telebot
from telebot import types
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
from flask import Flask, request
from datetime import datetime, timedelta
import threading
import time
import pytz

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("BOT_TOKEN")
CREDENTIALS_FILE = "/etc/secrets/credentials.json"
RENDER_URL = "https://arman-c2rh.onrender.com"

# API для времени намаза (Метод 2 - ISNA, можно менять)
PRAYER_API_URL = "https://api.aladhan.com/v1/timings"

# ================= GOOGLE SHEETS (БАЗА ДАННЫХ) =================

scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
sheet = None

def get_sheet():
    global sheet
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open("Zarina Answers").sheet1
        return sheet
    except Exception as e:
        print("Ошибка Google Sheets:", e)
        return None

# ================= КОНТЕНТ =================

MORNING_CONTENT = [
    "Дуа утром: 'Аллахумма бика асбахна...' (О Аллах, благодаря Тебе мы дожили до утра).",
    "История: Посланник Аллаха ﷺ всегда начинал день с поминания Всевышнего."
]

EVENING_CONTENT = [
    "Дуа вечером: 'Аллахумма бика амсайна...' (О Аллах, благодаря Тебе мы дожили до вечера).",
    "История: Пророк ﷺ советовал читать последние суры Корана перед сном для защиты."
]

# ================= ЛОГИКА ВРЕМЕНИ =================

def get_prayer_times(lat, lon):
    try:
        # Получаем данные на сегодня
        resp = requests.get(f"{PRAYER_API_URL}?latitude={lat}&longitude={lon}&method=2").json()
        return resp['data']['timings']
    except:
        return None

# ================= TELEGRAM BOT =================

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

def kb_location():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(types.KeyboardButton("📍 Отправить местоположение", request_location=True))
    return kb

def kb_done(prayer_name):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Выполнено", callback_data=f"done_{prayer_name}"))
    return kb

@bot.message_handler(commands=["start"])
def start(m):
    bot.send_message(
        m.chat.id,
        "Ассаляму алейкум! Я буду помогать вам соблюдать время намаза.\n"
        "Для начала мне нужно знать вашу локацию, чтобы рассчитать точное время.",
        reply_markup=kb_location()
    )

@bot.message_handler(content_types=["location"])
def handle_location(m):
    uid = str(m.from_user.id)
    lat = m.location.latitude
    lon = m.location.longitude
    
    # Сохраняем в таблицу (ID, Lat, Lon, TZ, Count, Last, Date)
    s = get_sheet()
    cell = s.find(uid)
    
    if cell:
        s.update_cell(cell.row, 2, lat)
        s.update_cell(cell.row, 3, lon)
    else:
        s.append_row([uid, lat, lon, "Asia/Almaty", 0, "", ""])

    times = get_prayer_times(lat, lon)
    if times:
        text = "🕌 Расписание на сегодня:\n"
        for name, t in times.items():
            if name in ['Fajr', 'Dhuhr', 'Asr', 'Maghrib', 'Isha']:
                text += f"**{name}**: {t}\n"
        bot.send_message(m.chat.id, text, parse_mode="Markdown")
        bot.send_message(m.chat.id, "Я буду присылать уведомления. Не забудьте отмечать выполненные!")

# ================= ОБРАБОТКА НАЖАТИЯ «ВЫПОЛНЕНО» =================

@bot.callback_query_handler(func=lambda call: call.data.startswith("done_"))
def prayer_done(call):
    uid = str(call.from_user.id)
    s = get_sheet()
    cell = s.find(uid)
    
    if cell:
        current_count = int(s.cell(cell.row, 5).value or 0)
        new_count = current_count + 1
        s.update_cell(cell.row, 5, new_count)
        
        bot.answer_callback_query(call.id, "МашаАллах! Засчитано.")
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"{call.message.text}\n\n✅ Отмечено! Всего выполнено: {new_count}"
        )

# ================= ФОНОВЫЕ УВЕДОМЛЕНИЯ =================

def notification_loop():
    while True:
        try:
            s = get_sheet()
            all_users = s.get_all_records()
            now = datetime.now(pytz.timezone("Asia/Almaty")).strftime("%H:%M")
            date_today = datetime.now(pytz.timezone("Asia/Almaty")).strftime("%Y-%m-%d")

            for user in all_users:
                uid = user['User ID']
                lat, lon = user['Lat'], user['Lon']
                
                times = get_prayer_times(lat, lon)
                if not times: continue

                # Проверка времени намаза
                for p_name in ['Fajr', 'Dhuhr', 'Asr', 'Maghrib', 'Isha']:
                    if times[p_name] == now:
                        # Чтобы не спамить в ту же минуту, проверяем дату/название
                        if user['Last Prayer Name'] != p_name or user['Last Date'] != date_today:
                            bot.send_message(uid, f"📢 Время намаза: {p_name} ({times[p_name]})", reply_markup=kb_done(p_name))
                            
                            # Обновляем статус в таблице, что уведомили
                            cell = s.find(str(uid))
                            s.update_cell(cell.row, 6, p_name)
                            s.update_cell(cell.row, 7, date_today)

                # Утренние/Вечерние истории (например в 08:00 и 20:00)
                if now == "08:00":
                    bot.send_message(uid, f"🌅 {random.choice(MORNING_CONTENT)}")
                if now == "20:00":
                    bot.send_message(uid, f"🌙 {random.choice(EVENING_CONTENT)}")

        except Exception as e:
            print("Ошибка в цикле уведомлений:", e)
        
        time.sleep(60) # Проверка каждую минуту

# Запуск потока уведомлений
threading.Thread(target=notification_loop, daemon=True).start()

# ================= WEBHOOK И ЗАПУСК =================

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return "ok"

@app.route("/")
def index(): return "Бот работает"

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}/webhook/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
