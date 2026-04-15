import os
import time
import random
import threading
import pytz
import gspread
from datetime import datetime
from flask import Flask, request
from telebot import telebot, types
from oauth2client.service_account import ServiceAccountCredentials
from praytimes import PrayTimes

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("BOT_TOKEN")
CREDENTIALS_FILE = "/etc/secrets/credentials.json"
RENDER_URL = "https://arman-c2rh.onrender.com"

# Инициализация калькулятора (метод MWL - один из мировых стандартов)
calc = PrayTimes('MWL') 

# ================= БАЗА ДАННЫХ (GOOGLE SHEETS) =================

scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def get_sheet():
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        return client.open("Zarina Answers").sheet1
    except Exception as e:
        print(f"Ошибка Google Sheets: {e}")
        return None

# ================= КОНТЕНТ (ДУА И ИСТОРИИ) =================

DUAS = [
    "«О Аллах, я прошу у Тебя полезного знания, благого удела и такого дела, которое будет принято»",
    "«О Аллах, помоги мне поминать Тебя, благодарить Тебя и должным образом поклоняться Тебе»"
]

STORIES = [
    "История о щедрости: Пророк ﷺ никогда не отказывал тому, кто просил его о чем-то ради Аллаха.",
    "История о терпении: Когда Пророк ﷺ пришел в Таиф, он проявил величайшее милосердие к тем, кто его обидел."
]

# ================= ЛОГИКА БОТА =================

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

def kb_main():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("📍 Обновить локацию", request_location=True))
    kb.add("📊 Моя статистика")
    return kb

def kb_done(prayer_name):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Выполнено", callback_data=f"done_{prayer_name}"))
    return kb

@bot.message_handler(commands=["start"])
def start(m):
    bot.send_message(
        m.chat.id, 
        "Ассаляму алейкум! Я буду присылать уведомления о намазе и полезные напоминания.\n\nПожалуйста, отправьте свою локацию:",
        reply_markup=kb_main()
    )

@bot.message_handler(content_types=["location"])
def handle_location(m):
    uid = str(m.from_user.id)
    lat, lon = m.location.latitude, m.location.longitude
    
    sheet = get_sheet()
    if not sheet: return

    cell = sheet.find(uid)
    if cell:
        sheet.update_cell(cell.row, 2, lat)
        sheet.update_cell(cell.row, 3, lon)
    else:
        # User ID, Lat, Lon, Count, LastDate, LastPrayer
        sheet.append_row([uid, lat, lon, 0, "", ""])

    bot.send_message(m.chat.id, "Локация сохранена! Теперь вы будете получать уведомления.", reply_markup=kb_main())

# ================= ФОНОВАЯ ПРОВЕРКА =================

def notification_loop():
    while True:
        try:
            sheet = get_sheet()
            if not sheet: 
                time.sleep(60)
                continue
                
            users = sheet.get_all_records()
            tz = pytz.timezone("Asia/Almaty")
            now_dt = datetime.now(tz)
            now_str = now_dt.strftime("%H:%M")
            today_str = now_dt.strftime("%d.%m.%Y")

            for user in users:
                uid = user['User ID']
                # Считаем время намаза локально
                times = calc.getTimes(now_dt.date(), (float(user['Lat']), float(user['Lon'])), 5)
                
                # Проверка 5 намазов
                for p_name in ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']:
                    p_time = times[p_name]
                    
                    if p_time == now_str:
                        # Проверка, чтобы не дублировать уведомление
                        if str(user.get('LastDate')) != today_str or user.get('LastPrayer') != p_name:
                            bot.send_message(uid, f"📢 Время намаза {p_name.capitalize()}: {p_time}", reply_markup=kb_done(p_name))
                            
                            # Обновляем в таблице факт уведомления
                            cell = sheet.find(str(uid))
                            sheet.update_cell(cell.row, 5, today_str)
                            sheet.update_cell(cell.row, 6, p_name)

                # Утренние/вечерние рассылки (например, 09:00 и 21:00)
                if now_str == "09:00":
                    bot.send_message(uid, f"🌅 Утреннее напоминание:\n{random.choice(DUAS)}")
                if now_str == "21:00":
                    bot.send_message(uid, f"🌙 Вечерняя история:\n{random.choice(STORIES)}")

        except Exception as e:
            print(f"Ошибка в цикле: {e}")
        
        time.sleep(45) # Проверка чуть чаще минуты для точности

threading.Thread(target=notification_loop, daemon=True).start()

# ================= КНОПКА "ВЫПОЛНЕНО" =================

@bot.callback_query_handler(func=lambda call: call.data.startswith("done_"))
def prayer_done(call):
    uid = str(call.from_user.id)
    sheet = get_sheet()
    cell = sheet.find(uid)
    
    if cell:
        current_count = int(sheet.cell(cell.row, 4).value or 0)
        sheet.update_cell(cell.row, 4, current_count + 1)
        bot.answer_callback_query(call.id, "МашаАллах! Принято.")
        bot.edit_message_text(f"{call.message.text}\n\n✅ Отмечено как выполненное!", call.message.chat.id, call.message.message_id)

# ================= ЗАПУСК ЧЕРЕЗ FLASK =================

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    update = types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return "ok", 200

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}/webhook/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
