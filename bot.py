import os
import re
import pytz
import time
import threading
import gspread
from datetime import datetime, timedelta
from flask import Flask, request
from telebot import telebot, types
from oauth2client.service_account import ServiceAccountCredentials

# ================= НАСТРОЙКИ =================

TOKEN = os.getenv("BOT_TOKEN")
CREDENTIALS_FILE = "/etc/secrets/credentials.json"
RENDER_URL = os.getenv("RENDER_URL", "https://your-app.onrender.com")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================= GOOGLE SHEETS =================

SCOPE = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

SHEET_USERS = "Users"
SHEET_TX = "Transactions"
SHEET_BUDGETS = "Budgets"
SHEET_GOALS = "Goals"

def get_client():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, SCOPE)
    return gspread.authorize(creds)

def get_spreadsheet():
    client = get_client()
    return client.open("FinanceBot")

def get_sheet(name):
    try:
        return get_spreadsheet().worksheet(name)
    except Exception as e:
        print(f"Ошибка получения листа {name}: {e}")
        return None

def ensure_sheets():
    """Создаёт нужные листы если их нет"""
    try:
        ss = get_spreadsheet()
        existing = [ws.title for ws in ss.worksheets()]

        if SHEET_USERS not in existing:
            ws = ss.add_worksheet(SHEET_USERS, rows=1000, cols=10)
            ws.append_row(["user_id", "username", "currency", "timezone", "daily_reminder", "joined"])

        if SHEET_TX not in existing:
            ws = ss.add_worksheet(SHEET_TX, rows=10000, cols=8)
            ws.append_row(["user_id", "date", "type", "amount", "category", "note", "month", "year"])

        if SHEET_BUDGETS not in existing:
            ws = ss.add_worksheet(SHEET_BUDGETS, rows=1000, cols=5)
            ws.append_row(["user_id", "category", "limit_amount", "month", "year"])

        if SHEET_GOALS not in existing:
            ws = ss.add_worksheet(SHEET_GOALS, rows=1000, cols=7)
            ws.append_row(["user_id", "name", "target", "saved", "currency", "created", "done"])

    except Exception as e:
        print(f"Ошибка ensure_sheets: {e}")

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

user_state = {}  # Хранит текущее состояние пользователя

def get_user(uid):
    sheet = get_sheet(SHEET_USERS)
    if not sheet: return None
    try:
        cell = sheet.find(str(uid))
        if cell:
            row = sheet.row_values(cell.row)
            return {
                "user_id": row[0], "username": row[1],
                "currency": row[2] if len(row) > 2 else "₸",
                "timezone": row[3] if len(row) > 3 else "Asia/Almaty",
                "daily_reminder": row[4] if len(row) > 4 else "off",
                "joined": row[5] if len(row) > 5 else ""
            }
    except:
        pass
    return None

def register_user(uid, username):
    sheet = get_sheet(SHEET_USERS)
    if not sheet: return
    if not get_user(uid):
        sheet.append_row([str(uid), username or "", "₸", "Asia/Almaty", "off", datetime.now().strftime("%d.%m.%Y")])

def get_currency(uid):
    user = get_user(uid)
    return user["currency"] if user else "₸"

def now_str():
    tz = pytz.timezone("Asia/Almaty")
    return datetime.now(tz)

def this_month():
    n = now_str()
    return n.month, n.year

def format_amount(amount, currency="₸"):
    return f"{amount:,.0f} {currency}".replace(",", " ")

# ================= ГЛАВНОЕ МЕНЮ =================

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
    ensure_sheets()

    text = (
        f"👋 Привет, {username}!\n\n"
        "Я — твой личный финансовый менеджер.\n\n"
        "Что я умею:\n"
        "• Учёт доходов и расходов\n"
        "• Установка бюджета по категориям\n"
        "• Цели накопления\n"
        "• Статистика за месяц\n"
        "• Ежедневные сводки\n\n"
        "Начни с кнопок ниже 👇"
    )
    bot.send_message(m.chat.id, text, reply_markup=kb_main())

@bot.message_handler(commands=["help"])
def help_cmd(m):
    text = (
        "📖 *Как пользоваться:*\n\n"
        "*Быстрый ввод:*\n"
        "`-500 еда кофе` — расход 500 на еду\n"
        "`+50000 зарплата` — доход 50000\n\n"
        "*Кнопки меню:*\n"
        "➕ Доход — добавить доход\n"
        "➖ Расход — добавить расход\n"
        "📊 Статистика — отчёт за месяц\n"
        "🎯 Цели — копилки и накопления\n"
        "📋 Бюджет — лимиты по категориям\n"
        "⚙️ Настройки — валюта, напоминания\n"
    )
    bot.send_message(m.chat.id, text, parse_mode="Markdown", reply_markup=kb_main())

# ================= БЫСТРЫЙ ВВОД =================

@bot.message_handler(func=lambda m: re.match(r'^[+-]\d+', m.text or ""))
def quick_input(m):
    uid = m.from_user.id
    text = m.text.strip()
    currency = get_currency(uid)

    try:
        parts = text.split()
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
        
        # Проверяем бюджет при расходе
        if tx_type == "expense":
            warning = check_budget_warning(uid, category, amount)
            if warning:
                reply += f"\n\n{warning}"

        bot.send_message(m.chat.id, reply, reply_markup=kb_main())
    except Exception as e:
        bot.send_message(m.chat.id, "❗ Формат: `-500 еда кофе` или `+50000 зарплата`", reply_markup=kb_main())

# ================= ДОБАВЛЕНИЕ ДОХОДА =================

@bot.message_handler(func=lambda m: m.text == "➕ Доход")
def add_income(m):
    uid = m.from_user.id
    user_state[uid] = {"action": "income_category"}
    bot.send_message(m.chat.id, "Выберите категорию дохода:", reply_markup=kb_categories(INCOME_CATEGORIES))

# ================= ДОБАВЛЕНИЕ РАСХОДА =================

@bot.message_handler(func=lambda m: m.text == "➖ Расход")
def add_expense(m):
    uid = m.from_user.id
    user_state[uid] = {"action": "expense_category"}
    bot.send_message(m.chat.id, "Выберите категорию расхода:", reply_markup=kb_categories(EXPENSE_CATEGORIES))

@bot.callback_query_handler(func=lambda c: c.data.startswith("cat_"))
def handle_category(call):
    uid = call.from_user.id
    category = call.data[4:]
    state = user_state.get(uid, {})

    if state.get("action") in ("income_category", "expense_category"):
        tx_type = "income" if state["action"] == "income_category" else "expense"
        user_state[uid] = {"action": "enter_amount", "type": tx_type, "category": category}
        currency = get_currency(uid)
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id,
            f"Введите сумму ({currency}):",
            reply_markup=kb_cancel()
        )

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "enter_amount")
def enter_amount(m):
    uid = m.from_user.id
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main())
        return

    try:
        amount = float(m.text.replace(",", ".").replace(" ", ""))
        state = user_state[uid]
        user_state[uid] = {**state, "action": "enter_note", "amount": amount}
        bot.send_message(m.chat.id, "Добавьте заметку (или нажмите /skip):", reply_markup=kb_cancel())
    except:
        bot.send_message(m.chat.id, "❗ Введите число, например: 1500")

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

# ================= СОХРАНЕНИЕ ТРАНЗАКЦИИ =================

def save_transaction(uid, tx_type, amount, category, note=""):
    sheet = get_sheet(SHEET_TX)
    if not sheet: return
    n = now_str()
    sheet.append_row([
        str(uid),
        n.strftime("%d.%m.%Y %H:%M"),
        tx_type,
        amount,
        category,
        note,
        n.month,
        n.year
    ])

def check_budget_warning(uid, category, new_amount):
    """Проверяет, не превышен ли бюджет по категории"""
    month, year = this_month()
    budget = get_budget_for_category(uid, category, month, year)
    if not budget:
        return None
    
    spent = get_spent_in_category(uid, category, month, year) + new_amount
    limit = budget["limit"]
    
    if spent >= limit:
        return f"⚠️ Лимит по «{category}» превышен! {format_amount(spent)} / {format_amount(limit)}"
    elif spent >= limit * 0.8:
        return f"⚠️ 80% бюджета по «{category}» использовано ({format_amount(spent)} / {format_amount(limit)})"
    return None

# ================= СТАТИСТИКА =================

@bot.message_handler(func=lambda m: m.text == "📊 Статистика")
def statistics(m):
    uid = m.from_user.id
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

    sheet = get_sheet(SHEET_TX)
    if not sheet:
        bot.send_message(call.message.chat.id, "Ошибка загрузки данных.")
        return

    all_rows = sheet.get_all_records()
    user_rows = [r for r in all_rows if str(r["user_id"]) == str(uid)]

    n = now_str()

    if mode == "month":
        rows = [r for r in user_rows if int(r["month"]) == n.month and int(r["year"]) == n.year]
        title = f"📅 {n.strftime('%B %Y')}"
    elif mode == "week":
        week_ago = (n - timedelta(days=7)).strftime("%d.%m.%Y")
        rows = [r for r in user_rows if r["date"][:10] >= week_ago]
        title = "📆 Последние 7 дней"
    elif mode == "cats":
        rows = [r for r in user_rows if int(r["month"]) == n.month and int(r["year"]) == n.year]
        title = "📋 По категориям"
        _send_category_stats(call.message.chat.id, rows, title, currency)
        return
    elif mode == "last":
        rows = user_rows[-10:]
        title = "📜 Последние 10 операций"
        _send_last_transactions(call.message.chat.id, rows, title, currency)
        return

    income = sum(float(r["amount"]) for r in rows if r["type"] == "income")
    expense = sum(float(r["amount"]) for r in rows if r["type"] == "expense")
    balance = income - expense

    text = (
        f"*{title}*\n\n"
        f"➕ Доходы: {format_amount(income, currency)}\n"
        f"➖ Расходы: {format_amount(expense, currency)}\n"
        f"{'🟢' if balance >= 0 else '🔴'} Баланс: {format_amount(balance, currency)}\n\n"
        f"📌 Транзакций: {len(rows)}"
    )
    bot.send_message(call.message.chat.id, text, parse_mode="Markdown", reply_markup=kb_main())

def _send_category_stats(chat_id, rows, title, currency):
    expense_rows = [r for r in rows if r["type"] == "expense"]
    cats = {}
    for r in expense_rows:
        cat = r["category"]
        cats[cat] = cats.get(cat, 0) + float(r["amount"])

    if not cats:
        bot.send_message(chat_id, "Нет расходов за этот период.", reply_markup=kb_main())
        return

    total = sum(cats.values())
    lines = [f"*{title}*\n"]
    for cat, amt in sorted(cats.items(), key=lambda x: -x[1]):
        emoji = CATEGORY_EMOJIS.get(cat, "📌")
        pct = amt / total * 100
        bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        lines.append(f"{emoji} {cat.capitalize()}\n{bar} {pct:.0f}% — {format_amount(amt, currency)}")

    lines.append(f"\n💸 Итого: {format_amount(total, currency)}")
    bot.send_message(chat_id, "\n\n".join(lines), parse_mode="Markdown", reply_markup=kb_main())

def _send_last_transactions(chat_id, rows, title, currency):
    if not rows:
        bot.send_message(chat_id, "Нет транзакций.", reply_markup=kb_main())
        return

    lines = [f"*{title}*\n"]
    for r in reversed(rows):
        emoji = "➕" if r["type"] == "income" else "➖"
        cat_emoji = CATEGORY_EMOJIS.get(r["category"], "📌")
        note = f" — {r['note']}" if r.get("note") else ""
        lines.append(f"{emoji} {format_amount(float(r['amount']), currency)} {cat_emoji} {r['category']}{note}\n_{r['date']}_")

    bot.send_message(chat_id, "\n\n".join(lines), parse_mode="Markdown", reply_markup=kb_main())

# ================= БЮДЖЕТ =================

@bot.message_handler(func=lambda m: m.text == "📋 Бюджет")
def budget_menu(m):
    uid = m.from_user.id
    month, year = this_month()
    currency = get_currency(uid)

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
    currency = get_currency(uid)
    bot.send_message(call.message.chat.id, f"Введите лимит для «{category}» ({currency}):", reply_markup=kb_cancel())

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

        save_budget(uid, category, limit, month, year)
        bot.send_message(m.chat.id,
            f"✅ Лимит установлен!\n{CATEGORY_EMOJIS.get(category,'📌')} {category.capitalize()}: {format_amount(limit, currency)}/мес",
            reply_markup=kb_main()
        )
    except:
        bot.send_message(m.chat.id, "❗ Введите число.")

@bot.callback_query_handler(func=lambda c: c.data == "budget_view")
def budget_view(call):
    uid = call.from_user.id
    month, year = this_month()
    currency = get_currency(uid)
    bot.answer_callback_query(call.id)

    sheet_b = get_sheet(SHEET_BUDGETS)
    sheet_t = get_sheet(SHEET_TX)
    if not sheet_b or not sheet_t:
        bot.send_message(call.message.chat.id, "Ошибка загрузки.")
        return

    budgets = [r for r in sheet_b.get_all_records() if str(r["user_id"]) == str(uid) and int(r["month"]) == month and int(r["year"]) == year]
    txs = [r for r in sheet_t.get_all_records() if str(r["user_id"]) == str(uid) and int(r["month"]) == month and int(r["year"]) == year and r["type"] == "expense"]

    if not budgets:
        bot.send_message(call.message.chat.id, "Лимиты не установлены. Нажми «Установить лимит».", reply_markup=kb_main())
        return

    n = now_str()
    lines = [f"*📋 Бюджет на {n.strftime('%B %Y')}*\n"]
    for b in budgets:
        cat = b["category"]
        limit = float(b["limit_amount"])
        spent = sum(float(r["amount"]) for r in txs if r["category"] == cat)
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

    bot.send_message(call.message.chat.id, "\n\n".join(lines), parse_mode="Markdown", reply_markup=kb_main())

def save_budget(uid, category, limit, month, year):
    sheet = get_sheet(SHEET_BUDGETS)
    if not sheet: return
    records = sheet.get_all_records()
    for i, r in enumerate(records):
        if str(r["user_id"]) == str(uid) and r["category"] == category and int(r["month"]) == month:
            sheet.update_cell(i + 2, 3, limit)
            return
    sheet.append_row([str(uid), category, limit, month, year])

def get_budget_for_category(uid, category, month, year):
    sheet = get_sheet(SHEET_BUDGETS)
    if not sheet: return None
    for r in sheet.get_all_records():
        if str(r["user_id"]) == str(uid) and r["category"] == category and int(r["month"]) == month:
            return {"limit": float(r["limit_amount"])}
    return None

def get_spent_in_category(uid, category, month, year):
    sheet = get_sheet(SHEET_TX)
    if not sheet: return 0
    return sum(float(r["amount"]) for r in sheet.get_all_records()
               if str(r["user_id"]) == str(uid) and r["category"] == category
               and int(r["month"]) == month and r["type"] == "expense")

# ================= ЦЕЛИ =================

@bot.message_handler(func=lambda m: m.text == "🎯 Цели")
def goals_menu(m):
    uid = m.from_user.id
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ Новая цель", callback_data="goal_new"),
        types.InlineKeyboardButton("💰 Пополнить", callback_data="goal_add"),
        types.InlineKeyboardButton("📋 Мои цели", callback_data="goal_list")
    )
    bot.send_message(m.chat.id, "🎯 Цели накопления:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "goal_new")
def goal_new(call):
    uid = call.from_user.id
    user_state[uid] = {"action": "goal_name"}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Введите название цели (например: «Телефон», «Отпуск»):", reply_markup=kb_cancel())

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("action") == "goal_name")
def goal_name_entered(m):
    uid = m.from_user.id
    if m.text == "❌ Отмена":
        user_state.pop(uid, None)
        bot.send_message(m.chat.id, "Отменено.", reply_markup=kb_main())
        return
    user_state[uid] = {"action": "goal_target", "name": m.text}
    currency = get_currency(uid)
    bot.send_message(m.chat.id, f"Введите целевую сумму ({currency}):", reply_markup=kb_cancel())

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

        sheet = get_sheet(SHEET_GOALS)
        if sheet:
            sheet.append_row([str(uid), state["name"], target, 0, currency, now_str().strftime("%d.%m.%Y"), "no"])

        bot.send_message(m.chat.id,
            f"🎯 Цель создана!\n«{state['name']}» — {format_amount(target, currency)}",
            reply_markup=kb_main()
        )
    except:
        bot.send_message(m.chat.id, "❗ Введите число.")

@bot.callback_query_handler(func=lambda c: c.data == "goal_list")
def goal_list(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    currency = get_currency(uid)

    sheet = get_sheet(SHEET_GOALS)
    if not sheet:
        bot.send_message(call.message.chat.id, "Ошибка загрузки.")
        return

    goals = [r for r in sheet.get_all_records() if str(r["user_id"]) == str(uid) and r["done"] == "no"]

    if not goals:
        bot.send_message(call.message.chat.id, "У тебя пока нет целей. Создай первую!", reply_markup=kb_main())
        return

    lines = ["*🎯 Мои цели*\n"]
    for g in goals:
        target = float(g["target"])
        saved = float(g["saved"])
        pct = min(saved / target * 100, 100) if target > 0 else 0
        remaining = target - saved
        filled = int(pct / 10)
        bar = "🟡" * filled + "⬜" * (10 - filled)
        lines.append(
            f"*{g['name']}*\n"
            f"{bar} {pct:.0f}%\n"
            f"Накоплено: {format_amount(saved, currency)} / {format_amount(target, currency)}\n"
            f"Осталось: {format_amount(remaining, currency)}"
        )

    bot.send_message(call.message.chat.id, "\n\n".join(lines), parse_mode="Markdown", reply_markup=kb_main())

@bot.callback_query_handler(func=lambda c: c.data == "goal_add")
def goal_add_select(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)

    sheet = get_sheet(SHEET_GOALS)
    if not sheet:
        bot.send_message(call.message.chat.id, "Ошибка загрузки.")
        return

    goals = [r for r in sheet.get_all_records() if str(r["user_id"]) == str(uid) and r["done"] == "no"]
    if not goals:
        bot.send_message(call.message.chat.id, "Нет активных целей.", reply_markup=kb_main())
        return

    kb = types.InlineKeyboardMarkup()
    for g in goals:
        kb.add(types.InlineKeyboardButton(g["name"], callback_data=f"goal_deposit_{g['name']}"))
    bot.send_message(call.message.chat.id, "В какую цель пополнить?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("goal_deposit_"))
def goal_deposit_chosen(call):
    uid = call.from_user.id
    goal_name = call.data[len("goal_deposit_"):]
    user_state[uid] = {"action": "goal_deposit_amount", "goal_name": goal_name}
    bot.answer_callback_query(call.id)
    currency = get_currency(uid)
    bot.send_message(call.message.chat.id, f"Введите сумму пополнения цели «{goal_name}» ({currency}):", reply_markup=kb_cancel())

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
        goal_name = state["goal_name"]
        currency = get_currency(uid)

        sheet = get_sheet(SHEET_GOALS)
        if sheet:
            records = sheet.get_all_records()
            for i, r in enumerate(records):
                if str(r["user_id"]) == str(uid) and r["name"] == goal_name and r["done"] == "no":
                    new_saved = float(r["saved"]) + amount
                    sheet.update_cell(i + 2, 4, new_saved)
                    target = float(r["target"])

                    if new_saved >= target:
                        sheet.update_cell(i + 2, 7, "yes")
                        bot.send_message(m.chat.id,
                            f"🎉 Поздравляю! Цель «{goal_name}» достигнута!\n{format_amount(new_saved, currency)} / {format_amount(target, currency)}",
                            reply_markup=kb_main()
                        )
                    else:
                        remaining = target - new_saved
                        pct = new_saved / target * 100
                        bot.send_message(m.chat.id,
                            f"💰 Пополнено: +{format_amount(amount, currency)}\n"
                            f"«{goal_name}»: {pct:.0f}% ({format_amount(new_saved, currency)} / {format_amount(target, currency)})\n"
                            f"Осталось: {format_amount(remaining, currency)}",
                            reply_markup=kb_main()
                        )
                    return

        bot.send_message(m.chat.id, "Цель не найдена.", reply_markup=kb_main())
    except:
        bot.send_message(m.chat.id, "❗ Введите число.")

# ================= НАСТРОЙКИ =================

@bot.message_handler(func=lambda m: m.text == "⚙️ Настройки")
def settings(m):
    uid = m.from_user.id
    user = get_user(uid)
    currency = user["currency"] if user else "₸"
    reminder = user["daily_reminder"] if user else "off"
    reminder_label = f"🔔 Напоминание: {reminder}" if reminder != "off" else "🔕 Напоминание: выкл"

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💱 Валюта: " + currency, callback_data="settings_currency"),
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

    sheet = get_sheet(SHEET_USERS)
    if sheet:
        cell = sheet.find(str(uid))
        if cell:
            sheet.update_cell(cell.row, 3, currency)

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

    sheet = get_sheet(SHEET_USERS)
    if sheet:
        cell = sheet.find(str(uid))
        if cell:
            sheet.update_cell(cell.row, 5, time_val)

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
    bot.send_message(call.message.chat.id, "Удалить ВСЕ твои данные? Это действие необратимо.", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ("confirm_delete", "cancel_delete"))
def handle_delete(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    if call.data == "cancel_delete":
        bot.send_message(call.message.chat.id, "Отменено.", reply_markup=kb_main())
        return

    for sheet_name in [SHEET_TX, SHEET_BUDGETS, SHEET_GOALS]:
        sheet = get_sheet(sheet_name)
        if not sheet: continue
        records = sheet.get_all_records()
        rows_to_delete = [i + 2 for i, r in enumerate(records) if str(r.get("user_id", "")) == str(uid)]
        for row in reversed(rows_to_delete):
            sheet.delete_rows(row)

    bot.send_message(call.message.chat.id, "✅ Все данные удалены.", reply_markup=kb_main())

# ================= ЕЖЕДНЕВНАЯ СВОДКА (ФОНОВЫЙ ПОТОК) =================

def daily_summary_loop():
    while True:
        try:
            tz = pytz.timezone("Asia/Almaty")
            now = datetime.now(tz)
            now_time = now.strftime("%H:%M")

            sheet_users = get_sheet(SHEET_USERS)
            sheet_tx = get_sheet(SHEET_TX)
            if not sheet_users or not sheet_tx:
                time.sleep(55)
                continue

            users = sheet_users.get_all_records()
            all_tx = sheet_tx.get_all_records()

            for user in users:
                if str(user.get("daily_reminder", "off")) != now_time:
                    continue

                uid = user["user_id"]
                currency = user.get("currency", "₸")
                n = now
                month_tx = [r for r in all_tx if str(r["user_id"]) == str(uid) and int(r["month"]) == n.month and int(r["year"]) == n.year]
                today_str = n.strftime("%d.%m.%Y")
                today_tx = [r for r in month_tx if r["date"].startswith(today_str)]

                income_today = sum(float(r["amount"]) for r in today_tx if r["type"] == "income")
                expense_today = sum(float(r["amount"]) for r in today_tx if r["type"] == "expense")
                income_month = sum(float(r["amount"]) for r in month_tx if r["type"] == "income")
                expense_month = sum(float(r["amount"]) for r in month_tx if r["type"] == "expense")

                text = (
                    f"📊 *Ежедневная сводка*\n\n"
                    f"*Сегодня ({today_str}):*\n"
                    f"➕ {format_amount(income_today, currency)}\n"
                    f"➖ {format_amount(expense_today, currency)}\n\n"
                    f"*За месяц:*\n"
                    f"➕ {format_amount(income_month, currency)}\n"
                    f"➖ {format_amount(expense_month, currency)}\n"
                    f"{'🟢' if income_month >= expense_month else '🔴'} Баланс: {format_amount(income_month - expense_month, currency)}"
                )
                try:
                    bot.send_message(uid, text, parse_mode="Markdown")
                except Exception as e:
                    print(f"Ошибка отправки сводки пользователю {uid}: {e}")

        except Exception as e:
            print(f"Ошибка daily_summary_loop: {e}")

        time.sleep(55)

threading.Thread(target=daily_summary_loop, daemon=True).start()

# ================= FLASK WEBHOOK =================

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
