from collections import Counter

from telegram import ReplyKeyboardMarkup


# UI modes are intentionally kept in memory. They are navigation state only;
# earnings and applications remain in the existing SQLite database/state.
MODES = {}

START_MODE = "start"
CABINET_MODE = "cabinet"
INCOME_MODE = "income"
APPLICATIONS_MODE = "applications"
ADMIN_MODE = "admin"


EXIT = "⬅️ Выйти"
CABINET = "👤 Личный кабинет"
AI = "🤖 Efin AI"
ADMIN_PANEL = "🛠 Админ-панель"
INCOME = "💰 Доход"
APPLICATIONS = "📥 Загрузить заявки"



def _menu(rows):
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
    )


START_MENU = _menu([
    [CABINET, AI],
])

ADMIN_START_MENU = _menu([
    [CABINET, AI],
    [ADMIN_PANEL],
])

CABINET_MENU = _menu([
    [INCOME, APPLICATIONS],
    [EXIT],
])

INCOME_MENU = _menu([
    ["📅 Сегодня", "📆 Неделя"],
    ["🗓 Месяц", "📅 Точная дата"],
    [EXIT],
])

DETAIL_MENU = _menu([
    ["📅 Сегодня", "📅 Вчера"],
    ["📆 Эта неделя", "📆 Прошлая неделя"],
    ["🗓 Этот месяц", "🗓 Прошлый месяц"],
    ["📅 Выбрать дату"],
    [EXIT],
])

APPLICATIONS_DATE_MENU = _menu([
    ["◀️ Вчера", "📅 Сегодня"],
    ["✏️ Ручной ввод"],
    ["❌ Отмена"],
    [EXIT],
])

APPLICATIONS_ACTIVE_MENU = _menu([
    ["✅ Завершить загрузку"],
    ["❌ Отменить загрузку"],
    [EXIT],
])


# Keep old names available to existing handlers/modules.
def _current_menu(user_id, bot_module):
    if user_id == bot_module.ADMIN_ID:
        mode = MODES.get(user_id, START_MODE)
        if mode == CABINET_MODE:
            return CABINET_MENU
        if mode == INCOME_MODE:
            return INCOME_MENU
        if mode == APPLICATIONS_MODE:
            return APPLICATIONS_ACTIVE_MENU
        return ADMIN_START_MENU

    mode = MODES.get(user_id, START_MODE)
    if mode == CABINET_MODE:
        return CABINET_MENU
    if mode == INCOME_MODE:
        return INCOME_MENU
    if mode == APPLICATIONS_MODE:
        return APPLICATIONS_ACTIVE_MENU
    return START_MENU



def _display_name(user):
    first = (user.first_name or "").strip()
    last = (user.last_name or "").strip()
    name = " ".join(part for part in (first, last) if part)
    return name or (user.username or "Пользователь")



def _profile_text(bot_module, user):
    from database import get_earnings_stats, get_user_earnings

    user_id = user.id
    stats = get_earnings_stats(user_id)
    earnings = get_user_earnings(user_id)

    projects = Counter(
        (earning.get("bank") or "Неизвестный проект").strip()
        for earning in earnings
    )

    top_projects = projects.most_common(3)

    lines = [
        "👤 ЛИЧНЫЙ КАБИНЕТ",
        "",
        f"Имя: {_display_name(user)}",
        f"📦 Всего встреч: {stats['count']}",
        "",
        "⭐ ЛЮБИМЫЕ ПРОЕКТЫ",
    ]

    if top_projects:
        for index, (project, count) in enumerate(top_projects, start=1):
            lines.append(f"{index}. {project} — {count} встреч")
    else:
        lines.append("Пока нет встреч.")

    lines.extend([
        "",
        "Выбери раздел ниже 👇",
    ])
    return "\n".join(lines)


async def show_cabinet(update, bot_module):
    user = update.effective_user
    MODES[user.id] = CABINET_MODE
    await update.message.reply_text(
        _profile_text(bot_module, user),
        reply_markup=CABINET_MENU,
    )


async def show_start(update, bot_module):
    user = update.effective_user
    MODES[user.id] = START_MODE
    bot_module.save_user(update)

    if user.id == bot_module.ADMIN_ID:
        text = (
            "👋 EFIN Money Bot\n\n"
            "Выбери нужный раздел 👇"
        )
        markup = ADMIN_START_MENU
    else:
        text = (
            "👋 EFIN Money Bot\n\n"
            "Выбери нужный раздел 👇"
        )
        markup = START_MENU

    await update.message.reply_text(text, reply_markup=markup)


async def _go_cabinet(update, bot_module):
    # Close navigation-only sessions before returning to the cabinet.
    user_id = update.effective_user.id
    bot_module.finish_detail_session(user_id)
    bot_module.remove_pending_application(user_id)
    bot_module.finish_manual_application_date(user_id)
    bot_module.finish_manual_import_date(user_id)
    bot_module.finish_import_session(user_id)
    MODES[user_id] = CABINET_MODE
    await show_cabinet(update, bot_module)


async def _go_start(update, bot_module):
    user_id = update.effective_user.id
    bot_module.finish_detail_session(user_id)
    bot_module.remove_pending_application(user_id)
    bot_module.finish_manual_application_date(user_id)
    bot_module.finish_manual_import_date(user_id)
    bot_module.finish_import_session(user_id)
    MODES[user_id] = START_MODE
    await update.message.reply_text(
        "Главное меню 👇",
        reply_markup=(ADMIN_START_MENU if user_id == bot_module.ADMIN_ID else START_MENU),
    )


async def _go_income(update, bot_module):
    user_id = update.effective_user.id
    MODES[user_id] = INCOME_MODE
    await bot_module.show_income(update)


async def _handle_navigation(update, context, original_handler, bot_module):
    if not update.message or not update.message.text:
        return await original_handler(update, context)

    user_id = update.effective_user.id
    text = update.message.text.strip()
    mode = MODES.get(user_id, START_MODE)

    # «Личный кабинет» — кнопка верхнего уровня. Режим хранится в памяти и
    # может разойтись с клавиатурой (например, после «⬅️ Назад» из админ-панели
    # в bot.py режим остаётся ADMIN_MODE, а на экране уже стартовое меню).
    # Поэтому кнопка работает из любого режима и заодно сбрасывает старые сессии.
    if text == CABINET:
        if mode == START_MODE:
            await show_cabinet(update, bot_module)
        else:
            await _go_cabinet(update, bot_module)
        return

    # Админ-панель доступна только со стартового экрана.
    if text == ADMIN_PANEL and user_id == bot_module.ADMIN_ID and mode == START_MODE:
        MODES[user_id] = ADMIN_MODE
        await original_handler(update, context)
        return

    # Global exit. It is checked before the old handler so every functional
    # screen has a safe way back to a higher-level menu.
    if text == EXIT:
        if mode == INCOME_MODE:
            await _go_cabinet(update, bot_module)
            return
        if mode == APPLICATIONS_MODE:
            await _go_cabinet(update, bot_module)
            return
        if mode == CABINET_MODE or mode == ADMIN_MODE:
            await _go_start(update, bot_module)
            return
        await _go_start(update, bot_module)
        return

    if mode == CABINET_MODE:
        if text == INCOME:
            await _go_income(update, bot_module)
            return

        if text == APPLICATIONS:
            MODES[user_id] = APPLICATIONS_MODE
            await bot_module.start_import(update, context)
            return

        # Efin AI is intentionally handled by ai_feature.py if the user
        # types it manually, but it is not shown in the cabinet keyboard.
        return await original_handler(update, context)

    if mode == INCOME_MODE:
        # Exact-date detail has its own internal state and old implementation.
        if bot_module.is_detail_session_active(user_id):
            return await original_handler(update, context)

        if text == "📅 Сегодня":
            await bot_module.show_today(update)
            return

        if text == "📆 Неделя":
            await bot_module.show_week(update)
            return

        if text == "🗓 Месяц":
            await bot_module.show_month(update)
            return

        if text == "📅 Точная дата":
            await bot_module.ask_for_detail_date(update)
            return

        return await original_handler(update, context)

    if mode == APPLICATIONS_MODE:
        # During an active import, keep the old import state machine intact.
        # Only the new exit button is intercepted here.
        return await original_handler(update, context)

    # Admin panel keeps its existing functionality. Its own buttons are
    # handled by bot.py and its existing callbacks.
    if mode == ADMIN_MODE:
        return await original_handler(update, context)

    # Start screen: let the existing Efin AI wrapper see its button.
    return await original_handler(update, context)



def install(bot_module):
    bot_module.START_MENU = START_MENU
    bot_module.ADMIN_START_MENU = ADMIN_START_MENU
    bot_module.CABINET_MENU = CABINET_MENU
    bot_module.INCOME_MENU = INCOME_MENU
    bot_module.DETAIL_MENU = DETAIL_MENU
    bot_module.IMPORT_DATE_MENU = APPLICATIONS_DATE_MENU
    bot_module.IMPORT_ACTIVE_MENU = APPLICATIONS_ACTIVE_MENU

    # Replace get_menu so existing income/application messages automatically
    # receive the correct current-level keyboard.
    def dynamic_get_menu(user_id):
        return _current_menu(user_id, bot_module)

    bot_module.get_menu = dynamic_get_menu

    original_start = bot_module.start
    original_handler = bot_module.handle_message

    async def wrapped_start(update, context):
        # Preserve /start as a reliable reset point.
        try:
            return await show_start(update, bot_module)
        except Exception:
            return await original_start(update, context)

    async def wrapped_handler(update, context):
        user_id = update.effective_user.id if update.effective_user else None
        if user_id is None:
            return await original_handler(update, context)
        return await _handle_navigation(
            update,
            context,
            original_handler,
            bot_module,
        )

    bot_module.start = wrapped_start
    bot_module.handle_message = wrapped_handler

    # The old import functions create their own date/active keyboards. Wrap
    # them so the mandatory exit button is present there as well.
    original_ask_manual_import_date = bot_module.ask_manual_import_date

    async def wrapped_ask_manual_import_date(update, user_id):
        await original_ask_manual_import_date(update, user_id)
        await update.message.reply_text(
            "⬅️ Выйти из загрузки можно кнопкой ниже.",
            reply_markup=APPLICATIONS_DATE_MENU,
        )

    bot_module.ask_manual_import_date = wrapped_ask_manual_import_date

    # If the existing import code switches back to its own keyboard, the
    # dynamic menu still handles all normal navigation; the explicit exit is
    # intercepted before the old handler.
