import os
import re
import pytz
import time
import threading
from datetime import datetime
from flask import Flask, request
from telebot import telebot, types
import psycopg2
from psycopg2.extras import RealDictCursor

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("BOT_TOKEN")
RENDER_URL = os.getenv("RENDER_URL", "https://your-app.onrender.com")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================= БАЗА ДАННЫХ =================

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    name TEXT,
                    age INTEGER,
                    gender TEXT,
                    looking_for TEXT,
                    city TEXT,
                    interests TEXT,
                    bio TEXT,
                    photo_id TEXT,
                    active BOOLEAN DEFAULT TRUE,
                    created TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS swipes (
                    id SERIAL PRIMARY KEY,
                    from_user TEXT,
                    to_user TEXT,
                    action TEXT,
                    created TEXT,
                    UNIQUE(from_user, to_user)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS matches (
                    id SERIAL PRIMARY KEY,
                    user1 TEXT,
                    user2 TEXT,
                    created TEXT,
                    UNIQUE(user1, user2)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    match_id INTEGER,
                    from_user TEXT,
                    text TEXT,
                    created TEXT
                )
            """)
        conn.commit()

init_db()

# ================= СОСТОЯНИЯ =================

user_state = {}

INTERESTS_LIST = [
    "🎵 Музыка", "🎮 Игры", "📚 Книги", "🏋️ Спорт",
    "✈️ Путешествия", "🍕 Еда", "🎬 Кино", "💻 Технологии",
    "🎨 Искусство", "🐾 Животные", "🌿 Природа", "💃 Танцы"
]

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def now_str():
    return datetime.now(pytz.timezone("UTC")).strftime("%d.%m.%Y %H:%M")

def get_profile(uid):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM profiles WHERE user_id=%s", (str(uid),))
            return cur.fetchone()

def get_match_id(uid1, uid2):
    u1, u2 = sorted([str(uid1), str(uid2)])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM matches WHERE user1=%s AND user2=%s", (u1, u2))
            row = cur.fetchone()
            return row["id"] if row else None

def get_next_profile(uid):
    """Возвращает следующий профиль для просмотра с учётом фильтров"""
    profile = get_profile(uid)
    if not profile:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Исключаем уже просмотренных и себя
            cur.execute("""
                SELECT * FROM profiles
                WHERE user_id != %s
                AND active = TRUE
                AND user_id NOT IN (
                    SELECT to_user FROM swipes WHERE from_user=%s
                )
                AND (looking_for = %s OR looking_for = 'all')
                ORDER BY RANDOM()
                LIMIT 1
            """, (str(uid), str(uid), profile["gender"]))
            return cur.fetchone()

def format_profile(p, show_contacts=False):
    interests = p["interests"] or ""
    text = (
        f"👤 *{p['name']}, {p['age']}*\n"
        f"📍 {p['city']}\n"
        f"{'💙' if p['gender'] == 'male' else '💗'} {'Мужчина' if p['gender'] == 'male' else 'Женщина'}\n"
    )
    if interests:
        text += f"✨ {interests}\n"
    if p["bio"]:
        text += f"\n_{p['bio']}_"
    return text

# ================= КЛАВИАТУРЫ =================

def kb_main(uid):
    profile = get_profile(uid)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if profile:
        kb.add(
            types.KeyboardButton("👀 Смотреть анкеты"),
            types.KeyboardButton("💌 Мои матчи"),
            types.KeyboardButton("📝 Моя анкета"),
            types.KeyboardButton("⚙️ Настройки")
        )
    else:
        kb.add(types.KeyboardButton("📝 Создать анкету"))
    return kb

def kb_swipe():
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("❌ Пропустить", callback_data="swipe_no"),
        types.InlineKeyboardButton("❤️ Лайк", callback_data="swipe_yes"),
        types.InlineKeyboardButton("⭐ Суперлайк", callback_data="swipe_super")
    )
    return kb

def kb_gender():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("👨 Мужчина", callback_data="gender_male"),
        types.InlineKeyboardButton("👩 Женщина", callback_data="gender_female")
    )
    return kb

def kb_looking_for():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("👨 Мужчин", callback_data="lf_male"),
        types.InlineKeyboardButton("👩 Женщин", callback_data="lf_female"),
        types.InlineKeyboardButton("👥 Всех", callback_data="lf_all")
    )
    return kb

def kb_interests(selected):
    kb = types.InlineKeyboardMarkup(row_width=2)
    for interest in INTERESTS_LIST:
        mark = "✅ " if interest in selected else ""
        kb.add(types.InlineKeyboardButton(f"{mark}{interest}", callback_data=f"int_{interest}"))
    kb.add(types.InlineKeyboardButton("➡️ Готово", callback_data="int_done"))
    return kb

def kb_cancel():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Отмена"))
    return kb

# ================= СТАРТ =================

@bot.message_handler(commands=["start"])
def start(m):
    uid = m.from_user.id
    profile = get_profile(uid)
    if profile:
        bot.send_message(m.chat.id,
            f"👋 С возвращением, {profile['name']}!",
            reply_markup=kb_main(uid)
        )
    else:
        bot.send_message(m.chat.id,
            "👋 Добро пожаловать в dating-бот!\n\n"
            "Здесь ты найдёшь интересных людей со всего мира.\n\n"
            "Давай создадим твою анкету 👇",
            reply_markup=kb_main(uid)
        )

# ================= СОЗДАНИЕ АНКЕТЫ =================

@bot.message_handler(func=lambda m: m.text in ("📝 Создать анкету", "📝 Моя анкета"))
def create_profile(m):
    uid = m.from_user.id
    profile = get_profile(uid)
    if profile and m.text == "📝 Моя анкета":
        # Показываем анкету
        text = format_profile(profile)
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit_profile"),
            types.InlineKeyboardButton("🔴 Скрыть анкету" if profile["active"] else "🟢 Показать анкету",
                callback_data="toggle_active")
        )
        if profile["photo_id"]:
            bot.send_photo(m.chat.id, profile["photo_id"], caption=text, parse_mode="Markdown", reply_markup=kb)
        else:
            bot.send_message(m.chat.id, text, parse_mode="Markdown", reply_markup=kb)
        return

    user_state[uid] = {"action": "reg_name"}
    bot.send_message(m.chat.id, "Как тебя зовут? Введи имя:", reply_markup=kb_cancel())

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "reg_name")
def reg_name(m):
    uid = m.from_user.id
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main(uid))
        return
    if len(m.text) > 30:
        bot.send_message(m.chat.id, "Имя слишком длинное. Введи покороче:")
        return
    user_state[uid] = {"action": "reg_age", "name": m.text}
    bot.send_message(m.chat.id, "Сколько тебе лет?", reply_markup=kb_cancel())

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "reg_age")
def reg_age(m):
    uid = m.from_user.id
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main(uid))
        return
    try:
        age = int(m.text)
        if age < 18 or age > 99:
            bot.send_message(m.chat.id, "Возраст должен быть от 18 до 99.")
            return
        user_state[uid] = {**user_state[uid], "action": "reg_gender", "age": age}
        bot.send_message(m.chat.id, "Выбери свой пол:", reply_markup=kb_gender())
    except:
        bot.send_message(m.chat.id, "Введи число, например: 25")

@bot.callback_query_handler(func=lambda c: c.data.startswith("gender_"))
def reg_gender(call):
    uid = call.from_user.id
    if user_state.get(uid, {}).get("action") != "reg_gender":
        return
    gender = call.data[7:]
    user_state[uid] = {**user_state[uid], "action": "reg_looking_for", "gender": gender}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Кого ищешь?", reply_markup=kb_looking_for())

@bot.callback_query_handler(func=lambda c: c.data.startswith("lf_"))
def reg_looking_for(call):
    uid = call.from_user.id
    if user_state.get(uid, {}).get("action") != "reg_looking_for":
        return
    lf = call.data[3:]
    user_state[uid] = {**user_state[uid], "action": "reg_city", "looking_for": lf}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Из какого ты города?", reply_markup=kb_cancel())

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "reg_city")
def reg_city(m):
    uid = m.from_user.id
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main(uid))
        return
    user_state[uid] = {**user_state[uid], "action": "reg_interests", "city": m.text, "interests": []}
    bot.send_message(m.chat.id, "Выбери интересы (можно несколько):",
        reply_markup=kb_interests([]))

@bot.callback_query_handler(func=lambda c: c.data.startswith("int_") and user_state.get(c.from_user.id, {}).get("action") == "reg_interests")
def reg_interests(call):
    uid = call.from_user.id
    val = call.data[4:]
    if val == "done":
        user_state[uid] = {**user_state[uid], "action": "reg_bio"}
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Расскажи о себе пару слов (или нажми /skip):", reply_markup=kb_cancel())
        return
    selected = user_state[uid].get("interests", [])
    if val in selected:
        selected.remove(val)
    else:
        if len(selected) < 5:
            selected.append(val)
        else:
            bot.answer_callback_query(call.id, "Максимум 5 интересов!")
            return
    user_state[uid]["interests"] = selected
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=kb_interests(selected))
    except:
        pass

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "reg_bio")
def reg_bio(m):
    uid = m.from_user.id
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main(uid))
        return
    bio = "" if m.text == "/skip" else m.text[:300]
    user_state[uid] = {**user_state[uid], "action": "reg_photo", "bio": bio}
    bot.send_message(m.chat.id, "Отправь своё фото (или /skip):", reply_markup=kb_cancel())

@bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "reg_photo")
def reg_photo(m):
    uid = m.from_user.id
    photo_id = m.photo[-1].file_id
    user_state[uid] = {**user_state[uid], "photo_id": photo_id}
    finish_registration(m.chat.id, uid)

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "reg_photo")
def reg_photo_skip(m):
    uid = m.from_user.id
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main(uid))
        return
    finish_registration(m.chat.id, uid)

def finish_registration(chat_id, uid):
    state = user_state.pop(uid, {})
    interests_str = ", ".join(state.get("interests", []))
    username = bot.get_chat(uid).username or ""

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO profiles (user_id, username, name, age, gender, looking_for, city, interests, bio, photo_id, active, created)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    name=EXCLUDED.name, age=EXCLUDED.age, gender=EXCLUDED.gender,
                    looking_for=EXCLUDED.looking_for, city=EXCLUDED.city,
                    interests=EXCLUDED.interests, bio=EXCLUDED.bio,
                    photo_id=EXCLUDED.photo_id, active=TRUE
            """, (
                str(uid), username, state["name"], state["age"], state["gender"],
                state["looking_for"], state["city"], interests_str,
                state.get("bio", ""), state.get("photo_id", ""), now_str()
            ))
        conn.commit()

    bot.send_message(chat_id,
        f"🎉 Анкета создана!\n\n"
        f"👤 {state['name']}, {state['age']}\n"
        f"📍 {state['city']}\n\n"
        "Теперь ты можешь смотреть анкеты!",
        reply_markup=kb_main(uid)
    )

# ================= СВАЙПЫ =================

@bot.message_handler(func=lambda m: m.text == "👀 Смотреть анкеты")
def browse_profiles(m):
    uid = m.from_user.id
    profile = get_profile(uid)
    if not profile:
        bot.send_message(m.chat.id, "Сначала создай анкету!", reply_markup=kb_main(uid))
        return
    show_next_profile(m.chat.id, uid)

def show_next_profile(chat_id, uid):
    candidate = get_next_profile(uid)
    if not candidate:
        bot.send_message(chat_id,
            "😔 Анкеты закончились!\nПопробуй позже — появятся новые люди.",
            reply_markup=kb_main(uid)
        )
        return

    text = format_profile(candidate)
    # Сохраняем кто сейчас показывается
    user_state[uid] = {"viewing": str(candidate["user_id"])}

    if candidate["photo_id"]:
        bot.send_photo(chat_id, candidate["photo_id"], caption=text, parse_mode="Markdown", reply_markup=kb_swipe())
    else:
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=kb_swipe())

@bot.callback_query_handler(func=lambda c: c.data in ("swipe_yes", "swipe_no", "swipe_super"))
def handle_swipe(call):
    uid = call.from_user.id
    state = user_state.get(uid, {})
    to_uid = state.get("viewing")

    if not to_uid:
        bot.answer_callback_query(call.id, "Анкета уже не актуальна.")
        return

    action = call.data[6:]  # yes / no / super
    bot.answer_callback_query(call.id)

    # Сохраняем свайп
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""
                    INSERT INTO swipes (from_user, to_user, action, created)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (from_user, to_user) DO NOTHING
                """, (str(uid), to_uid, action, now_str()))
            except:
                pass
        conn.commit()

    # Проверяем взаимный лайк
    if action in ("yes", "super"):
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM swipes
                    WHERE from_user=%s AND to_user=%s AND action IN ('yes', 'super')
                """, (to_uid, str(uid)))
                mutual = cur.fetchone()

        if mutual:
            # МАТЧ!
            u1, u2 = sorted([str(uid), to_uid])
            with get_conn() as conn:
                with conn.cursor() as cur:
                    try:
                        cur.execute("""
                            INSERT INTO matches (user1, user2, created)
                            VALUES (%s, %s, %s)
                            ON CONFLICT DO NOTHING
                        """, (u1, u2, now_str()))
                    except:
                        pass
                conn.commit()

            # Уведомляем обоих
            their_profile = get_profile(to_uid)
            my_profile = get_profile(uid)

            match_kb = types.InlineKeyboardMarkup()
            match_kb.add(types.InlineKeyboardButton("💌 Написать", callback_data=f"chat_{to_uid}"))

            bot.send_message(uid,
                f"🎉 *Это матч!*\n\nВам понравился {their_profile['name']}!",
                parse_mode="Markdown", reply_markup=match_kb
            )

            match_kb2 = types.InlineKeyboardMarkup()
            match_kb2.add(types.InlineKeyboardButton("💌 Написать", callback_data=f"chat_{uid}"))
            bot.send_message(to_uid,
                f"🎉 *Это матч!*\n\nВам понравился {my_profile['name']}!",
                parse_mode="Markdown", reply_markup=match_kb2
            )

    # Показываем следующий профиль
    user_state[uid] = {}
    show_next_profile(call.message.chat.id, uid)

# ================= МАТЧИ =================

@bot.message_handler(func=lambda m: m.text == "💌 Мои матчи")
def my_matches(m):
    uid = m.from_user.id
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM matches
                WHERE user1=%s OR user2=%s
                ORDER BY created DESC
            """, (str(uid), str(uid)))
            matches = cur.fetchall()

    if not matches:
        bot.send_message(m.chat.id, "У тебя пока нет матчей 😔\nПродолжай листать анкеты!", reply_markup=kb_main(uid))
        return

    kb = types.InlineKeyboardMarkup()
    for match in matches:
        other_uid = match["user2"] if match["user1"] == str(uid) else match["user1"]
        other = get_profile(other_uid)
        if other:
            kb.add(types.InlineKeyboardButton(
                f"{'❤️' if match else '💬'} {other['name']}, {other['age']} — {other['city']}",
                callback_data=f"chat_{other_uid}"
            ))

    bot.send_message(m.chat.id, f"💌 Твои матчи ({len(matches)}):", reply_markup=kb)

# ================= ЧАТ =================

@bot.callback_query_handler(func=lambda c: c.data.startswith("chat_"))
def open_chat(call):
    uid = call.from_user.id
    other_uid = call.data[5:]
    bot.answer_callback_query(call.id)

    # Проверяем что матч существует
    match_id = get_match_id(uid, other_uid)
    if not match_id:
        bot.send_message(call.message.chat.id, "Матч не найден.")
        return

    other = get_profile(other_uid)
    user_state[uid] = {"action": "chatting", "with": other_uid, "match_id": match_id}

    # Показываем последние сообщения
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM messages WHERE match_id=%s
                ORDER BY id DESC LIMIT 10
            """, (match_id,))
            msgs = list(reversed(cur.fetchall()))

    my_profile = get_profile(uid)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("🔙 Назад к матчам"))

    if msgs:
        history = []
        for msg in msgs:
            sender = my_profile["name"] if msg["from_user"] == str(uid) else other["name"]
            history.append(f"*{sender}:* {msg['text']}")
        bot.send_message(call.message.chat.id,
            f"💬 Чат с {other['name']}\n\n" + "\n".join(history) + "\n\nПиши сообщение:",
            parse_mode="Markdown", reply_markup=kb
        )
    else:
        bot.send_message(call.message.chat.id,
            f"💬 Чат с {other['name']}\n\nНапиши первым! 👇",
            reply_markup=kb
        )

@bot.message_handler(func=lambda m: m.text == "🔙 Назад к матчам")
def back_to_matches(m):
    uid = m.from_user.id
    user_state.pop(uid, None)
    bot.send_message(m.chat.id, "Возвращаемся к матчам...", reply_markup=kb_main(uid))
    my_matches(m)

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "chatting")
def send_chat_message(m):
    uid = m.from_user.id
    state = user_state.get(uid, {})
    other_uid = state.get("with")
    match_id = state.get("match_id")

    if not other_uid or not match_id:
        return

    # Сохраняем сообщение
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO messages (match_id, from_user, text, created)
                VALUES (%s, %s, %s, %s)
            """, (match_id, str(uid), m.text, now_str()))
        conn.commit()

    # Пересылаем другому пользователю
    my_profile = get_profile(uid)
    try:
        reply_kb = types.InlineKeyboardMarkup()
        reply_kb.add(types.InlineKeyboardButton("💬 Ответить", callback_data=f"chat_{uid}"))
        bot.send_message(other_uid,
            f"💌 *{my_profile['name']}:*\n{m.text}",
            parse_mode="Markdown",
            reply_markup=reply_kb
        )
        bot.send_message(m.chat.id, "✅ Отправлено!")
    except Exception as e:
        print(f"Ошибка отправки сообщения: {e}")
        bot.send_message(m.chat.id, "❌ Не удалось доставить сообщение.")

# ================= РЕДАКТИРОВАНИЕ АНКЕТЫ =================

@bot.callback_query_handler(func=lambda c: c.data == "edit_profile")
def edit_profile(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✏️ Имя", callback_data="edit_name"),
        types.InlineKeyboardButton("🔢 Возраст", callback_data="edit_age"),
        types.InlineKeyboardButton("📍 Город", callback_data="edit_city"),
        types.InlineKeyboardButton("📝 О себе", callback_data="edit_bio"),
        types.InlineKeyboardButton("🖼 Фото", callback_data="edit_photo"),
        types.InlineKeyboardButton("✨ Интересы", callback_data="edit_interests"),
    )
    bot.send_message(call.message.chat.id, "Что хочешь изменить?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ("edit_name", "edit_age", "edit_city", "edit_bio", "edit_photo", "edit_interests"))
def handle_edit(call):
    uid = call.from_user.id
    field = call.data[5:]
    bot.answer_callback_query(call.id)

    if field == "interests":
        profile = get_profile(uid)
        current = profile["interests"].split(", ") if profile and profile["interests"] else []
        user_state[uid] = {"action": "edit_interests", "interests": current}
        bot.send_message(call.message.chat.id, "Выбери интересы:", reply_markup=kb_interests(current))
        return

    prompts = {
        "name": "Введи новое имя:",
        "age": "Введи новый возраст:",
        "city": "Введи новый город:",
        "bio": "Расскажи о себе (или /skip):",
        "photo": "Отправь новое фото (или /skip):"
    }
    user_state[uid] = {"action": f"edit_{field}"}
    bot.send_message(call.message.chat.id, prompts[field], reply_markup=kb_cancel())

@bot.callback_query_handler(func=lambda c: c.data.startswith("int_") and user_state.get(c.from_user.id, {}).get("action") == "edit_interests")
def edit_interests_handler(call):
    uid = call.from_user.id
    val = call.data[4:]
    if val == "done":
        selected = user_state.pop(uid, {}).get("interests", [])
        interests_str = ", ".join(selected)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE profiles SET interests=%s WHERE user_id=%s", (interests_str, str(uid)))
            conn.commit()
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "✅ Интересы обновлены!", reply_markup=kb_main(uid))
        return
    selected = user_state[uid].get("interests", [])
    if val in selected:
        selected.remove(val)
    else:
        if len(selected) < 5:
            selected.append(val)
        else:
            bot.answer_callback_query(call.id, "Максимум 5!")
            return
    user_state[uid]["interests"] = selected
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=kb_interests(selected))
    except:
        pass

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") in ("edit_name", "edit_age", "edit_city", "edit_bio"))
def handle_edit_text(m):
    uid = m.from_user.id
    action = user_state.get(uid, {}).get("action", "")
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main(uid))
        return

    field = action[5:]
    value = m.text if m.text != "/skip" else ""

    if field == "age":
        try:
            value = int(m.text)
            if value < 18 or value > 99:
                bot.send_message(m.chat.id, "Возраст от 18 до 99.")
                return
        except:
            bot.send_message(m.chat.id, "Введи число.")
            return

    user_state.pop(uid, None)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE profiles SET {field}=%s WHERE user_id=%s", (value, str(uid)))
        conn.commit()
    bot.send_message(m.chat.id, "✅ Обновлено!", reply_markup=kb_main(uid))

@bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "edit_photo")
def handle_edit_photo(m):
    uid = m.from_user.id
    photo_id = m.photo[-1].file_id
    user_state.pop(uid, None)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE profiles SET photo_id=%s WHERE user_id=%s", (photo_id, str(uid)))
        conn.commit()
    bot.send_message(m.chat.id, "✅ Фото обновлено!", reply_markup=kb_main(uid))

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "edit_photo")
def handle_edit_photo_skip(m):
    uid = m.from_user.id
    if m.text in ("❌ Отмена", "/skip"):
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Без изменений.", reply_markup=kb_main(uid))

# ================= ПОКАЗАТЬ / СКРЫТЬ АНКЕТУ =================

@bot.callback_query_handler(func=lambda c: c.data == "toggle_active")
def toggle_active(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    profile = get_profile(uid)
    new_status = not profile["active"]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE profiles SET active=%s WHERE user_id=%s", (new_status, str(uid)))
        conn.commit()
    status_text = "🟢 Анкета видна всем!" if new_status else "🔴 Анкета скрыта."
    bot.send_message(call.message.chat.id, status_text, reply_markup=kb_main(uid))

# ================= НАСТРОЙКИ =================

@bot.message_handler(func=lambda m: m.text == "⚙️ Настройки")
def settings(m):
    uid = m.from_user.id
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🔍 Изменить фильтры поиска", callback_data="change_filters"),
        types.InlineKeyboardButton("🗑 Удалить анкету", callback_data="delete_profile")
    )
    bot.send_message(m.chat.id, "⚙️ Настройки:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "change_filters")
def change_filters(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    user_state[uid] = {"action": "reg_looking_for"}
    bot.send_message(call.message.chat.id, "Кого ищешь?", reply_markup=kb_looking_for())

@bot.callback_query_handler(func=lambda c: c.data == "delete_profile")
def delete_profile_confirm(call):
    bot.answer_callback_query(call.id)
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("⚠️ Да, удалить", callback_data="confirm_delete_profile"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete_profile")
    )
    bot.send_message(call.message.chat.id, "Удалить анкету и все данные? Это необратимо.", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ("confirm_delete_profile", "cancel_delete_profile"))
def handle_delete_profile(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    if call.data == "cancel_delete_profile":
        bot.send_message(call.message.chat.id, "Отменено.", reply_markup=kb_main(uid))
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM profiles WHERE user_id=%s", (str(uid),))
            cur.execute("DELETE FROM swipes WHERE from_user=%s OR to_user=%s", (str(uid), str(uid)))
            cur.execute("DELETE FROM matches WHERE user1=%s OR user2=%s", (str(uid), str(uid)))
        conn.commit()
    bot.send_message(call.message.chat.id, "✅ Анкета удалена.", reply_markup=kb_main(uid))

# ================= FLASK =================

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    update = types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return "ok", 200

@app.route("/", methods=["GET"])
def index():
    return "Dating bot is running!", 200

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}/webhook/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
