import os
import re
import pytz
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request
from telebot import telebot, types
import psycopg2
from psycopg2.extras import RealDictCursor

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("BOT_TOKEN")
RENDER_URL = os.getenv("RENDER_URL", "https://arman-c2rh.onrender.com")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================= БАЗА ДАННЫХ =================

def get_conn():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    currency TEXT DEFAULT '₸',
                    daily_reminder TEXT DEFAULT 'off',
                    joined TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT,
                    date TEXT,
                    type TEXT,
                    amount REAL,
                    category TEXT,
                    note TEXT,
                    month INTEGER,
                    year INTEGER
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS budgets (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT,
                    category TEXT,
                    limit_amount REAL,
                    month INTEGER,
                    year INTEGER,
                    UNIQUE(user_id, category, month, year)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS goals (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT,
                    name TEXT,
                    target REAL,
                    saved REAL DEFAULT 0,
                    currency TEXT,
                    created TEXT,
                    done INTEGER DEFAULT 0
                )
            """)
        conn.commit()

init_db()

# ================= КАТЕГОРИИ =================

EXPENSE_CATEGORIES = {
    "🍔 Еда": "еда",
    "🚗 Транспорт": "транспорт",
    "🏠 Жильё": "жильё",
    "💊 Здоровье": "здоровье",
    "🎮 Развлечения": "развлечения",
    "👗 Одежда": "одежда",
    "📚 Образование": "образование",
    "💡 Коммунальные": "коммунальные",
    "🛍 Прочее": "прочее"
}

INCOME_CATEGORIES = {
    "💼 Зарплата": "зарплата",
    "💰 Фриланс": "фриланс",
    "🎁 Подарок": "подарок",
    "📈 Инвестиции": "инвестиции",
    "🔄 Прочее": "прочее"
}

CATEGORY_EMOJIS = {
    "еда": "🍔", "транспорт": "🚗", "жильё": "🏠", "здоровье": "💊",
    "развлечения": "🎮", "одежда": "👗", "образование": "📚",
    "коммунальные": "💡", "прочее": "🛍", "зарплата": "💼",
    "фриланс": "💰", "подарок": "🎁", "инвестиции": "📈"
}

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

user_state = {}

def now_tz():
    return datetime.now(pytz.timezone("Asia/Almaty"))

def this_month():
    n = now_tz()
    return n.month, n.year

def format_amount(amount, currency="₸"):
    return f"{amount:,.0f} {currency}".replace(",", " ")

def get_user(uid):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id=%s", (str(uid),))
            return cur.fetchone()

def get_currency(uid):
    user = get_user(uid)
    return user["currency"] if user else "₸"

def register_user(uid, username):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, username, currency, daily_reminder, joined)
                VALUES (%s, %s, '₸', 'off', %s)
                ON CONFLICT (user_id) DO NOTHING
            """, (str(uid), username or "", now_tz().strftime("%d.%m.%Y")))
        conn.commit()

def save_transaction(uid, tx_type, amount, category, note=""):
    n = now_tz()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO transactions (user_id, date, type, amount, category, note, month, year)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (str(uid), n.strftime("%d.%m.%Y %H:%M"), tx_type, amount, category, note, n.month, n.year))
        conn.commit()

def check_budget_warning(uid, category, new_amount):
    month, year = this_month()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT limit_amount FROM budgets WHERE user_id=%s AND category=%s AND month=%s AND year=%s",
                (str(uid), category, month, year)
            )
            budget = cur.fetchone()
            if not budget:
                return None
            limit = budget["limit_amount"]
            cur.execute(
                "SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE user_id=%s AND category=%s AND month=%s AND year=%s AND type='expense'",
                (str(uid), category, month, year)
            )
            spent = cur.fetchone()["total"] + new_amount
            if spent >= limit:
                return f"⚠️ Лимит по «{category}» превышен! {format_amount(spent)} / {format_amount(limit)}"
            elif spent >= limit * 0.8:
                return f"⚠️ 80% бюджета по «{category}» использовано ({format_amount(spent)} / {format_amount(limit)})"
    return None

# ================= КЛАВИАТУРЫ =================

def kb_main():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("➕ Доход"),
        types.KeyboardButton("➖ Расход"),
        types.KeyboardButton("📊 Статистика"),
        types.KeyboardButton("🎯 Цели"),
        types.KeyboardButton("📋 Бюджет"),
        types.KeyboardButton("⚙️ Настройки")
    )
    return kb

def kb_cancel():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Отмена"))
    return kb

def kb_categories(cat_dict):
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(label, callback_data=f"cat_{val}") for label, val in cat_dict.items()]
    kb.add(*buttons)
    return kb

# ================= КОМАНДЫ =================

@bot.message_handler(commands=["start"])
def start(m):
    uid = m.from_user.id
    username = m.from_user.first_name or m.from_user.username or "друг"
    register_user(uid, username)
    text = (
        f"👋 Привет, {username}!\n\n"
        "Я — твой личный финансовый менеджер.\n\n"
        "Что я умею:\n"
        "• Учёт доходов и расходов\n"
        "• Бюджет по категориям\n"
        "• Цели накопления\n"
        "• Статистика и отчёты\n\n"
        "💡 Быстрый ввод: -500 еда кофе или +50000 зарплата"
    )
    bot.send_message(m.chat.id, text, reply_markup=kb_main())

@bot.message_handler(commands=["help"])
def help_cmd(m):
    text = (
        "📖 Как пользоваться:\n\n"
        "Быстрый ввод:\n"
        "-500 еда кофе — расход 500 на еду\n"
        "+50000 зарплата — доход 50000\n\n"
        "Кнопки меню:\n"
        "➕ Доход — добавить доход\n"
        "➖ Расход — добавить расход\n"
        "📊 Статистика — отчёт за месяц\n"
        "🎯 Цели — копилки и накопления\n"
        "📋 Бюджет — лимиты по категориям\n"
        "⚙️ Настройки — валюта, напоминания"
    )
    bot.send_message(m.chat.id, text, reply_markup=kb_main())

# ================= БЫСТРЫЙ ВВОД =================

@bot.message_handler(func=lambda m: bool(re.match(r'^[+-]\d+', m.text or "")))
def quick_input(m):
    uid = m.from_user.id
    currency = get_currency(uid)
    try:
        parts = m.text.strip().split()
        amount_str = parts[0]
        tx_type = "income" if amount_str[0] == "+" else "expense"
        amount = float(amount_str[1:].replace(",", "."))
        category = parts[1].lower() if len(parts) > 1 else "прочее"
        note = " ".join(parts[2:]) if len(parts) > 2 else ""
        save_transaction(uid, tx_type, amount, category, note)
        emoji = "➕" if tx_type == "income" else "➖"
        cat_emoji = CATEGORY_EMOJIS.get(category, "📌")
        reply = f"{emoji} {format_amount(amount, currency)}\n{cat_emoji} {category.capitalize()}"
        if note:
            reply += f"\n📝 {note}"
        if tx_type == "expense":
            warning = check_budget_warning(uid, category, amount)
            if warning:
                reply += f"\n\n{warning}"
        bot.send_message(m.chat.id, reply, reply_markup=kb_main())
    except Exception as e:
        print(f"quick_input error: {e}")
        bot.send_message(m.chat.id, "Формат: -500 еда кофе или +50000 зарплата", reply_markup=kb_main())

# ================= ДОХОД / РАСХОД =================

@bot.message_handler(func=lambda m: m.text == "➕ Доход")
def add_income(m):
    user_state[m.from_user.id] = {"action": "income_category"}
    bot.send_message(m.chat.id, "Выберите категорию дохода:", reply_markup=kb_categories(INCOME_CATEGORIES))

@bot.message_handler(func=lambda m: m.text == "➖ Расход")
def add_expense(m):
    user_state[m.from_user.id] = {"action": "expense_category"}
    bot.send_message(m.chat.id, "Выберите категорию расхода:", reply_markup=kb_categories(EXPENSE_CATEGORIES))

@bot.callback_query_handler(func=lambda c: c.data.startswith("cat_") and user_state.get(c.from_user.id, {}).get("action") in ("income_category", "expense_category"))
def handle_category(call):
    uid = call.from_user.id
    category = call.data[4:]
    tx_type = "income" if user_state[uid]["action"] == "income_category" else "expense"
    user_state[uid] = {"action": "enter_amount", "type": tx_type, "category": category}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, f"Введите сумму ({get_currency(uid)}):", reply_markup=kb_cancel())

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "enter_amount")
def enter_amount(m):
    uid = m.from_user.id
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main())
        return
    try:
        amount = float(m.text.replace(",", ".").replace(" ", ""))
        user_state[uid] = {**user_state[uid], "action": "enter_note", "amount": amount}
        bot.send_message(m.chat.id, "Добавьте заметку (или /skip):", reply_markup=kb_cancel())
    except:
        bot.send_message(m.chat.id, "Введите число, например: 1500")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "enter_note")
def enter_note(m):
    uid = m.from_user.id
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main())
        return
    note = "" if m.text == "/skip" else m.text
    state = user_state.pop(uid, {})
    currency = get_currency(uid)
    save_transaction(uid, state["type"], state["amount"], state["category"], note)
    emoji = "➕" if state["type"] == "income" else "➖"
    cat_emoji = CATEGORY_EMOJIS.get(state["category"], "📌")
    reply = f"{emoji} {format_amount(state['amount'], currency)}\n{cat_emoji} {state['category'].capitalize()}"
    if note:
        reply += f"\n📝 {note}"
    if state["type"] == "expense":
        warning = check_budget_warning(uid, state["category"], state["amount"])
        if warning:
            reply += f"\n\n{warning}"
    bot.send_message(m.chat.id, reply, reply_markup=kb_main())

# ================= СТАТИСТИКА =================

@bot.message_handler(func=lambda m: m.text == "📊 Статистика")
def statistics(m):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📅 Этот месяц", callback_data="stats_month"),
        types.InlineKeyboardButton("📆 Эта неделя", callback_data="stats_week"),
        types.InlineKeyboardButton("📋 По категориям", callback_data="stats_cats"),
        types.InlineKeyboardButton("📜 Последние 10", callback_data="stats_last")
    )
    bot.send_message(m.chat.id, "Выберите отчёт:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("stats_"))
def handle_stats(call):
    uid = call.from_user.id
    currency = get_currency(uid)
    mode = call.data[6:]
    bot.answer_callback_query(call.id)
    n = now_tz()

    with get_conn() as conn:
        with conn.cursor() as cur:
            if mode == "month":
                cur.execute("SELECT * FROM transactions WHERE user_id=%s AND month=%s AND year=%s", (str(uid), n.month, n.year))
                rows = cur.fetchall()
                income = sum(r["amount"] for r in rows if r["type"] == "income")
                expense = sum(r["amount"] for r in rows if r["type"] == "expense")
                balance = income - expense
                text = (
                    f"📅 {n.strftime('%B %Y')}\n\n"
                    f"➕ Доходы: {format_amount(income, currency)}\n"
                    f"➖ Расходы: {format_amount(expense, currency)}\n"
                    f"{'🟢' if balance >= 0 else '🔴'} Баланс: {format_amount(balance, currency)}\n\n"
                    f"📌 Транзакций: {len(rows)}"
                )
                bot.send_message(call.message.chat.id, text, reply_markup=kb_main())

            elif mode == "week":
                week_ago = (n - timedelta(days=7)).strftime("%d.%m.%Y")
                cur.execute("SELECT * FROM transactions WHERE user_id=%s AND date >= %s", (str(uid), week_ago))
                rows = cur.fetchall()
                income = sum(r["amount"] for r in rows if r["type"] == "income")
                expense = sum(r["amount"] for r in rows if r["type"] == "expense")
                balance = income - expense
                text = (
                    f"📆 Последние 7 дней\n\n"
                    f"➕ Доходы: {format_amount(income, currency)}\n"
                    f"➖ Расходы: {format_amount(expense, currency)}\n"
                    f"{'🟢' if balance >= 0 else '🔴'} Баланс: {format_amount(balance, currency)}\n\n"
                    f"📌 Транзакций: {len(rows)}"
                )
                bot.send_message(call.message.chat.id, text, reply_markup=kb_main())

            elif mode == "cats":
                cur.execute(
                    "SELECT category, SUM(amount) as total FROM transactions WHERE user_id=%s AND month=%s AND year=%s AND type='expense' GROUP BY category ORDER BY total DESC",
                    (str(uid), n.month, n.year)
                )
                rows = cur.fetchall()
                if not rows:
                    bot.send_message(call.message.chat.id, "Нет расходов за этот месяц.", reply_markup=kb_main())
                    return
                total = sum(r["total"] for r in rows)
                lines = [f"📋 По категориям — {n.strftime('%B %Y')}\n"]
                for r in rows:
                    pct = r["total"] / total * 100
                    bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
                    emoji = CATEGORY_EMOJIS.get(r["category"], "📌")
                    lines.append(f"{emoji} {r['category'].capitalize()}\n{bar} {pct:.0f}% — {format_amount(r['total'], currency)}")
                lines.append(f"\n💸 Итого: {format_amount(total, currency)}")
                bot.send_message(call.message.chat.id, "\n\n".join(lines), reply_markup=kb_main())

            elif mode == "last":
                cur.execute("SELECT * FROM transactions WHERE user_id=%s ORDER BY id DESC LIMIT 10", (str(uid),))
                rows = cur.fetchall()
                if not rows:
                    bot.send_message(call.message.chat.id, "Нет транзакций.", reply_markup=kb_main())
                    return
                lines = ["📜 Последние 10 операций\n"]
                for r in rows:
                    emoji = "➕" if r["type"] == "income" else "➖"
                    cat_emoji = CATEGORY_EMOJIS.get(r["category"], "📌")
                    note = f" — {r['note']}" if r["note"] else ""
                    lines.append(f"{emoji} {format_amount(r['amount'], currency)} {cat_emoji} {r['category']}{note}\n{r['date']}")
                bot.send_message(call.message.chat.id, "\n\n".join(lines), reply_markup=kb_main())

# ================= БЮДЖЕТ =================

@bot.message_handler(func=lambda m: m.text == "📋 Бюджет")
def budget_menu(m):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ Установить лимит", callback_data="budget_set"),
        types.InlineKeyboardButton("📊 Текущий бюджет", callback_data="budget_view")
    )
    bot.send_message(m.chat.id, "📋 Управление бюджетом:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "budget_set")
def budget_set(call):
    uid = call.from_user.id
    user_state[uid] = {"action": "budget_category"}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Выберите категорию для лимита:", reply_markup=kb_categories(EXPENSE_CATEGORIES))

@bot.callback_query_handler(func=lambda c: c.data.startswith("cat_") and user_state.get(c.from_user.id, {}).get("action") == "budget_category")
def budget_category_chosen(call):
    uid = call.from_user.id
    category = call.data[4:]
    user_state[uid] = {"action": "budget_amount", "category": category}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, f"Введите лимит для «{category}» ({get_currency(uid)}):", reply_markup=kb_cancel())

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "budget_amount")
def budget_amount_entered(m):
    uid = m.from_user.id
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main())
        return
    try:
        limit = float(m.text.replace(",", ".").replace(" ", ""))
        state = user_state.pop(uid, {})
        category = state["category"]
        month, year = this_month()
        currency = get_currency(uid)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO budgets (user_id, category, limit_amount, month, year)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, category, month, year) DO UPDATE SET limit_amount=EXCLUDED.limit_amount
                """, (str(uid), category, limit, month, year))
            conn.commit()
        bot.send_message(m.chat.id,
            f"✅ Лимит установлен!\n{CATEGORY_EMOJIS.get(category,'📌')} {category.capitalize()}: {format_amount(limit, currency)}/мес",
            reply_markup=kb_main()
        )
    except:
        bot.send_message(m.chat.id, "Введите число.")

@bot.callback_query_handler(func=lambda c: c.data == "budget_view")
def budget_view(call):
    uid = call.from_user.id
    month, year = this_month()
    currency = get_currency(uid)
    bot.answer_callback_query(call.id)
    n = now_tz()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM budgets WHERE user_id=%s AND month=%s AND year=%s", (str(uid), month, year))
            budgets = cur.fetchall()
            if not budgets:
                bot.send_message(call.message.chat.id, "Лимиты не установлены.", reply_markup=kb_main())
                return
            lines = [f"📋 Бюджет на {n.strftime('%B %Y')}\n"]
            for b in budgets:
                cat = b["category"]
                limit = b["limit_amount"]
                cur.execute(
                    "SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE user_id=%s AND category=%s AND month=%s AND year=%s AND type='expense'",
                    (str(uid), cat, month, year)
                )
                spent = cur.fetchone()["total"]
                remaining = limit - spent
                pct = min(spent / limit * 100, 100) if limit > 0 else 0
                filled = int(pct / 10)
                bar = "🟥" * filled + "⬜" * (10 - filled) if pct >= 80 else "🟩" * filled + "⬜" * (10 - filled)
                status = "⚠️" if pct >= 80 else "✅"
                emoji = CATEGORY_EMOJIS.get(cat, "📌")
                lines.append(
                    f"{status} {emoji} {cat.capitalize()}\n"
                    f"{bar} {pct:.0f}%\n"
                    f"Потрачено: {format_amount(spent, currency)} / {format_amount(limit, currency)}\n"
                    f"Остаток: {format_amount(remaining, currency)}"
                )
    bot.send_message(call.message.chat.id, "\n\n".join(lines), reply_markup=kb_main())

# ================= ЦЕЛИ =================

@bot.message_handler(func=lambda m: m.text == "🎯 Цели")
def goals_menu(m):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ Новая цель", callback_data="goal_new"),
        types.InlineKeyboardButton("💰 Пополнить", callback_data="goal_add"),
        types.InlineKeyboardButton("📋 Мои цели", callback_data="goal_list")
    )
    bot.send_message(m.chat.id, "🎯 Цели накопления:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "goal_new")
def goal_new(call):
    user_state[call.from_user.id] = {"action": "goal_name"}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Введите название цели (например: Телефон, Отпуск):", reply_markup=kb_cancel())

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "goal_name")
def goal_name_entered(m):
    uid = m.from_user.id
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main())
        return
    user_state[uid] = {"action": "goal_target", "name": m.text}
    bot.send_message(m.chat.id, f"Введите целевую сумму ({get_currency(uid)}):", reply_markup=kb_cancel())

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "goal_target")
def goal_target_entered(m):
    uid = m.from_user.id
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main())
        return
    try:
        target = float(m.text.replace(",", ".").replace(" ", ""))
        state = user_state.pop(uid, {})
        currency = get_currency(uid)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO goals (user_id, name, target, saved, currency, created, done) VALUES (%s, %s, %s, 0, %s, %s, 0)",
                    (str(uid), state["name"], target, currency, now_tz().strftime("%d.%m.%Y"))
                )
            conn.commit()
        bot.send_message(m.chat.id, f"🎯 Цель создана!\n{state['name']} — {format_amount(target, currency)}", reply_markup=kb_main())
    except:
        bot.send_message(m.chat.id, "Введите число.")

@bot.callback_query_handler(func=lambda c: c.data == "goal_list")
def goal_list(call):
    uid = call.from_user.id
    currency = get_currency(uid)
    bot.answer_callback_query(call.id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM goals WHERE user_id=%s AND done=0", (str(uid),))
            goals = cur.fetchall()
    if not goals:
        bot.send_message(call.message.chat.id, "У тебя пока нет целей. Создай первую!", reply_markup=kb_main())
        return
    lines = ["🎯 Мои цели\n"]
    for g in goals:
        pct = min(g["saved"] / g["target"] * 100, 100) if g["target"] > 0 else 0
        filled = int(pct / 10)
        bar = "🟡" * filled + "⬜" * (10 - filled)
        lines.append(
            f"{g['name']}\n"
            f"{bar} {pct:.0f}%\n"
            f"Накоплено: {format_amount(g['saved'], currency)} / {format_amount(g['target'], currency)}\n"
            f"Осталось: {format_amount(g['target'] - g['saved'], currency)}"
        )
    bot.send_message(call.message.chat.id, "\n\n".join(lines), reply_markup=kb_main())

@bot.callback_query_handler(func=lambda c: c.data == "goal_add")
def goal_add_select(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM goals WHERE user_id=%s AND done=0", (str(uid),))
            goals = cur.fetchall()
    if not goals:
        bot.send_message(call.message.chat.id, "Нет активных целей.", reply_markup=kb_main())
        return
    kb = types.InlineKeyboardMarkup()
    for g in goals:
        kb.add(types.InlineKeyboardButton(g["name"], callback_data=f"goal_deposit_{g['id']}"))
    bot.send_message(call.message.chat.id, "В какую цель пополнить?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("goal_deposit_"))
def goal_deposit_chosen(call):
    uid = call.from_user.id
    goal_id = call.data[len("goal_deposit_"):]
    user_state[uid] = {"action": "goal_deposit_amount", "goal_id": goal_id}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, f"Введите сумму пополнения ({get_currency(uid)}):", reply_markup=kb_cancel())

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "goal_deposit_amount")
def goal_deposit_amount(m):
    uid = m.from_user.id
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main())
        return
    try:
        amount = float(m.text.replace(",", ".").replace(" ", ""))
        state = user_state.pop(uid, {})
        goal_id = state["goal_id"]
        currency = get_currency(uid)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM goals WHERE id=%s AND user_id=%s", (goal_id, str(uid)))
                goal = cur.fetchone()
                if not goal:
                    bot.send_message(m.chat.id, "Цель не найдена.", reply_markup=kb_main())
                    return
                new_saved = goal["saved"] + amount
                done = 1 if new_saved >= goal["target"] else 0
                cur.execute("UPDATE goals SET saved=%s, done=%s WHERE id=%s", (new_saved, done, goal_id))
            conn.commit()
        if done:
            bot.send_message(m.chat.id,
                f"🎉 Цель достигнута! {goal['name']}\n{format_amount(new_saved, currency)} / {format_amount(goal['target'], currency)}",
                reply_markup=kb_main()
            )
        else:
            pct = new_saved / goal["target"] * 100
            bot.send_message(m.chat.id,
                f"💰 +{format_amount(amount, currency)}\n"
                f"{goal['name']}: {pct:.0f}% ({format_amount(new_saved, currency)} / {format_amount(goal['target'], currency)})\n"
                f"Осталось: {format_amount(goal['target'] - new_saved, currency)}",
                reply_markup=kb_main()
            )
    except Exception as e:
        print(f"goal_deposit error: {e}")
        bot.send_message(m.chat.id, "Введите число.")

# ================= НАСТРОЙКИ =================

@bot.message_handler(func=lambda m: m.text == "⚙️ Настройки")
def settings(m):
    uid = m.from_user.id
    user = get_user(uid)
    currency = user["currency"] if user else "₸"
    reminder = user["daily_reminder"] if user else "off"
    reminder_label = f"🔔 {reminder}" if reminder != "off" else "🔕 Напоминание выкл"
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(f"💱 Валюта: {currency}", callback_data="settings_currency"),
        types.InlineKeyboardButton(reminder_label, callback_data="settings_reminder"),
        types.InlineKeyboardButton("🗑 Удалить все данные", callback_data="settings_delete")
    )
    bot.send_message(m.chat.id, "⚙️ Настройки:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "settings_currency")
def settings_currency(call):
    bot.answer_callback_query(call.id)
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("₸ Тенге", callback_data="currency_₸"),
        types.InlineKeyboardButton("₽ Рубль", callback_data="currency_₽"),
        types.InlineKeyboardButton("$ Доллар", callback_data="currency_$"),
        types.InlineKeyboardButton("€ Евро", callback_data="currency_€"),
        types.InlineKeyboardButton("£ Фунт", callback_data="currency_£"),
    )
    bot.send_message(call.message.chat.id, "Выберите валюту:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("currency_"))
def currency_chosen(call):
    uid = call.from_user.id
    currency = call.data[9:]
    bot.answer_callback_query(call.id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET currency=%s WHERE user_id=%s", (currency, str(uid)))
        conn.commit()
    bot.send_message(call.message.chat.id, f"✅ Валюта изменена на {currency}", reply_markup=kb_main())

@bot.callback_query_handler(func=lambda c: c.data == "settings_reminder")
def settings_reminder(call):
    bot.answer_callback_query(call.id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🌅 08:00", callback_data="reminder_08:00"),
        types.InlineKeyboardButton("🌆 18:00", callback_data="reminder_18:00"),
        types.InlineKeyboardButton("🌙 21:00", callback_data="reminder_21:00"),
        types.InlineKeyboardButton("🔕 Выключить", callback_data="reminder_off"),
    )
    bot.send_message(call.message.chat.id, "Ежедневная сводка — когда присылать?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("reminder_"))
def reminder_chosen(call):
    uid = call.from_user.id
    time_val = call.data[9:]
    bot.answer_callback_query(call.id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET daily_reminder=%s WHERE user_id=%s", (time_val, str(uid)))
        conn.commit()
    label = f"в {time_val}" if time_val != "off" else "выключено"
    bot.send_message(call.message.chat.id, f"✅ Напоминание {label}", reply_markup=kb_main())

@bot.callback_query_handler(func=lambda c: c.data == "settings_delete")
def settings_delete_confirm(call):
    bot.answer_callback_query(call.id)
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("⚠️ Да, удалить всё", callback_data="confirm_delete"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")
    )
    bot.send_message(call.message.chat.id, "Удалить ВСЕ твои данные? Это необратимо.", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ("confirm_delete", "cancel_delete"))
def handle_delete(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    if call.data == "cancel_delete":
        bot.send_message(call.message.chat.id, "Отменено.", reply_markup=kb_main())
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM transactions WHERE user_id=%s", (str(uid),))
            cur.execute("DELETE FROM budgets WHERE user_id=%s", (str(uid),))
            cur.execute("DELETE FROM goals WHERE user_id=%s", (str(uid),))
        conn.commit()
    bot.send_message(call.message.chat.id, "✅ Все данные удалены.", reply_markup=kb_main())

# ================= ЕЖЕДНЕВНАЯ СВОДКА =================

def daily_summary_loop():
    while True:
        try:
            n = now_tz()
            now_time = n.strftime("%H:%M")
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM users WHERE daily_reminder=%s", (now_time,))
                    users = cur.fetchall()
                    for user in users:
                        uid = user["user_id"]
                        currency = user["currency"]
                        today_str = n.strftime("%d.%m.%Y")
                        cur.execute("SELECT * FROM transactions WHERE user_id=%s AND date LIKE %s", (uid, f"{today_str}%"))
                        today_rows = cur.fetchall()
                        cur.execute("SELECT * FROM transactions WHERE user_id=%s AND month=%s AND year=%s", (uid, n.month, n.year))
                        month_rows = cur.fetchall()
                        income_today = sum(r["amount"] for r in today_rows if r["type"] == "income")
                        expense_today = sum(r["amount"] for r in today_rows if r["type"] == "expense")
                        income_month = sum(r["amount"] for r in month_rows if r["type"] == "income")
                        expense_month = sum(r["amount"] for r in month_rows if r["type"] == "expense")
                        text = (
                            f"📊 Ежедневная сводка\n\n"
                            f"Сегодня:\n"
                            f"➕ {format_amount(income_today, currency)}\n"
                            f"➖ {format_amount(expense_today, currency)}\n\n"
                            f"За месяц:\n"
                            f"➕ {format_amount(income_month, currency)}\n"
                            f"➖ {format_amount(expense_month, currency)}\n"
                            f"{'🟢' if income_month >= expense_month else '🔴'} Баланс: {format_amount(income_month - expense_month, currency)}"
                        )
                        try:
                            bot.send_message(uid, text)
                        except Exception as e:
                            print(f"Ошибка отправки сводки {uid}: {e}")
        except Exception as e:
            print(f"Ошибка daily_summary_loop: {e}")
        time.sleep(55)

threading.Thread(target=daily_summary_loop, daemon=True).start()

# ================= FLASK =================

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    update = types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return "ok", 200

@app.route("/", methods=["GET"])
def index():
    return "Bot is running!", 200

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}/webhook/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
ENDOFFILE