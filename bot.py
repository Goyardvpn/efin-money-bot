import asyncio
from datetime import date, datetime, timedelta, time
from zoneinfo import ZoneInfo

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
from zoneinfo import ZoneInfo

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
import re

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import BOT_TOKEN, ADMIN_ID

from database import (
    init_db,
    register_user,
    add_earning,
    earning_exists,
    delete_all_user_earnings,
    delete_user_earnings_by_date,
    get_earnings_stats,
    get_today_stats,
    get_next_advance,
    get_next_settlement,
    get_week_income,
    get_month_income,
    get_user_earnings,
    calculate_periods,
    get_users,
    get_global_stats,
    add_tariff,
    update_tariff,
    delete_tariff,
    get_tariff,
    get_all_rates,
    recalculate_earnings,
)

from parser import parse_message


# =========================================================
# МЕНЮ ПОЛЬЗОВАТЕЛЯ
# =========================================================

USER_MENU = ReplyKeyboardMarkup(
    [
        ["💰 Заработок", "📅 Сегодня"],
        ["📆 Неделя", "🗓 Месяц"],
        ["📥 Загрузить заявки", "📥 Последние заявки"],
        ["⚙️ Настройки"],
    ],
    resize_keyboard=True,
)


# =========================================================
# МЕНЮ АДМИНИСТРАТОРА
# =========================================================

ADMIN_MENU = ReplyKeyboardMarkup(
    [
        ["💰 Заработок", "📅 Сегодня"],
        ["📆 Неделя", "🗓 Месяц"],
        ["📥 Загрузить заявки", "📥 Последние заявки"],
        ["⚙️ Настройки"],
        ["🛠 Админ-панель"],
    ],
    resize_keyboard=True,
)


# =========================================================
# МЕНЮ АДМИН-ПАНЕЛИ
# =========================================================

ADMIN_PANEL_MENU = ReplyKeyboardMarkup(
    [
        ["👥 Пользователи"],
        ["📊 Общая статистика"],
        ["📋 Все заявки"],
        ["⚙️ Тарифы"],
        ["🔄 Пересчитать заявки"],
        ["💸 Корректировка"],
        ["📢 Рассылка"],
        ["⬅️ Назад"],
    ],
    resize_keyboard=True,
)


# =========================================================
# МЕНЮ ДОХОДА
# =========================================================

INCOME_MENU = ReplyKeyboardMarkup(
    [
        ["🔎 Детализация дохода"],
        ["⬅️ Назад"],
    ],
    resize_keyboard=True,
)


# =========================================================
# МЕНЮ ДЕТАЛИЗАЦИИ
# =========================================================

DETAIL_MENU = ReplyKeyboardMarkup(
    [
        ["📅 Сегодня", "📅 Вчера"],
        ["📆 Эта неделя", "📆 Прошлая неделя"],
        ["🗓 Этот месяц", "🗓 Прошлый месяц"],
        ["📆 Выбрать дату"],
        ["⬅️ Назад"],
    ],
    resize_keyboard=True,
)


# =========================================================
# МЕНЮ ВЫБОРА ДАТЫ ОДИНОЧНОЙ ЗАЯВКИ
# =========================================================

APPLICATION_DATE_MENU = ReplyKeyboardMarkup(
    [
        ["◀️ Вчера", "📅 Сегодня"],
        ["✏️ Ручной ввод"],
        ["❌ Ошибочная отправка"],
    ],
    resize_keyboard=True,
)


# =========================================================
# МЕНЮ ВЫБОРА ДАТЫ МАССОВОЙ ЗАГРУЗКИ
# =========================================================

IMPORT_DATE_MENU = ReplyKeyboardMarkup(
    [
        ["◀️ Вчера", "📅 Сегодня"],
        ["✏️ Ручной ввод"],
        ["❌ Отмена"],
    ],
    resize_keyboard=True,
)


# =========================================================
# МЕНЮ АКТИВНОЙ МАССОВОЙ ЗАГРУЗКИ
# =========================================================

IMPORT_ACTIVE_MENU = ReplyKeyboardMarkup(
    [
        ["✅ Завершить загрузку"],
        ["❌ Отменить загрузку"],
    ],
    resize_keyboard=True,
)


# =========================================================
# МЕНЮ АДМИНСКОГО УДАЛЕНИЯ ПО ДАТЕ
# =========================================================

ADMIN_DELETE_DATE_MENU = ReplyKeyboardMarkup(
    [
        ["◀️ Вчера", "📅 Сегодня"],
        ["✏️ Ввести дату"],
        ["❌ Отмена"],
    ],
    resize_keyboard=True,
)


# =========================================================
# СОСТОЯНИЯ МАССОВОЙ ЗАГРУЗКИ
# =========================================================

IMPORT_SESSIONS = {}


def create_import_session(
    user_id: int,
    selected_date: date | None = None,
):
    IMPORT_SESSIONS[user_id] = {
        "active": True,
        "selected_date": selected_date,
        "received": 0,
        "added": 0,
        "duplicates": 0,
        "not_payable": 0,
        "unrecognized": 0,
        "total_earned": 0,
    }


def get_import_session(user_id: int):
    return IMPORT_SESSIONS.get(user_id)


def finish_import_session(user_id: int):
    return IMPORT_SESSIONS.pop(
        user_id,
        None,
    )


# =========================================================
# СОСТОЯНИЕ РУЧНОГО ВВОДА ДАТЫ МАССОВОЙ ЗАГРУЗКИ
# =========================================================

MANUAL_IMPORT_DATE = {}


def start_manual_import_date(user_id: int):
    MANUAL_IMPORT_DATE[user_id] = True


def finish_manual_import_date(user_id: int):
    MANUAL_IMPORT_DATE.pop(
        user_id,
        None,
    )


def is_manual_import_date_active(user_id: int):
    return user_id in MANUAL_IMPORT_DATE


# =========================================================
# СОСТОЯНИЕ ОЖИДАЮЩЕЙ ОДИНОЧНОЙ ЗАЯВКИ
# =========================================================

PENDING_APPLICATIONS = {}


def create_pending_application(
    user_id: int,
    result: dict,
):
    PENDING_APPLICATIONS[user_id] = {
        "result": result,
        "waiting_date": True,
    }


def get_pending_application(user_id: int):
    return PENDING_APPLICATIONS.get(user_id)


def remove_pending_application(user_id: int):
    return PENDING_APPLICATIONS.pop(
        user_id,
        None,
    )


# =========================================================
# СОСТОЯНИЕ ДЕТАЛИЗАЦИИ
# =========================================================

DETAIL_SESSIONS = {}


def start_detail_session(user_id: int):
    DETAIL_SESSIONS[user_id] = True


def finish_detail_session(user_id: int):
    DETAIL_SESSIONS.pop(
        user_id,
        None,
    )


def is_detail_session_active(user_id: int):
    return user_id in DETAIL_SESSIONS


# =========================================================
# СОСТОЯНИЕ РУЧНОГО ВВОДА ДАТЫ ОДИНОЧНОЙ ЗАЯВКИ
# =========================================================

MANUAL_APPLICATION_DATE = {}


def start_manual_application_date(user_id: int):
    MANUAL_APPLICATION_DATE[user_id] = True


def finish_manual_application_date(user_id: int):
    MANUAL_APPLICATION_DATE.pop(
        user_id,
        None,
    )


def is_manual_application_date_active(user_id: int):
    return user_id in MANUAL_APPLICATION_DATE


# =========================================================
# СОСТОЯНИЕ УПРАВЛЕНИЯ ТАРИФОМ
# =========================================================

TARIFF_SESSIONS = {}


def start_tariff_session(user_id, mode, trigger=None):
    TARIFF_SESSIONS[user_id] = {
        "mode": mode,
        "trigger": trigger,
        "step": "trigger" if mode == "add" else "name",
        "name": None,
        "advance": None,
        "settlement": None,
    }


def finish_tariff_session(user_id):
    TARIFF_SESSIONS.pop(user_id, None)


def get_tariff_session(user_id):
    return TARIFF_SESSIONS.get(user_id)


# =========================================================
# СОСТОЯНИЕ РАССЫЛКИ
# =========================================================

BROADCAST_SESSIONS = {}


def start_broadcast_session(admin_id: int):
    BROADCAST_SESSIONS[admin_id] = {
        "text": None,
    }


def finish_broadcast_session(admin_id: int):
    return BROADCAST_SESSIONS.pop(
        admin_id,
        None,
    )


def get_broadcast_session(admin_id: int):
    return BROADCAST_SESSIONS.get(admin_id)


# =========================================================
# СОСТОЯНИЕ ПЕРЕРАСЧЁТА
# =========================================================

RECALC_SESSIONS = {}


def start_recalc_session(admin_id):
    RECALC_SESSIONS[admin_id] = {
        "step": "start_date",
        "start_date": None,
        "end_date": None,
    }


def finish_recalc_session(admin_id):
    RECALC_SESSIONS.pop(admin_id, None)


def get_recalc_session(admin_id):
    return RECALC_SESSIONS.get(admin_id)


def build_recalc_confirmation_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔄 Пересчитать",
                callback_data="admin_recalc_confirm",
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Отмена",
                callback_data="admin_recalc_cancel",
            )
        ],
    ])


def build_broadcast_confirmation_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Отправить всем",
                callback_data="admin_broadcast_confirm",
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Отмена",
                callback_data="admin_broadcast_cancel",
            )
        ],
    ])


async def handle_recalc_text(update, admin_id, text):
    session = get_recalc_session(admin_id)

    if not session:
        return False

    if text == "❌ Отмена":
        finish_recalc_session(admin_id)
        await update.message.reply_text(
            "❌ Перерасчёт отменён.",
            reply_markup=ADMIN_PANEL_MENU,
        )
        return True

    if session["step"] == "start_date":
        try:
            selected = datetime.strptime(
                text.strip(),
                "%d.%m.%Y",
            ).date()
        except ValueError:
            await update.message.reply_text(
                "❌ Неверная дата. Формат: ДД.ММ.ГГГГ"
            )
            return True

        session["start_date"] = selected
        session["step"] = "end_date"

        await update.message.reply_text(
            "📅 Теперь введи конечную дату в формате ДД.ММ.ГГГГ."
        )
        return True

    if session["step"] == "end_date":
        try:
            selected = datetime.strptime(
                text.strip(),
                "%d.%m.%Y",
            ).date()
        except ValueError:
            await update.message.reply_text(
                "❌ Неверная дата. Формат: ДД.ММ.ГГГГ"
            )
            return True

        if selected < session["start_date"]:
            await update.message.reply_text(
                "❌ Конечная дата не может быть раньше начальной."
            )
            return True

        session["end_date"] = selected

        await update.message.reply_text(
            "⚠️ ПЕРЕРАСЧЁТ ЗАЯВОК\n\n"
            f"📅 Период: {session['start_date'].strftime('%d.%m.%Y')} — "
            f"{selected.strftime('%d.%m.%Y')}\n\n"
            "Сохранённые заявки будут пересчитаны по текущим тарифам.\n"
            "Заявки с отключённым тарифом останутся без изменений.\n\n"
            "Продолжить?",
            reply_markup=build_recalc_confirmation_keyboard(),
        )
        return True

    return False


async def handle_broadcast_text(update, admin_id, text):
    session = get_broadcast_session(admin_id)

    if not session:
        return False

    if text == "❌ Отмена":
        finish_broadcast_session(admin_id)
        await update.message.reply_text(
            "❌ Рассылка отменена.",
            reply_markup=ADMIN_PANEL_MENU,
        )
        return True

    message_text = text.strip()

    if not message_text:
        await update.message.reply_text(
            "❌ Сообщение не может быть пустым."
        )
        return True

    session["text"] = message_text

    users = get_users()
    recipients = [
        user
        for user in users
        if user["user_id"] != ADMIN_ID
        and not user["is_blocked"]
    ]

    await update.message.reply_text(
        "📢 ПРЕДПРОСМОТР РАССЫЛКИ\n\n"
        f"{message_text}\n\n"
        "────────────────\n"
        f"👥 Получателей: {len(recipients)}\n\n"
        "Отправить сообщение всем?",
        reply_markup=build_broadcast_confirmation_keyboard(),
    )

    return True


def build_tariffs_keyboard():
    rows = [
        [
            InlineKeyboardButton(
                "➕ Добавить тариф",
                callback_data="admin_tariff_add",
            )
        ]
    ]

    for tariff in get_all_rates():
        rows.append([
            InlineKeyboardButton(
                f"✏️ {tariff['trigger']} — {tariff['name']}",
                callback_data=f"admin_tariff_edit:{tariff['trigger']}",
            )
        ])
        rows.append([
            InlineKeyboardButton(
                f"🗑 Отключить {tariff['trigger']}",
                callback_data=f"admin_tariff_delete:{tariff['trigger']}",
            )
        ])

    rows.append([
        InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="admin_panel",
        )
    ])

    return InlineKeyboardMarkup(rows)


async def show_tariffs(query):
    tariffs = get_all_rates()

    text = "⚙️ ТАРИФЫ\n\n"

    if not tariffs:
        text += "Тарифов пока нет.\n\n"
    else:
        for tariff in tariffs:
            total = tariff["advance"] + tariff["settlement"]
            text += (
                f"🔹 {tariff['trigger']} — {tariff['name']}\n"
                f"   💵 Аванс: {tariff['advance']} ₽\n"
                f"   🟠 Сверка: {tariff['settlement']} ₽\n"
                f"   💰 Всего: {total} ₽\n\n"
            )

    text += "Выбери действие:"

    await query.edit_message_text(
        text,
        reply_markup=build_tariffs_keyboard(),
    )


async def handle_tariff_text(update, user_id, text):
    session = get_tariff_session(user_id)

    if not session:
        return False

    if text == "❌ Отмена":
        finish_tariff_session(user_id)
        await update.message.reply_text(
            "❌ Изменение тарифа отменено.",
            reply_markup=ADMIN_PANEL_MENU,
        )
        return True

    mode = session["mode"]

    if mode == "add" and session["step"] == "trigger":
        trigger = text.strip().upper()

        if not re.fullmatch(r"[А-ЯЁ]{2}", trigger):
            await update.message.reply_text(
                "❌ Код должен состоять ровно из двух русских букв.\n\n"
                "Например: НБ"
            )
            return True

        if get_tariff(trigger):
            await update.message.reply_text(
                "⚠️ Такой код уже существует.\n"
                "Выбери другой код или используй редактирование."
            )
            return True

        session["trigger"] = trigger
        session["step"] = "name"

        await update.message.reply_text(
            f"🏦 Код: {trigger}\n\n"
            "Теперь напиши название банка/продукта:"
        )
        return True

    if session["step"] == "name":
        name = text.strip()

        if not name:
            await update.message.reply_text("❌ Название не может быть пустым.")
            return True

        session["name"] = name
        session["step"] = "advance"

        await update.message.reply_text(
            "💵 Напиши сумму аванса в рублях.\n\n"
            "Например: 300"
        )
        return True

    if session["step"] == "advance":
        if not text.strip().isdigit():
            await update.message.reply_text(
                "❌ Введи целое число рублей. Например: 300"
            )
            return True

        session["advance"] = int(text.strip())
        session["step"] = "settlement"

        await update.message.reply_text(
            "🟠 Напиши сумму сверки в рублях.\n\n"
            "Например: 100"
        )
        return True

    if session["step"] == "settlement":
        if not text.strip().isdigit():
            await update.message.reply_text(
                "❌ Введи целое число рублей. Например: 100"
            )
            return True

        session["settlement"] = int(text.strip())

        if mode == "add":
            add_tariff(
                session["trigger"],
                session["name"],
                session["advance"],
                session["settlement"],
            )
            action = "добавлен"
        else:
            update_tariff(
                session["trigger"],
                name=session["name"],
                advance=session["advance"],
                settlement=session["settlement"],
            )
            action = "изменён"

        trigger = session["trigger"]
        tariff = get_tariff(trigger)
        finish_tariff_session(user_id)

        await update.message.reply_text(
            "✅ ТАРИФ СОХРАНЁН\n\n"
            f"🔹 {tariff['trigger']} — {tariff['name']}\n"
            f"💵 Аванс: {tariff['advance']} ₽\n"
            f"🟠 Сверка: {tariff['settlement']} ₽\n"
            f"💰 Всего: {tariff['advance'] + tariff['settlement']} ₽\n\n"
            f"Тариф {action}.",
            reply_markup=ADMIN_PANEL_MENU,
        )
        return True

    return False


# =========================================================
# СОСТОЯНИЯ АДМИНСКОГО УДАЛЕНИЯ
# =========================================================

ADMIN_MANUAL_DELETE_DATE = {}

ADMIN_PENDING_DATE_DELETE = {}


def start_admin_manual_delete_date(
    admin_id: int,
    target_user_id: int,
):
    ADMIN_MANUAL_DELETE_DATE[admin_id] = target_user_id


def finish_admin_manual_delete_date(
    admin_id: int,
):
    ADMIN_MANUAL_DELETE_DATE.pop(
        admin_id,
        None,
    )


def get_admin_manual_delete_target(
    admin_id: int,
):
    return ADMIN_MANUAL_DELETE_DATE.get(
        admin_id
    )


def set_admin_pending_date_delete(
    admin_id: int,
    target_user_id: int,
    selected_date: date,
):
    ADMIN_PENDING_DATE_DELETE[admin_id] = {
        "target_user_id": target_user_id,
        "date": selected_date,
    }


def get_admin_pending_date_delete(
    admin_id: int,
):
    return ADMIN_PENDING_DATE_DELETE.get(
        admin_id
    )


def finish_admin_pending_date_delete(
    admin_id: int,
):
    ADMIN_PENDING_DATE_DELETE.pop(
        admin_id,
        None,
    )


# =========================================================
# МЕНЮ ПОЛЬЗОВАТЕЛЯ
# =========================================================

def get_menu(user_id):
    if user_id == ADMIN_ID:
        return ADMIN_MENU

    return USER_MENU


# =========================================================
# РЕГИСТРАЦИЯ ПОЛЬЗОВАТЕЛЯ
# =========================================================

def save_user(update: Update):
    user = update.effective_user

    if not user:
        return

    register_user(
        user_id=user.id,
        username=user.username or "",
        first_name=user.first_name or "",
        last_name=user.last_name or "",
    )


# =========================================================
# УДАЛЕНИЕ СООБЩЕНИЯ
# =========================================================

async def delete_user_message(update: Update):
    if not update.message:
        return

    try:
        await update.message.delete()

    except Exception as error:
        print(
            f"⚠️ Не удалось удалить сообщение: {error}"
        )


# =========================================================
# ФОРМАТ ДАТЫ
# =========================================================

def format_date(value):
    if not value:
        return "—"

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)

        except ValueError:
            return "—"

    if isinstance(value, datetime):
        value = value.date()

    return value.strftime("%d.%m.%Y")


# =========================================================
# НАЗВАНИЯ МЕСЯЦЕВ
# =========================================================

MONTH_NAMES = {
    1: "январь",
    2: "февраль",
    3: "март",
    4: "апрель",
    5: "май",
    6: "июнь",
    7: "июль",
    8: "август",
    9: "сентябрь",
    10: "октябрь",
    11: "ноябрь",
    12: "декабрь",
}


def format_month(value):
    if not value:
        return "—"

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)

        except ValueError:
            return "—"

    if isinstance(value, datetime):
        value = value.date()

    return (
        f"{MONTH_NAMES[value.month]} "
        f"{value.year}"
    )


# =========================================================
# ПРЕОБРАЗОВАНИЕ В ДАТУ ЗАЯВКИ
# =========================================================

def make_application_datetime(
    selected_date: date,
):
    return datetime.combine(
        selected_date,
        time.min,
    )


# =========================================================
# СОХРАНЕНИЕ ПОДТВЕРЖДЁННОЙ ОДИНОЧНОЙ ЗАЯВКИ
# =========================================================

async def save_confirmed_application(
    update: Update,
    user_id: int,
    selected_date: date,
):
    pending = get_pending_application(
        user_id
    )

    if not pending:
        await update.message.reply_text(
            "⚠️ Заявка для подтверждения "
            "не найдена.",
            reply_markup=get_menu(user_id),
        )

        return

    result = pending["result"]

    created_at = make_application_datetime(
        selected_date
    )

    added = add_earning(
        user_id=user_id,
        operation_id=result["operation_id"],
        trigger=result["trigger"],
        bank=result["name"],
        status=result["status"],
        advance=result["advance"],
        settlement=result["settlement"],
        total=result["total"],
        created_at=created_at,
        original_text=result["original_text"],
    )

    remove_pending_application(user_id)

    finish_manual_application_date(user_id)

    if not added:
        await update.message.reply_text(
            "♻️ Эта заявка уже была добавлена.\n\n"
            f"📄 Заявка: "
            f"{result['operation_id']}",
            reply_markup=get_menu(user_id),
        )

        return

    periods = calculate_periods(
        created_at
    )

    message = (
        "✅ ЗАЯВКА ДОБАВЛЕНА\n\n"
        f"📄 Заявка: "
        f"{result['operation_id']}\n"
        f"🏦 {result['name']}\n"
        f"📌 Статус: "
        f"{result['status']}\n\n"
        f"📅 Дата заявки: "
        f"{format_date(selected_date)}\n\n"
        f"💵 Аванс: "
        f"{result['advance']} ₽\n"
        f"📅 Сверка: "
        f"{result['settlement']} ₽\n"
        f"💰 За заявку: "
        f"{result['total']} ₽\n"
    )

    if periods:
        message += (
            "\n━━━━━━━━━━━━━━\n\n"
            "🔵 АВАНС\n"
            f"📦 За неделю: "
            f"{format_date(periods['week_start'])}"
            f" – "
            f"{format_date(periods['week_end'])}\n"
            f"💳 Выплата: "
            f"{format_date(periods['advance_payout_start'])}"
            f" – "
            f"{format_date(periods['advance_payout_end'])}\n\n"
            "🟠 СВЕРКА\n"
            f"📅 За: "
            f"{format_month(periods['settlement_month'])}\n"
            f"💳 Выплата: "
            f"{format_date(periods['settlement_payout_start'])}"
            f" – "
            f"{format_date(periods['settlement_payout_end'])}\n"
        )

    stats = get_earnings_stats(
        user_id
    )

    message += (
        "\n━━━━━━━━━━━━━━\n"
        f"💰 Всего начислено: "
        f"{stats['total']} ₽"
    )

    await update.message.reply_text(
        message,
        reply_markup=get_menu(user_id),
    )


# =========================================================
# ЗАПРОС ДАТЫ ОДИНОЧНОЙ ЗАЯВКИ
# =========================================================

async def ask_application_date(
    update: Update,
    user_id: int,
):
    pending = get_pending_application(
        user_id
    )

    if not pending:
        return

    result = pending["result"]

    await update.message.reply_text(
        "📅 УКАЖИ ДАТУ ЗАЯВКИ\n\n"
        f"📄 {result['operation_id']}\n"
        f"🏦 {result['name']}\n"
        f"📌 {result['status']}\n\n"
        "Я НЕ буду брать дату из сообщения "
        "EfinAgentBot.\n\n"
        "Выбери фактическую дату заявки:",
        reply_markup=APPLICATION_DATE_MENU,
    )


# =========================================================
# РУЧНОЙ ВВОД ДАТЫ ОДИНОЧНОЙ ЗАЯВКИ
# =========================================================

async def ask_manual_application_date(
    update: Update,
    user_id: int,
):
    start_manual_application_date(
        user_id
    )

    await update.message.reply_text(
        "✏️ РУЧНОЙ ВВОД\n\n"
        "Напиши дату заявки в формате:\n"
        "ДД.ММ.ГГГГ\n\n"
        "Например:\n"
        "16.09.2026",
        reply_markup=ReplyKeyboardMarkup(
            [
                ["❌ Ошибочная отправка"],
            ],
            resize_keyboard=True,
        ),
    )


# =========================================================
# ОБРАБОТКА РУЧНОЙ ДАТЫ ОДИНОЧНОЙ ЗАЯВКИ
# =========================================================

async def handle_manual_application_date(
    update: Update,
    text: str,
):
    user_id = update.effective_user.id

    try:
        selected_date = datetime.strptime(
            text.strip(),
            "%d.%m.%Y",
        ).date()

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат даты.\n\n"
            "Напиши так:\n"
            "16.09.2026",
            reply_markup=ReplyKeyboardMarkup(
                [
                    ["❌ Ошибочная отправка"],
                ],
                resize_keyboard=True,
            ),
        )

        return

    finish_manual_application_date(
        user_id
    )

    await save_confirmed_application(
        update,
        user_id,
        selected_date,
    )


# =========================================================
# ОТМЕНА ОДИНОЧНОЙ ЗАЯВКИ
# =========================================================

async def cancel_pending_application(
    update: Update,
    user_id: int,
):
    pending = remove_pending_application(
        user_id
    )

    finish_manual_application_date(
        user_id
    )

    if pending:
        operation_id = pending["result"][
            "operation_id"
        ]

        await update.message.reply_text(
            "❌ ОТПРАВКА ОТМЕНЕНА\n\n"
            f"📄 Заявка: {operation_id}\n\n"
            "Я её не сохранил в базу.",
            reply_markup=get_menu(user_id),
        )

    else:
        await update.message.reply_text(
            "❌ Отменено.",
            reply_markup=get_menu(user_id),
        )


# =========================================================
# РАСЧЁТ ДЕТАЛИЗАЦИИ
# =========================================================

def get_income_details(
    user_id: int,
    selected_date: date,
):
    earnings = get_user_earnings(
        user_id
    )

    selected_periods = calculate_periods(
        selected_date
    )

    if not selected_periods:
        return None

    advance_items = []
    settlement_items = []

    without_date = 0

    for earning in earnings:
        created_at = earning["created_at"]

        if not created_at:
            without_date += 1
            continue

        periods = calculate_periods(
            created_at
        )

        if not periods:
            continue

        if (
            periods["week_start"]
            == selected_periods["week_start"]
            and earning["advance"] > 0
        ):
            advance_items.append(
                earning
            )

        if (
            periods["settlement_month"]
            == selected_periods["settlement_month"]
            and earning["settlement"] > 0
        ):
            settlement_items.append(
                earning
            )

    advance_items.sort(
        key=lambda item: (
            str(item["created_at"]),
            item["id"],
        )
    )

    settlement_items.sort(
        key=lambda item: (
            str(item["created_at"]),
            item["id"],
        )
    )

    return {
        "week_start": selected_periods[
            "week_start"
        ],
        "week_end": selected_periods[
            "week_end"
        ],
        "advance_payout_start": selected_periods[
            "advance_payout_start"
        ],
        "advance_payout_end": selected_periods[
            "advance_payout_end"
        ],
        "advance_items": advance_items,
        "advance_count": len(
            advance_items
        ),
        "advance_amount": sum(
            item["advance"]
            for item in advance_items
        ),
        "settlement_month": selected_periods[
            "settlement_month"
        ],
        "settlement_payout_start": selected_periods[
            "settlement_payout_start"
        ],
        "settlement_payout_end": selected_periods[
            "settlement_payout_end"
        ],
        "settlement_items": settlement_items,
        "settlement_count": len(
            settlement_items
        ),
        "settlement_amount": sum(
            item["settlement"]
            for item in settlement_items
        ),
        "without_date": without_date,
    }


# =========================================================
# ФОРМАТ ЗАЯВКИ ДЛЯ ДЕТАЛИЗАЦИИ
# =========================================================

def format_detail_item(
    index,
    earning,
    amount_field,
    amount_name,
):
    return (
        f"{index}. 📄 "
        f"{earning['operation_id']}\n"
        f"   🏦 {earning['bank']}\n"
        f"   📅 {format_date(earning['created_at'])}\n"
        f"   📌 {earning['status']}\n"
        f"   💵 {amount_name}: "
        f"{earning[amount_field]} ₽\n"
    )


# =========================================================
# РАЗБИВКА ДЛИННОГО ТЕКСТА
# =========================================================

def split_text(
    text,
    max_length=3800,
):
    if len(text) <= max_length:
        return [text]

    parts = []
    current = ""

    for line in text.splitlines(
        keepends=True
    ):
        if (
            len(current) + len(line)
            > max_length
        ):
            if current:
                parts.append(current)

            current = line

        else:
            current += line

    if current:
        parts.append(current)

    return parts


# =========================================================
# ПОКАЗ ДЕТАЛИЗАЦИИ
# =========================================================

async def show_income_details(
    update: Update,
    user_id: int,
    selected_date: date,
):
    details = get_income_details(
        user_id,
        selected_date,
    )

    if not details:
        await update.message.reply_text(
            "❌ Не удалось определить период.",
            reply_markup=DETAIL_MENU,
        )

        start_detail_session(user_id)

        return

    start_detail_session(user_id)

    await update.message.reply_text(
        "🔎 ДЕТАЛИЗАЦИЯ ДОХОДА\n\n"
        f"📅 Выбранная дата: "
        f"{format_date(selected_date)}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🔵 АВАНС\n\n"
        f"📦 Неделя заявок: "
        f"{format_date(details['week_start'])}"
        f" – "
        f"{format_date(details['week_end'])}\n"
        f"💳 Выплата: "
        f"{format_date(details['advance_payout_start'])}"
        f" – "
        f"{format_date(details['advance_payout_end'])}\n\n"
        f"📦 Заявок: "
        f"{details['advance_count']}\n"
        f"💵 Сумма аванса: "
        f"{details['advance_amount']} ₽",
    )

    if details["advance_items"]:
        text = (
            "🔵 ЗАЯВКИ, ПОПАВШИЕ В АВАНС\n\n"
        )

        for index, earning in enumerate(
            details["advance_items"],
            start=1,
        ):
            text += format_detail_item(
                index,
                earning,
                "advance",
                "Аванс",
            )

            text += "\n"

        text += (
            "━━━━━━━━━━━━━━\n"
            f"💵 ИТОГО АВАНС: "
            f"{details['advance_amount']} ₽"
        )

        for part in split_text(text):
            await update.message.reply_text(
                part
            )

    else:
        await update.message.reply_text(
            "🔵 В выбранной неделе "
            "нет заявок, попадающих в аванс."
        )

    await update.message.reply_text(
        "🟠 СВЕРКА\n\n"
        f"📅 Месяц заявок: "
        f"{format_month(details['settlement_month'])}\n"
        f"💳 Выплата: "
        f"{format_date(details['settlement_payout_start'])}"
        f" – "
        f"{format_date(details['settlement_payout_end'])}\n\n"
        f"📦 Заявок: "
        f"{details['settlement_count']}\n"
        f"💵 Сумма сверки: "
        f"{details['settlement_amount']} ₽",
    )

    if details["settlement_items"]:
        text = (
            "🟠 ЗАЯВКИ, ПОПАВШИЕ В СВЕРКУ\n\n"
        )

        for index, earning in enumerate(
            details["settlement_items"],
            start=1,
        ):
            text += format_detail_item(
                index,
                earning,
                "settlement",
                "Сверка",
            )

            text += "\n"

        text += (
            "━━━━━━━━━━━━━━\n"
            f"💵 ИТОГО СВЕРКА: "
            f"{details['settlement_amount']} ₽"
        )

        for part in split_text(text):
            await update.message.reply_text(
                part
            )

    else:
        await update.message.reply_text(
            "🟠 В выбранном месяце "
            "нет заявок, попадающих в сверку."
        )

    if details["without_date"]:
        await update.message.reply_text(
            "⚠️ В базе есть заявки без даты.\n\n"
            f"Количество: "
            f"{details['without_date']}\n\n"
            "Такие заявки нельзя автоматически "
            "отнести к конкретной неделе или месяцу."
        )

    await update.message.reply_text(
        "Готово. Выбери другой период 👇",
        reply_markup=DETAIL_MENU,
    )


# =========================================================
# БЫСТРЫЙ ВЫБОР ПЕРИОДА
# =========================================================

def get_period_date(text):
    today = datetime.now(MOSCOW_TZ).date()

    if text == "📅 Сегодня":
        return today

    if text == "📅 Вчера":
        return today - timedelta(days=1)

    if text == "📆 Эта неделя":
        return (
            today
            - timedelta(
                days=today.weekday()
            )
        )

    if text == "📆 Прошлая неделя":
        current_week_start = (
            today
            - timedelta(
                days=today.weekday()
            )
        )

        return (
            current_week_start
            - timedelta(days=7)
        )

    if text == "🗓 Этот месяц":
        return today.replace(day=1)

    if text == "🗓 Прошлый месяц":
        first_day = today.replace(day=1)

        return (
            first_day
            - timedelta(days=1)
        ).replace(day=1)

    return None


# =========================================================
# ЗАПРОС ДАТЫ ДЛЯ ДЕТАЛИЗАЦИИ
# =========================================================

async def ask_for_detail_date(
    update: Update,
):
    user_id = update.effective_user.id

    start_detail_session(
        user_id
    )

    await update.message.reply_text(
        "📆 ВВЕДИ ДАТУ\n\n"
        "Напиши дату в формате:\n"
        "ДД.ММ.ГГГГ\n\n"
        "Например:\n"
        "16.09.2026\n\n"
        "Я покажу:\n"
        "🔵 какие заявки попали в аванс\n"
        "🟠 какие заявки попали в сверку",
        reply_markup=DETAIL_MENU,
    )


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id

    # Проверяем, был ли пользователь в базе ДО регистрации.
    # Если его нет — это новый пользователь.
    existing_user = next(
        (
            user
            for user in get_users()
            if user["user_id"] == user_id
        ),
        None,
    )

    is_new_user = existing_user is None

    # Регистрируем / обновляем пользователя
    save_user(update)

    # Сбрасываем активные состояния
    finish_detail_session(user_id)
    remove_pending_application(user_id)
    finish_manual_application_date(user_id)
    finish_import_session(user_id)
    finish_manual_import_date(user_id)

    # =====================================================
    # НОВЫЙ ПОЛЬЗОВАТЕЛЬ
    # =====================================================

    if is_new_user:
        await update.message.reply_text(
            "Добро пожаловать в командку EFIN 👋\n\n"
            "Здесь ты можешь удобно отслеживать "
            "свои заявки и заработок.\n\n"
            
            "📥 КАК ПОЛЬЗОВАТЬСЯ БОТОМ\n\n"
            
            "• Отправляй заявку от EfinAgentBot — "
            "бот предложит выбрать дату и добавит "
            "её в твой доход.\n\n"
            
            "• Если нужно загрузить несколько заявок "
            "сразу — нажми «📥 Загрузить заявки», "
            "выбери дату и отправляй заявки одну за другой.\n\n"
            
            "• В разделе «💰 Заработок» можно посмотреть "
            "ближайшие выплаты, общий доход и количество заявок.\n\n"
            
            "• Через «🔎 Детализация дохода» можно посмотреть, "
            "какие конкретно заявки попали в аванс и сверку.\n\n"
            
            "• Если случайно отправишь одну и ту же заявку "
            "повторно — бот сообщит, что это дубль.\n\n"
            
            "• Все основные действия доступны через кнопки меню.\n\n"
            
            "━━━━━━━━━━━━━━\n\n"
            
            "⚠️ БОТ находится в разработке, "
            "выплаты в сверку, могут отличаться!\n\n"
            
            "Жалобы, угрозы, предложения — @mityazazin",
            
            reply_markup=get_menu(user_id),
        )

        return

    # =====================================================
    # УЖЕ ЗАРЕГИСТРИРОВАННЫЙ ПОЛЬЗОВАТЕЛЬ
    # =====================================================

    await update.message.reply_text(
        "👋 С возвращением в EFIN!\n\n"
        "Выбирай нужный раздел 👇",
        reply_markup=get_menu(user_id),
    )
    user_id = update.effective_user.id

    save_user(update)

    finish_detail_session(user_id)
    remove_pending_application(user_id)
    finish_manual_application_date(user_id)
    finish_import_session(user_id)
    finish_manual_import_date(user_id)

    await update.message.reply_text(
        "👋 Привет! Это Efin Money Bot.\n\n"
        "📄 Одну заявку можешь просто переслать "
        "мне — я попрошу указать дату.\n\n"
        "📦 Если заявок несколько — нажми "
        "«📥 Загрузить заявки», выбери одну дату "
        "для всей пачки и отправляй их.\n\n"
        "Выбирай нужный раздел 👇",
        reply_markup=get_menu(user_id),
    )


# =========================================================
# НАЧАЛО МАССОВОЙ ЗАГРУЗКИ
# =========================================================

async def start_import(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id

    finish_detail_session(user_id)
    remove_pending_application(user_id)
    finish_manual_application_date(user_id)
    finish_manual_import_date(user_id)

    existing_session = get_import_session(
        user_id
    )

    if existing_session:
        selected_date = existing_session.get(
            "selected_date"
        )

        if selected_date:
            await update.message.reply_text(
                "📥 Массовая загрузка уже активна.\n\n"
                f"📅 Дата заявок: "
                f"{format_date(selected_date)}\n\n"
                "Продолжай пересылать заявки.\n\n"
                "Когда закончишь, нажми:\n"
                "✅ Завершить загрузку",
                reply_markup=IMPORT_ACTIVE_MENU,
            )

        else:
            await update.message.reply_text(
                "📥 Массовая загрузка уже запущена.\n\n"
                "Сначала выбери дату заявок.",
                reply_markup=IMPORT_DATE_MENU,
            )

        return

    create_import_session(user_id)

    await update.message.reply_text(
        "📥 ЗАГРУЗКА ЗАЯВОК\n\n"
        "Ты собираешься загрузить несколько "
        "заявок.\n\n"
        "Сначала выбери дату, которая будет "
        "установлена ВСЕМ заявкам этой пачки.\n\n"
        "⚠️ Дата из сообщений EfinAgentBot "
        "использоваться НЕ будет.",
        reply_markup=IMPORT_DATE_MENU,
    )


# =========================================================
# РУЧНОЙ ВВОД ДАТЫ МАССОВОЙ ЗАГРУЗКИ
# =========================================================

async def ask_manual_import_date(
    update: Update,
    user_id: int,
):
    start_manual_import_date(
        user_id
    )

    await update.message.reply_text(
        "✏️ РУЧНОЙ ВВОД ДАТЫ ПАЧКИ\n\n"
        "Напиши дату заявок в формате:\n"
        "ДД.ММ.ГГГГ\n\n"
        "Например:\n"
        "16.09.2026",
        reply_markup=ReplyKeyboardMarkup(
            [
                ["❌ Отмена"],
            ],
            resize_keyboard=True,
        ),
    )


# =========================================================
# ОБРАБОТКА РУЧНОЙ ДАТЫ МАССОВОЙ ЗАГРУЗКИ
# =========================================================

async def handle_manual_import_date(
    update: Update,
    text: str,
):
    user_id = update.effective_user.id

    try:
        selected_date = datetime.strptime(
            text.strip(),
            "%d.%m.%Y",
        ).date()

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат даты.\n\n"
            "Напиши так:\n"
            "16.09.2026",
            reply_markup=ReplyKeyboardMarkup(
                [
                    ["❌ Отмена"],
                ],
                resize_keyboard=True,
            ),
        )

        return

    session = get_import_session(
        user_id
    )

    if not session:
        finish_manual_import_date(user_id)

        await update.message.reply_text(
            "⚠️ Сессия загрузки уже завершена.",
            reply_markup=get_menu(user_id),
        )

        return

    session["selected_date"] = selected_date

    finish_manual_import_date(user_id)

    await update.message.reply_text(
        "✅ ДАТА ВЫБРАНА\n\n"
        f"📅 Дата всех заявок: "
        f"{format_date(selected_date)}\n\n"
        "Теперь отправляй заявки от "
        "EfinAgentBot.\n\n"
        "Когда закончишь, нажми:\n"
        "✅ Завершить загрузку",
        reply_markup=IMPORT_ACTIVE_MENU,
    )


# =========================================================
# ПОДТВЕРЖДЕНИЕ ДАТЫ МАССОВОЙ ЗАГРУЗКИ
# =========================================================

async def confirm_import_date(
    update: Update,
    user_id: int,
    selected_date: date,
):
    session = get_import_session(
        user_id
    )

    if not session:
        await update.message.reply_text(
            "⚠️ Сессия загрузки не найдена.",
            reply_markup=get_menu(user_id),
        )

        return

    session["selected_date"] = selected_date

    finish_manual_import_date(user_id)

    await update.message.reply_text(
        "✅ ДАТА ВЫБРАНА\n\n"
        f"📅 Дата всех заявок: "
        f"{format_date(selected_date)}\n\n"
        "Теперь отправляй заявки от "
        "EfinAgentBot.\n\n"
        "⚠️ Дата внутри сообщений "
        "игнорируется.\n\n"
        "Когда закончишь, нажми:\n"
        "✅ Завершить загрузку",
        reply_markup=IMPORT_ACTIVE_MENU,
    )


# =========================================================
# ОТМЕНА МАССОВОЙ ЗАГРУЗКИ
# =========================================================

async def cancel_import(
    update: Update,
    user_id: int,
):
    session = finish_import_session(
        user_id
    )

    finish_manual_import_date(user_id)

    if session:
        await update.message.reply_text(
            "❌ ЗАГРУЗКА ОТМЕНЕНА\n\n"
            f"📨 Получено сообщений: "
            f"{session['received']}\n"
            f"✅ Добавлено: "
            f"{session['added']}\n\n"
            "Заявки, которые уже были сохранены "
            "до отмены, остаются в базе.",
            reply_markup=get_menu(user_id),
        )

    else:
        await update.message.reply_text(
            "❌ Загрузка отменена.",
            reply_markup=get_menu(user_id),
        )


# =========================================================
# ЗАВЕРШЕНИЕ МАССОВОЙ ЗАГРУЗКИ
# =========================================================

async def finish_import(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id

    session = finish_import_session(
        user_id
    )

    finish_manual_import_date(user_id)

    if not session:
        await update.message.reply_text(
            "ℹ️ Сейчас загрузка заявок "
            "не запущена.",
            reply_markup=get_menu(user_id),
        )

        return

    selected_date = session.get(
        "selected_date"
    )

    await update.message.reply_text(
        "📥 ЗАГРУЗКА ЗАВЕРШЕНА\n\n"
        f"📅 Дата заявок: "
        f"{format_date(selected_date)}\n\n"
        f"📨 Получено сообщений: "
        f"{session['received']}\n\n"
        f"✅ Добавлено: "
        f"{session['added']}\n"
        f"♻️ Дубликатов: "
        f"{session['duplicates']}\n"
        f"⏳ Не оплачивается: "
        f"{session['not_payable']}\n"
        f"❓ Не распознано: "
        f"{session['unrecognized']}\n\n"
        "━━━━━━━━━━━━━━\n"
        f"💰 Начислено: "
        f"{session['total_earned']} ₽",
        reply_markup=get_menu(user_id),
    )


# =========================================================
# АДМИН-ПАНЕЛЬ
# =========================================================

async def show_admin_panel(
    update: Update,
):
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ Доступ запрещён."
        )

        return

    await update.message.reply_text(
        "🛠 АДМИН-ПАНЕЛЬ\n\n"
        "👥 Пользователи — управление пользователями\n"
        "📊 Общая статистика — статистика по всем\n"
        "📋 Все заявки — все операции\n"
        "⚙️ Тарифы — управление тарифами\n"
        "💸 Корректировка — ручные корректировки\n"
        "📢 Рассылка — сообщения пользователям",
        reply_markup=ADMIN_PANEL_MENU,
    )


# =========================================================
# КЛАВИАТУРА ПОЛЬЗОВАТЕЛЕЙ
# =========================================================

def get_user_display_name(user):
    name_parts = []

    if user["first_name"]:
        name_parts.append(
            user["first_name"]
        )

    if user["last_name"]:
        name_parts.append(
            user["last_name"]
        )

    full_name = " ".join(
        name_parts
    )

    if not full_name:
        full_name = "Без имени"

    if user["username"]:
        return (
            f"{full_name} "
            f"(@{user['username']})"
        )

    return full_name


def build_users_keyboard(users):
    rows = []

    for user in users:
        user_id = user["user_id"]

        name = get_user_display_name(
            user
        )

        if len(name) > 35:
            name = name[:32] + "..."

        rows.append(
            [
                InlineKeyboardButton(
                    f"👤 {name}",
                    callback_data=f"admin_user:{user_id}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "⬅️ Назад",
                callback_data="admin_panel",
            )
        ]
    )

    return InlineKeyboardMarkup(rows)


# =========================================================
# ПОЛЬЗОВАТЕЛИ
# =========================================================

async def show_users(
    update: Update,
):
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ Доступ запрещён."
        )

        return

    users = get_users()

    if not users:
        await update.message.reply_text(
            "👥 Пользователей пока нет.",
            reply_markup=ADMIN_PANEL_MENU,
        )

        return

    message = (
        "👥 ПОЛЬЗОВАТЕЛИ\n\n"
        "Выбери пользователя:"
    )

    await update.message.reply_text(
        message,
        reply_markup=build_users_keyboard(users),
    )


# =========================================================
# КАРТОЧКА ПОЛЬЗОВАТЕЛЯ ДЛЯ АДМИНА
# =========================================================

def build_admin_user_keyboard(
    target_user_id: int,
):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🗑 Удалить все заявки",
                    callback_data=(
                        f"admin_del_all:{target_user_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "📅 Удалить заявки за дату",
                    callback_data=(
                        f"admin_del_date:{target_user_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Назад",
                    callback_data="admin_users",
                )
            ],
        ]
    )


async def show_admin_user(
    query,
    target_user_id: int,
):
    user = next(
        (
            item
            for item in get_users()
            if item["user_id"] == target_user_id
        ),
        None,
    )

    if not user:
        await query.edit_message_text(
            "❌ Пользователь не найден."
        )

        return

    stats = get_earnings_stats(
        target_user_id
    )

    name = get_user_display_name(
        user
    )

    username = (
        f"@{user['username']}"
        if user["username"]
        else "без username"
    )

    message = (
        "👤 ПОЛЬЗОВАТЕЛЬ\n\n"
        f"Имя: {name}\n"
        f"Username: {username}\n"
        f"🆔 ID: {target_user_id}\n\n"
        "━━━━━━━━━━━━━━\n"
        f"📦 Заявок: {stats['count']}\n"
        f"💵 Аванс: {stats['advance']} ₽\n"
        f"📅 Сверка: {stats['settlement']} ₽\n"
        f"💰 Всего: {stats['total']} ₽\n\n"
        "Выбери действие:"
    )

    await query.edit_message_text(
        message,
        reply_markup=build_admin_user_keyboard(
            target_user_id
        ),
    )


# =========================================================
# ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ ВСЕХ ЗАЯВОК
# =========================================================

def build_delete_all_confirmation_keyboard(
    target_user_id: int,
):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⚠️ Да, удалить всё",
                    callback_data=(
                        f"admin_confirm_all:{target_user_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data=(
                        f"admin_user:{target_user_id}"
                    ),
                )
            ],
        ]
    )


# =========================================================
# ПОДГОТОВКА УДАЛЕНИЯ ПО ДАТЕ
# =========================================================

def build_admin_delete_date_keyboard(
    target_user_id: int,
):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "◀️ Вчера",
                    callback_data=(
                        f"admin_date_yesterday:{target_user_id}"
                    ),
                ),
                InlineKeyboardButton(
                    "📅 Сегодня",
                    callback_data=(
                        f"admin_date_today:{target_user_id}"
                    ),
                ),
            ],
            [
                InlineKeyboardButton(
                    "✏️ Ввести дату",
                    callback_data=(
                        f"admin_date_manual:{target_user_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data=(
                        f"admin_user:{target_user_id}"
                    ),
                )
            ],
        ]
    )


async def show_admin_delete_date_menu(
    query,
    target_user_id: int,
):
    await query.edit_message_text(
        "📅 УДАЛЕНИЕ ЗАЯВОК ПО ДАТЕ\n\n"
        "Выбери дату:",
        reply_markup=build_admin_delete_date_keyboard(
            target_user_id
        ),
    )


# =========================================================
# ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ ЗАЯВОК ЗА ДАТУ
# =========================================================

def build_date_delete_confirmation_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🗑 Да, удалить",
                    callback_data="admin_confirm_date_delete",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data="admin_cancel_delete",
                )
            ],
        ]
    )


async def prepare_admin_date_delete(
    query_or_message,
    admin_id: int,
    target_user_id: int,
    selected_date: date,
):
    stats = delete_user_earnings_preview(
        target_user_id,
        selected_date,
    )

    set_admin_pending_date_delete(
        admin_id,
        target_user_id,
        selected_date,
    )

    message = (
        "📅 УДАЛЕНИЕ ЗАЯВОК\n\n"
        f"👤 Пользователь ID: "
        f"{target_user_id}\n"
        f"📅 Дата: "
        f"{format_date(selected_date)}\n\n"
        f"📦 Найдено заявок: "
        f"{stats['count']}\n"
        f"💰 Сумма: "
        f"{stats['total']} ₽\n\n"
    )

    if stats["count"] == 0:
        message += (
            "⚠️ За эту дату заявок нет.\n\n"
            "Удалять нечего."
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data=(
                            f"admin_user:{target_user_id}"
                        ),
                    )
                ]
            ]
        )

    else:
        message += (
            "⚠️ После удаления эти заявки "
            "будут полностью удалены из базы.\n\n"
            "Продолжить?"
        )

        keyboard = (
            build_date_delete_confirmation_keyboard()
        )

    if hasattr(query_or_message, "edit_message_text"):
        await query_or_message.edit_message_text(
            message,
            reply_markup=keyboard,
        )
    else:
        await query_or_message.reply_text(
            message,
            reply_markup=keyboard,
        )


def delete_user_earnings_preview(
    user_id: int,
    selected_date: date,
):
    """
    Получает статистику перед удалением.
    Само удаление здесь НЕ выполняется.
    """
    earnings = get_user_earnings(
        user_id
    )

    count = 0
    advance = 0
    settlement = 0
    total = 0

    for earning in earnings:
        created_at = earning["created_at"]

        if not created_at:
            continue

        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(
                    created_at
                )
            except ValueError:
                continue

        if isinstance(created_at, datetime):
            earning_date = created_at.date()
        elif isinstance(created_at, date):
            earning_date = created_at
        else:
            continue

        if earning_date != selected_date:
            continue

        count += 1
        advance += earning["advance"]
        settlement += earning["settlement"]
        total += earning["total"]

    return {
        "count": count,
        "advance": advance,
        "settlement": settlement,
        "total": total,
    }


# =========================================================
# УВЕДОМЛЕНИЕ ПОЛЬЗОВАТЕЛЯ ОБ УДАЛЕНИИ
# =========================================================

async def notify_user_about_deletion(
    context: ContextTypes.DEFAULT_TYPE,
    target_user_id: int,
    deleted_count: int,
    selected_date: date | None = None,
):
    if deleted_count <= 0:
        return True

    if selected_date:
        message = (
            "⚠️ АДМИНИСТРАТОР ОЧИСТИЛ ВАШ СПИСОК ЗАЯВОК\n\n"
            f"📅 Дата: {format_date(selected_date)}\n"
            f"🗑 Удалено заявок: {deleted_count}\n\n"
            "Если это произошло по ошибке — "
            "обратитесь к администратору."
        )

    else:
        message = (
            "⚠️ АДМИНИСТРАТОР ОЧИСТИЛ ВАШ СПИСОК ЗАЯВОК\n\n"
            f"🗑 Удалено заявок: {deleted_count}\n\n"
            "Если это произошло по ошибке — "
            "обратитесь к администратору."
        )

    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=message,
        )

        return True

    except Exception as error:
        print(
            f"⚠️ Не удалось уведомить пользователя "
            f"{target_user_id}: {error}"
        )

        return False


# =========================================================
# ОБЩАЯ СТАТИСТИКА
# =========================================================

async def show_global_stats(
    update: Update,
):
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ Доступ запрещён."
        )

        return

    stats = get_global_stats()

    await update.message.reply_text(
        "📊 ОБЩАЯ СТАТИСТИКА\n\n"
        f"👥 Пользователей: "
        f"{stats['users']}\n"
        f"📦 Заявок: "
        f"{stats['count']}\n\n"
        f"💵 Аванс: "
        f"{stats['advance']} ₽\n"
        f"📅 Сверка: "
        f"{stats['settlement']} ₽\n"
        "━━━━━━━━━━━━━━\n"
        f"💰 ВСЕГО: "
        f"{stats['total']} ₽",
        reply_markup=ADMIN_PANEL_MENU,
    )


# =========================================================
# ЗАРАБОТОК
# =========================================================

async def show_income(
    update: Update,
):
    user_id = update.effective_user.id

    finish_detail_session(user_id)

    stats = get_earnings_stats(
        user_id
    )

    next_advance = get_next_advance(
        user_id
    )

    next_settlement = get_next_settlement(
        user_id
    )

    message = (
        "💰 МОЙ ДОХОД\n\n"
    )

    if next_advance:
        message += (
            "🔵 БЛИЖАЙШИЙ АВАНС\n\n"
            f"📦 За заявки: "
            f"{format_date(next_advance['week_start'])}"
            f" – "
            f"{format_date(next_advance['week_end'])}\n\n"
            f"💳 Выплата: "
            f"{format_date(next_advance['payout_start'])}"
            f" – "
            f"{format_date(next_advance['payout_end'])}\n\n"
            f"💵 К выплате: "
            f"{next_advance['amount']} ₽\n"
            f"📦 Заявок: "
            f"{next_advance['count']}\n\n"
        )

    else:
        message += (
            "🔵 БЛИЖАЙШИЙ АВАНС\n\n"
            "Пока нет запланированного аванса.\n\n"
        )

    if next_settlement:
        message += (
            "🟠 БЛИЖАЙШАЯ СВЕРКА\n\n"
            f"📅 За: "
            f"{format_month(next_settlement['month'])}\n\n"
            f"💳 Выплата: "
            f"{format_date(next_settlement['payout_start'])}"
            f" – "
            f"{format_date(next_settlement['payout_end'])}\n\n"
            f"💵 К сверке: "
            f"{next_settlement['amount']} ₽\n"
            f"📦 Заявок: "
            f"{next_settlement['count']}\n\n"
        )

    else:
        message += (
            "🟠 БЛИЖАЙШАЯ СВЕРКА\n\n"
            "Пока нет запланированной сверки.\n\n"
        )

    message += (
        "━━━━━━━━━━━━━━\n\n"
        f"📦 Всего заявок: "
        f"{stats['count']}\n"
        f"💵 Всего авансов: "
        f"{stats['advance']} ₽\n"
        f"📅 Всего сверок: "
        f"{stats['settlement']} ₽\n\n"
        f"💰 ОБЩЕЕ НАЧИСЛЕНИЕ: "
        f"{stats['total']} ₽"
    )

    await update.message.reply_text(
        message,
        reply_markup=INCOME_MENU,
    )


# =========================================================
# СЕГОДНЯ
# =========================================================

async def show_today(
    update: Update,
):
    user_id = update.effective_user.id

    stats = get_today_stats(
        user_id
    )

    await update.message.reply_text(
        "📅 ЗАРАБОТОК ЗА СЕГОДНЯ\n\n"
        f"📦 Заявок: "
        f"{stats['count']}\n\n"
        f"💵 Аванс: "
        f"{stats['advance']} ₽\n"
        f"📅 Сверка: "
        f"{stats['settlement']} ₽\n"
        "━━━━━━━━━━━━━━\n"
        f"💰 ВСЕГО: "
        f"{stats['total']} ₽",
        reply_markup=get_menu(user_id),
    )


# =========================================================
# НЕДЕЛЯ
# =========================================================

async def show_week(
    update: Update,
):
    user_id = update.effective_user.id

    today = datetime.now(MOSCOW_TZ).date()

    week_start = (
        today
        - timedelta(
            days=today.weekday()
        )
    )

    stats = get_week_income(
        user_id,
        week_start,
    )

    week_end = stats[
        "week_end"
    ]

    advance_payout_start = (
        week_end
        + timedelta(days=1)
    )

    advance_payout_end = (
        advance_payout_start
        + timedelta(days=4)
    )

    await update.message.reply_text(
        "📆 ТЕКУЩАЯ НЕДЕЛЯ\n\n"
        "📅 Период заявок:\n"
        f"{format_date(week_start)}"
        f" – "
        f"{format_date(week_end)}\n\n"
        f"📦 Заявок: "
        f"{stats['count']}\n\n"
        f"💵 Аванс за эту неделю: "
        f"{stats['advance']} ₽\n"
        f"📅 Сверка: "
        f"{stats['settlement']} ₽\n"
        "━━━━━━━━━━━━━━\n"
        f"💰 Всего за заявки: "
        f"{stats['total']} ₽\n\n"
        "🔵 Аванс за эту неделю будет выплачен:\n"
        f"{format_date(advance_payout_start)}"
        f" – "
        f"{format_date(advance_payout_end)}",
        reply_markup=get_menu(user_id),
    )


# =========================================================
# МЕСЯЦ
# =========================================================

async def show_month(
    update: Update,
):
    user_id = update.effective_user.id

    today = datetime.now(MOSCOW_TZ).date()

    stats = get_month_income(
        user_id,
        today.year,
        today.month,
    )

    if today.month == 12:
        next_month = today.replace(
            year=today.year + 1,
            month=1,
            day=1,
        )

    else:
        next_month = today.replace(
            month=today.month + 1,
            day=1,
        )

    settlement_start = (
        next_month.replace(
            day=25
        )
    )

    if next_month.month == 12:
        settlement_end = (
            next_month.replace(
                year=next_month.year + 1,
                month=1,
                day=5,
            )
        )

    else:
        settlement_end = (
            next_month.replace(
                month=next_month.month + 1,
                day=5,
            )
        )

    await update.message.reply_text(
        "🗓 ТЕКУЩИЙ МЕСЯЦ\n\n"
        f"📅 {MONTH_NAMES[today.month]} "
        f"{today.year}\n\n"
        f"📦 Заявок: "
        f"{stats['count']}\n\n"
        f"💵 Аванс: "
        f"{stats['advance']} ₽\n"
        f"📅 Сверка: "
        f"{stats['settlement']} ₽\n"
        "━━━━━━━━━━━━━━\n"
        f"💰 Всего за месяц: "
        f"{stats['total']} ₽\n\n"
        "🟠 Сверка за этот месяц:\n"
        f"{format_date(settlement_start)}"
        f" – "
        f"{format_date(settlement_end)}",
        reply_markup=get_menu(user_id),
    )


# =========================================================
# ПОСЛЕДНИЕ ЗАЯВКИ
# =========================================================

async def show_recent_earnings(
    update: Update,
):
    user_id = update.effective_user.id

    earnings = get_user_earnings(
        user_id
    )

    if not earnings:
        await update.message.reply_text(
            "📥 Заявок пока нет.",
            reply_markup=get_menu(user_id),
        )

        return

    earnings = earnings[:10]

    message = (
        "📥 ПОСЛЕДНИЕ ЗАЯВКИ\n\n"
    )

    for earning in earnings:
        message += (
            f"📄 {earning['operation_id']}\n"
            f"🏦 {earning['bank']}\n"
            f"📅 {format_date(earning['created_at'])}\n"
            f"📌 {earning['status']}\n"
            f"💵 Аванс: "
            f"{earning['advance']} ₽\n"
            f"📅 Сверка: "
            f"{earning['settlement']} ₽\n"
            f"💰 Итого: "
            f"{earning['total']} ₽\n"
            "━━━━━━━━━━━━━━\n"
        )

    await update.message.reply_text(
        message,
        reply_markup=get_menu(user_id),
    )


# =========================================================
# ОБРАБОТКА ДЕТАЛИЗАЦИИ: РУЧНОЙ ВВОД ДАТЫ
# =========================================================

async def handle_detail_date(
    update: Update,
    text: str,
):
    user_id = update.effective_user.id

    try:
        selected_date = datetime.strptime(
            text.strip(),
            "%d.%m.%Y",
        ).date()

    except ValueError:
        await update.message.reply_text(
            "❌ Не понял дату.\n\n"
            "Введи её в формате:\n"
            "ДД.ММ.ГГГГ\n\n"
            "Например:\n"
            "16.09.2026",
            reply_markup=DETAIL_MENU,
        )

        return

    await show_income_details(
        update,
        user_id,
        selected_date,
    )


# =========================================================
# ОБРАБОТКА ОБЫЧНОЙ ОДИНОЧНОЙ ЗАЯВКИ
# =========================================================

async def handle_direct_application(
    update: Update,
    user_id: int,
    text: str,
):
    result = parse_message(text)

    if result is None:
        await update.message.reply_text(
            "🤔 Я не смог распознать эту заявку.\n\n"
            "Перешли мне сообщение от "
            "EfinAgentBot целиком.",
            reply_markup=get_menu(user_id),
        )

        return

    operation_ids = re.findall(
        r"(?<![А-ЯЁ])([А-ЯЁ]{2}\d{7})(?!\d)",
        text,
    )

    if len(operation_ids) > 1:
        await update.message.reply_text(
            "📦 Я вижу в одном сообщении "
            "несколько заявок.\n\n"
            "Для загрузки нескольких заявок "
            "используй кнопку:\n"
            "📥 Загрузить заявки\n\n"
            "Там ты один раз выберешь дату "
            "для всей пачки.",
            reply_markup=get_menu(user_id),
        )

        return

    operation_id = result["operation_id"]

    # =====================================================
    # МГНОВЕННАЯ ПРОВЕРКА ДУБЛЯ
    # =====================================================

    if earning_exists(
        user_id,
        operation_id,
    ):
        await update.message.reply_text(
            "♻️ ДУБЛЬ\n\n"
            "Эта заявка уже есть в твоём списке.\n\n"
            f"📄 Заявка: {operation_id}\n"
            f"🏦 {result['name']}\n\n"
            "Я повторно её не добавлю.",
            reply_markup=get_menu(user_id),
        )

        await delete_user_message(
            update
        )

        return

    if not result["is_payable"]:
        await update.message.reply_text(
            "⏳ Заявка пока не оплачивается.\n\n"
            f"📄 Заявка: "
            f"{result['operation_id']}\n"
            f"🏦 {result['name']}\n"
            f"📌 Статус: "
            f"{result['status']}\n\n"
            "💰 Начисление: 0 ₽",
            reply_markup=get_menu(user_id),
        )

        await delete_user_message(
            update
        )

        return

    # =====================================================
    # ЕСЛИ УЖЕ ЕСТЬ НЕПОДТВЕРЖДЁННАЯ ЗАЯВКА
    # =====================================================

    if get_pending_application(user_id):
        await update.message.reply_text(
            "📦 Похоже, ты отправляешь несколько заявок.\n\n"
            "Для пачки используй:\n"
            "📥 Загрузить заявки\n\n"
            "Там выберешь одну дату для всей пачки.\n\n"
            "Текущая заявка ожидающей даты "
            "будет отменена.",
            reply_markup=get_menu(user_id),
        )

        remove_pending_application(
            user_id
        )

        finish_manual_application_date(
            user_id
        )

        return

    create_pending_application(
        user_id,
        result,
    )

    await ask_application_date(
        update,
        user_id,
    )

    await delete_user_message(
        update
    )


# =========================================================
# ОБРАБОТКА МАССОВОЙ ЗАГРУЗКИ
# =========================================================

async def handle_import_message(
    update: Update,
    user_id: int,
    text: str,
):
    import_session = get_import_session(
        user_id
    )

    if not import_session:
        return False

    selected_date = import_session.get(
        "selected_date"
    )

    if not selected_date:
        await update.message.reply_text(
            "⚠️ Сначала выбери дату загрузки.\n\n"
            "После этого я начну принимать заявки.",
            reply_markup=IMPORT_DATE_MENU,
        )

        return True

    import_session["received"] += 1

    result = parse_message(text)

    if result is None:
        import_session[
            "unrecognized"
        ] += 1

        await delete_user_message(
            update
        )

        return True

    operation_id = result["operation_id"]

    # =====================================================
    # ДУБЛЬ В МАССОВОЙ ЗАГРУЗКЕ
    # =====================================================

    if earning_exists(
        user_id,
        operation_id,
    ):
        import_session[
            "duplicates"
        ] += 1

        await delete_user_message(
            update
        )

        return True

    if not result["is_payable"]:
        import_session[
            "not_payable"
        ] += 1

        await delete_user_message(
            update
        )

        return True

    # =====================================================
    # ДАТА EFINAGENTBOT ИГНОРИРУЕТСЯ
    # =====================================================

    created_at = make_application_datetime(
        selected_date
    )

    added = add_earning(
        user_id=user_id,
        operation_id=result["operation_id"],
        trigger=result["trigger"],
        bank=result["name"],
        status=result["status"],
        advance=result["advance"],
        settlement=result["settlement"],
        total=result["total"],
        created_at=created_at,
        original_text=result["original_text"],
    )

    if not added:
        import_session[
            "duplicates"
        ] += 1

        await delete_user_message(
            update
        )

        return True

    import_session[
        "added"
    ] += 1

    import_session[
        "total_earned"
    ] += result["total"]

    await delete_user_message(
        update
    )

    return True


# =========================================================
# ОБРАБОТКА АДМИНСКОЙ РУЧНОЙ ДАТЫ УДАЛЕНИЯ
# =========================================================

async def handle_admin_manual_delete_date(
    update: Update,
    text: str,
):
    admin_id = update.effective_user.id

    target_user_id = get_admin_manual_delete_target(
        admin_id
    )

    if target_user_id is None:
        return False

    if text == "❌ Отмена":
        finish_admin_manual_delete_date(
            admin_id
        )

        await update.message.reply_text(
            "❌ Удаление отменено.",
            reply_markup=ADMIN_PANEL_MENU,
        )

        return True

    try:
        selected_date = datetime.strptime(
            text.strip(),
            "%d.%m.%Y",
        ).date()

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат даты.\n\n"
            "Введи дату так:\n"
            "16.09.2026",
            reply_markup=ADMIN_DELETE_DATE_MENU,
        )

        return True

    finish_admin_manual_delete_date(
        admin_id
    )

    stats = delete_user_earnings_preview(
        target_user_id,
        selected_date,
    )

    set_admin_pending_date_delete(
        admin_id,
        target_user_id,
        selected_date,
    )

    message = (
        "📅 УДАЛЕНИЕ ЗАЯВОК\n\n"
        f"👤 Пользователь ID: "
        f"{target_user_id}\n"
        f"📅 Дата: "
        f"{format_date(selected_date)}\n\n"
        f"📦 Найдено заявок: "
        f"{stats['count']}\n"
        f"💰 Сумма: "
        f"{stats['total']} ₽\n\n"
    )

    if stats["count"] == 0:
        finish_admin_pending_date_delete(
            admin_id
        )

        await update.message.reply_text(
            message
            + "⚠️ За эту дату заявок нет.",
            reply_markup=ADMIN_PANEL_MENU,
        )

    else:
        await update.message.reply_text(
            message
            + "⚠️ После удаления заявки "
            "будут полностью удалены из базы.\n\n"
            "Продолжить?",
            reply_markup=build_date_delete_confirmation_keyboard(),
        )

    return True


# =========================================================
# CALLBACKS АДМИН-ПАНЕЛИ
# =========================================================

async def handle_admin_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not query:
        return

    await query.answer()

    admin_id = query.from_user.id

    if admin_id != ADMIN_ID:
        await query.answer(
            "⛔ Доступ запрещён.",
            show_alert=True,
        )

        return

    data = query.data or ""


    # =====================================================
    # ПЕРЕРАСЧЁТ ЗАЯВОК
    # =====================================================

    if data == "admin_recalc_cancel":
        finish_recalc_session(admin_id)
        await query.edit_message_text("❌ Перерасчёт отменён.")
        await query.message.reply_text(
            "Админ-панель 👇",
            reply_markup=ADMIN_PANEL_MENU,
        )
        return

    if data == "admin_recalc_confirm":
        session = get_recalc_session(admin_id)

        if not session:
            await query.answer(
                "⚠️ Сессия перерасчёта истекла.",
                show_alert=True,
            )
            return

        start_date = session["start_date"]
        end_date = session["end_date"]
        finish_recalc_session(admin_id)

        result = recalculate_earnings(
            start_date,
            end_date,
        )

        difference = result["difference"]
        difference_text = (
            f"+{difference} ₽"
            if difference > 0
            else f"{difference} ₽"
        )

        await query.edit_message_text(
            "✅ ПЕРЕРАСЧЁТ ЗАВЕРШЁН

"
            f"📅 Период: {start_date.strftime('%d.%m.%Y')} — "
            f"{end_date.strftime('%d.%m.%Y')}

"
            f"🔄 Изменено: {result['updated']}
"
            f"⏭ Без изменений: {result['unchanged']}
"
            f"⚠️ Пропущено: {result['skipped']}

"
            f"💰 Было: {result['old_total']} ₽
"
            f"💰 Стало: {result['new_total']} ₽
"
            f"📈 Разница: {difference_text}"
        )

        await query.message.reply_text(
            "Админ-панель 👇",
            reply_markup=ADMIN_PANEL_MENU,
        )
        return

    # =====================================================
    # РАССЫЛКА
    # =====================================================

    if data == "admin_broadcast_cancel":
        finish_broadcast_session(admin_id)

        await query.edit_message_text(
            "❌ Рассылка отменена."
        )

        await query.message.reply_text(
            "Админ-панель 👇",
            reply_markup=ADMIN_PANEL_MENU,
        )

        return

    if data == "admin_broadcast_confirm":
        session = get_broadcast_session(admin_id)

        if not session or not session.get("text"):
            await query.answer(
                "⚠️ Сообщение для рассылки не найдено.",
                show_alert=True,
            )
            return

        message_text = session["text"]
        finish_broadcast_session(admin_id)

        users = get_users()

        sent = 0
        failed = 0
        skipped = 0

        await query.edit_message_text(
            "📢 РАССЫЛКА ЗАПУЩЕНА\n\n"
            "Сообщение отправляется пользователям..."
        )

        for user in users:
            target_user_id = user["user_id"]

            if target_user_id == ADMIN_ID:
                skipped += 1
                continue

            if user["is_blocked"]:
                skipped += 1
                continue

            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=message_text,
                )
                sent += 1

                # Небольшая пауза, чтобы не упереться
                # в лимиты Telegram при большой базе.
                await asyncio.sleep(0.05)

            except TelegramError as error:
                failed += 1
                print(
                    f"⚠️ Не удалось отправить рассылку "
                    f"user_id={target_user_id}: {error}"
                )

        await query.message.reply_text(
            "✅ РАССЫЛКА ЗАВЕРШЕНА\n\n"
            f"📨 Отправлено: {sent}\n"
            f"❌ Не доставлено: {failed}\n"
            f"⏭ Пропущено: {skipped}",
            reply_markup=ADMIN_PANEL_MENU,
        )

        return

    # =====================================================
    # ТАРИФЫ
    # =====================================================

    if data == "admin_tariffs":
        await show_tariffs(query)
        return

    if data == "admin_tariff_add":
        start_tariff_session(admin_id, "add")
        await query.message.reply_text(
            "➕ ДОБАВЛЕНИЕ ТАРИФА\n\n"
            "Напиши код тарифа — ровно 2 русские буквы.\n"
            "Например: НБ\n\n"
            "Для отмены: ❌ Отмена",
            reply_markup=ReplyKeyboardMarkup(
                [["❌ Отмена"]],
                resize_keyboard=True,
            ),
        )
        return

    if data.startswith("admin_tariff_edit:"):
        trigger = data.split(":", 1)[1]
        tariff = get_tariff(trigger)

        if not tariff:
            await query.answer("Тариф не найден.", show_alert=True)
            return

        start_tariff_session(admin_id, "edit", trigger)
        session = get_tariff_session(admin_id)
        session["name"] = tariff["name"]
        session["advance"] = tariff["advance"]
        session["settlement"] = tariff["settlement"]

        await query.message.reply_text(
            f"✏️ ИЗМЕНЕНИЕ ТАРИФА {trigger}\n\n"
            f"Текущее название: {tariff['name']}\n"
            f"Текущий аванс: {tariff['advance']} ₽\n"
            f"Текущая сверка: {tariff['settlement']} ₽\n\n"
            "Напиши новое название:",
            reply_markup=ReplyKeyboardMarkup(
                [["❌ Отмена"]],
                resize_keyboard=True,
            ),
        )
        return

    if data.startswith("admin_tariff_delete:"):
        trigger = data.split(":", 1)[1]
        tariff = get_tariff(trigger)

        if not tariff:
            await query.answer("Тариф уже отключён.", show_alert=True)
            return

        await query.edit_message_text(
            f"🗑 ОТКЛЮЧЕНИЕ ТАРИФА\n\n"
            f"🔹 {tariff['trigger']} — {tariff['name']}\n"
            f"💵 Аванс: {tariff['advance']} ₽\n"
            f"🟠 Сверка: {tariff['settlement']} ₽\n\n"
            "Отключить?",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ Да, отключить",
                        callback_data=f"admin_tariff_confirm_delete:{trigger}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Отмена",
                        callback_data="admin_tariffs",
                    )
                ],
            ]),
        )
        return

    if data.startswith("admin_tariff_confirm_delete:"):
        trigger = data.split(":", 1)[1]
        tariff = get_tariff(trigger)

        if not tariff:
            await query.answer("Тариф уже отключён.", show_alert=True)
            return

        delete_tariff(trigger)
        await query.edit_message_text(
            f"🗑 Тариф {trigger} отключён.\n\n"
            "Заявки с этим кодом больше не будут "
            "распознаваться как оплачиваемые, пока тариф "
            "не будет восстановлен.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⚙️ К тарифам",
                    callback_data="admin_tariffs",
                )]
            ]),
        )
        return

    # =====================================================
    # СПИСОК ПОЛЬЗОВАТЕЛЕЙ
    # =====================================================

    if data == "admin_users":
        users = get_users()

        if not users:
            await query.edit_message_text(
                "👥 Пользователей пока нет."
            )

            return

        await query.edit_message_text(
            "👥 ПОЛЬЗОВАТЕЛИ\n\n"
            "Выбери пользователя:",
            reply_markup=build_users_keyboard(
                users
            ),
        )

        return

    # =====================================================
    # АДМИН-ПАНЕЛЬ
    # =====================================================

    if data == "admin_panel":
        await query.edit_message_text(
            "🛠 АДМИН-ПАНЕЛЬ\n\n"
            "Для управления пользователями "
            "нажми «👥 Пользователи» "
            "в основном меню администратора."
        )

        await query.message.reply_text(
            "Выбери раздел 👇",
            reply_markup=ADMIN_PANEL_MENU,
        )

        return

    # =====================================================
    # ВЫБОР ПОЛЬЗОВАТЕЛЯ
    # =====================================================

    if data.startswith("admin_user:"):
        try:
            target_user_id = int(
                data.split(":", 1)[1]
            )

        except ValueError:
            return

        await show_admin_user(
            query,
            target_user_id,
        )

        return

    # =====================================================
    # УДАЛИТЬ ВСЕ ЗАЯВКИ
    # =====================================================

    if data.startswith("admin_del_all:"):
        try:
            target_user_id = int(
                data.split(":", 1)[1]
            )

        except ValueError:
            return

        stats = get_earnings_stats(
            target_user_id
        )

        await query.edit_message_text(
            "⚠️ УДАЛЕНИЕ ВСЕХ ЗАЯВОК\n\n"
            f"👤 Пользователь ID: "
            f"{target_user_id}\n\n"
            f"📦 Заявок будет удалено: "
            f"{stats['count']}\n"
            f"💰 Сумма: "
            f"{stats['total']} ₽\n\n"
            "⚠️ Это действие нельзя отменить.\n\n"
            "Продолжить?",
            reply_markup=(
                build_delete_all_confirmation_keyboard(
                    target_user_id
                )
            ),
        )

        return

    # =====================================================
    # ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ ВСЕХ
    # =====================================================

    if data.startswith("admin_confirm_all:"):
        try:
            target_user_id = int(
                data.split(":", 1)[1]
            )

        except ValueError:
            return

        result = delete_all_user_earnings(
            target_user_id
        )

        notified = await notify_user_about_deletion(
            context,
            target_user_id,
            result["count"],
        )

        notification_text = (
            "уведомление отправлено"
            if notified
            else "не удалось отправить уведомление"
        )

        await query.edit_message_text(
            "✅ ГОТОВО\n\n"
            f"👤 Пользователь ID: "
            f"{target_user_id}\n"
            f"🗑 Удалено заявок: "
            f"{result['count']}\n"
            f"💰 Удалено начислений: "
            f"{result['total']} ₽\n\n"
            f"📨 {notification_text}."
        )

        return

    # =====================================================
    # УДАЛЕНИЕ ПО ДАТЕ
    # =====================================================

    if data.startswith("admin_del_date:"):
        try:
            target_user_id = int(
                data.split(":", 1)[1]
            )

        except ValueError:
            return

        await show_admin_delete_date_menu(
            query,
            target_user_id,
        )

        return

    # =====================================================
    # ВЧЕРА
    # =====================================================

    if data.startswith("admin_date_yesterday:"):
        try:
            target_user_id = int(
                data.split(":", 1)[1]
            )

        except ValueError:
            return

        selected_date = (
            datetime.now(MOSCOW_TZ).date()
            - timedelta(days=1)
        )

        stats = delete_user_earnings_preview(
            target_user_id,
            selected_date,
        )

        set_admin_pending_date_delete(
            admin_id,
            target_user_id,
            selected_date,
        )

        if stats["count"] == 0:
            finish_admin_pending_date_delete(
                admin_id
            )

            await query.edit_message_text(
                "📅 УДАЛЕНИЕ ЗАЯВОК\n\n"
                f"Дата: {format_date(selected_date)}\n\n"
                "⚠️ За эту дату заявок нет.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "⬅️ Назад",
                                callback_data=(
                                    f"admin_user:{target_user_id}"
                                ),
                            )
                        ]
                    ]
                ),
            )

            return

        await query.edit_message_text(
            "📅 УДАЛЕНИЕ ЗАЯВОК\n\n"
            f"👤 Пользователь ID: "
            f"{target_user_id}\n"
            f"📅 Дата: "
            f"{format_date(selected_date)}\n\n"
            f"📦 Найдено заявок: "
            f"{stats['count']}\n"
            f"💰 Сумма: "
            f"{stats['total']} ₽\n\n"
            "Удалить?",
            reply_markup=(
                build_date_delete_confirmation_keyboard()
            ),
        )

        return

    # =====================================================
    # СЕГОДНЯ
    # =====================================================

    if data.startswith("admin_date_today:"):
        try:
            target_user_id = int(
                data.split(":", 1)[1]
            )

        except ValueError:
            return

        selected_date = datetime.now(MOSCOW_TZ).date()

        stats = delete_user_earnings_preview(
            target_user_id,
            selected_date,
        )

        set_admin_pending_date_delete(
            admin_id,
            target_user_id,
            selected_date,
        )

        if stats["count"] == 0:
            finish_admin_pending_date_delete(
                admin_id
            )

            await query.edit_message_text(
                "📅 УДАЛЕНИЕ ЗАЯВОК\n\n"
                f"Дата: {format_date(selected_date)}\n\n"
                "⚠️ За эту дату заявок нет.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "⬅️ Назад",
                                callback_data=(
                                    f"admin_user:{target_user_id}"
                                ),
                            )
                        ]
                    ]
                ),
            )

            return

        await query.edit_message_text(
            "📅 УДАЛЕНИЕ ЗАЯВОК\n\n"
            f"👤 Пользователь ID: "
            f"{target_user_id}\n"
            f"📅 Дата: "
            f"{format_date(selected_date)}\n\n"
            f"📦 Найдено заявок: "
            f"{stats['count']}\n"
            f"💰 Сумма: "
            f"{stats['total']} ₽\n\n"
            "Удалить?",
            reply_markup=(
                build_date_delete_confirmation_keyboard()
            ),
        )

        return

    # =====================================================
    # РУЧНОЙ ВВОД ДАТЫ
    # =====================================================

    if data.startswith("admin_date_manual:"):
        try:
            target_user_id = int(
                data.split(":", 1)[1]
            )

        except ValueError:
            return

        start_admin_manual_delete_date(
            admin_id,
            target_user_id,
        )

        await query.message.reply_text(
            "✏️ ВВЕДИ ДАТУ\n\n"
            f"👤 Пользователь ID: "
            f"{target_user_id}\n\n"
            "Формат:\n"
            "ДД.ММ.ГГГГ\n\n"
            "Например:\n"
            "24.09.2026",
            reply_markup=ADMIN_DELETE_DATE_MENU,
        )

        return

    # =====================================================
    # ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ ПО ДАТЕ
    # =====================================================

    if data == "admin_confirm_date_delete":
        pending = get_admin_pending_date_delete(
            admin_id
        )

        if not pending:
            await query.edit_message_text(
                "⚠️ Данные удаления устарели."
            )

            return

        target_user_id = pending[
            "target_user_id"
        ]

        selected_date = pending[
            "date"
        ]

        result = delete_user_earnings_by_date(
            target_user_id,
            selected_date,
        )

        finish_admin_pending_date_delete(
            admin_id
        )

        notified = await notify_user_about_deletion(
            context,
            target_user_id,
            result["count"],
            selected_date,
        )

        notification_text = (
            "уведомление отправлено"
            if notified
            else "не удалось отправить уведомление"
        )

        await query.edit_message_text(
            "✅ ГОТОВО\n\n"
            f"👤 Пользователь ID: "
            f"{target_user_id}\n"
            f"📅 Дата: "
            f"{format_date(selected_date)}\n"
            f"🗑 Удалено заявок: "
            f"{result['count']}\n"
            f"💰 Удалено начислений: "
            f"{result['total']} ₽\n\n"
            f"📨 {notification_text}."
        )

        return

    # =====================================================
    # ОТМЕНА УДАЛЕНИЯ
    # =====================================================

    if data == "admin_cancel_delete":
        finish_admin_pending_date_delete(
            admin_id
        )

        finish_admin_manual_delete_date(
            admin_id
        )

        await query.edit_message_text(
            "❌ Удаление отменено."
        )

        await query.message.reply_text(
            "Админ-панель 👇",
            reply_markup=ADMIN_PANEL_MENU,
        )

        return


# =========================================================
# ОБРАБОТКА СООБЩЕНИЙ
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if (
        not update.message
        or not update.message.text
    ):
        return

    text = update.message.text
    user_id = update.effective_user.id

    save_user(update)

    # =====================================================
    # АДМИНСКИЙ ПЕРЕРАСЧЁТ
    # =====================================================

    if user_id == ADMIN_ID:
        if get_recalc_session(user_id):
            handled = await handle_recalc_text(
                update,
                user_id,
                text,
            )
            if handled:
                return

    # =====================================================
    # АДМИНСКАЯ РАССЫЛКА
    # =====================================================

    if user_id == ADMIN_ID:
        if get_broadcast_session(user_id):
            handled = await handle_broadcast_text(
                update,
                user_id,
                text,
            )
            if handled:
                return

    # =====================================================
    # АДМИНСКОЕ УПРАВЛЕНИЕ ТАРИФОМ
    # =====================================================

    if user_id == ADMIN_ID:
        if get_tariff_session(user_id):
            handled = await handle_tariff_text(
                update,
                user_id,
                text,
            )
            if handled:
                return

    # =====================================================
    # АДМИНСКИЙ РУЧНОЙ ВВОД ДАТЫ УДАЛЕНИЯ
    # =====================================================

    if user_id == ADMIN_ID:

        if get_admin_manual_delete_target(
            user_id
        ) is not None:

            handled = (
                await handle_admin_manual_delete_date(
                    update,
                    text,
                )
            )

            if handled:
                return

    # =====================================================
    # РУЧНАЯ ДАТА МАССОВОЙ ЗАГРУЗКИ
    # =====================================================

    if is_manual_import_date_active(
        user_id
    ):
        if text == "❌ Отмена":
            await cancel_import(
                update,
                user_id,
            )

            return

        await handle_manual_import_date(
            update,
            text,
        )

        return

    # =====================================================
    # АКТИВНАЯ МАССОВАЯ ЗАГРУЗКА
    # =====================================================

    import_session = get_import_session(
        user_id
    )

    if import_session:

        if not import_session.get(
            "selected_date"
        ):
            if text == "◀️ Вчера":
                await confirm_import_date(
                    update,
                    user_id,
                    datetime.now(MOSCOW_TZ).date()
                    - timedelta(days=1),
                )

                return

            if text == "📅 Сегодня":
                await confirm_import_date(
                    update,
                    user_id,
                    datetime.now(MOSCOW_TZ).date(),
                )

                return

            if text == "✏️ Ручной ввод":
                await ask_manual_import_date(
                    update,
                    user_id,
                )

                return

            if text == "❌ Отмена":
                await cancel_import(
                    update,
                    user_id,
                )

                return

            await update.message.reply_text(
                "⚠️ Сначала выбери дату "
                "для всей пачки.",
                reply_markup=IMPORT_DATE_MENU,
            )

            return

        if text == "✅ Завершить загрузку":
            await finish_import(
                update,
                context,
            )

            return

        if text == "❌ Отменить загрузку":
            await cancel_import(
                update,
                user_id,
            )

            return

        await handle_import_message(
            update,
            user_id,
            text,
        )

        return

    # =====================================================
    # РУЧНАЯ ДАТА ОДИНОЧНОЙ ЗАЯВКИ
    # =====================================================

    if is_manual_application_date_active(
        user_id
    ):
        if text == "❌ Ошибочная отправка":
            await cancel_pending_application(
                update,
                user_id,
            )

            return

        await handle_manual_application_date(
            update,
            text,
        )

        return

    # =====================================================
    # ЕСТЬ НЕПОДТВЕРЖДЁННАЯ ОДИНОЧНАЯ ЗАЯВКА
    # =====================================================

    pending = get_pending_application(
        user_id
    )

    if pending:

        # -------------------------------------------------
        # Если вместо даты прилетела ещё одна заявка,
        # значит пользователь начал отправлять пачку.
        # -------------------------------------------------

        possible_result = parse_message(
            text
        )

        if possible_result:

            operation_id = (
                possible_result["operation_id"]
            )

            if earning_exists(
                user_id,
                operation_id,
            ):
                await update.message.reply_text(
                    "♻️ ДУБЛЬ\n\n"
                    "Эта заявка уже есть "
                    "в твоём списке.\n\n"
                    f"📄 {operation_id}",
                    reply_markup=get_menu(user_id),
                )

                await delete_user_message(
                    update
                )

                return

            remove_pending_application(
                user_id
            )

            finish_manual_application_date(
                user_id
            )

            await update.message.reply_text(
                "📦 Похоже, ты отправляешь "
                "несколько заявок.\n\n"
                "Для пачки используй:\n"
                "📥 Загрузить заявки\n\n"
                "Выбери дату один раз, затем "
                "перешли все заявки.",
                reply_markup=get_menu(user_id),
            )

            return

        if text == "📥 Загрузить заявки":
            remove_pending_application(
                user_id
            )

            await start_import(
                update,
                context,
            )

            return

        if text == "◀️ Вчера":
            selected_date = (
                datetime.now(MOSCOW_TZ).date()
                - timedelta(days=1)
            )

            await save_confirmed_application(
                update,
                user_id,
                selected_date,
            )

            return

        if text == "📅 Сегодня":
            selected_date = datetime.now(MOSCOW_TZ).date()

            await save_confirmed_application(
                update,
                user_id,
                selected_date,
            )

            return

        if text == "✏️ Ручной ввод":
            await ask_manual_application_date(
                update,
                user_id,
            )

            return

        if text == "❌ Ошибочная отправка":
            await cancel_pending_application(
                update,
                user_id,
            )

            return

        await update.message.reply_text(
            "⚠️ Сначала укажи дату заявки.\n\n"
            "Выбери кнопку ниже:",
            reply_markup=APPLICATION_DATE_MENU,
        )

        return

    # =====================================================
    # ДЕТАЛИЗАЦИЯ ДОХОДА
    # =====================================================

    if is_detail_session_active(
        user_id
    ):

        if text == "⬅️ Назад":
            finish_detail_session(
                user_id
            )

            await update.message.reply_text(
                "Главное меню 👇",
                reply_markup=get_menu(user_id),
            )

            return

        if text == "📆 Выбрать дату":
            await ask_for_detail_date(
                update
            )

            return

        quick_date = get_period_date(
            text
        )

        if quick_date:
            await show_income_details(
                update,
                user_id,
                quick_date,
            )

            return

        await handle_detail_date(
            update,
            text,
        )

        return

    # =====================================================
    # ОТКРЫТИЕ ДЕТАЛИЗАЦИИ
    # =====================================================

    if text == "🔎 Детализация дохода":
        start_detail_session(
            user_id
        )

        await update.message.reply_text(
            "🔎 ДЕТАЛИЗАЦИЯ ДОХОДА\n\n"
            "Выбери нужный период.\n\n"
            "Я покажу конкретные заявки, "
            "которые попали в:\n"
            "🔵 аванс\n"
            "🟠 сверку",
            reply_markup=DETAIL_MENU,
        )

        return

    # =====================================================
    # НАЗАД
    # =====================================================

    if text == "⬅️ Назад":
        await update.message.reply_text(
            "Главное меню 👇",
            reply_markup=get_menu(user_id),
        )

        return

    # =====================================================
    # АДМИН-ПАНЕЛЬ
    # =====================================================

    if text == "🛠 Админ-панель":
        await show_admin_panel(
            update
        )

        return

    # =====================================================
    # ПОЛЬЗОВАТЕЛИ
    # =====================================================

    if text == "👥 Пользователи":
        await show_users(
            update
        )

        return

    # =====================================================
    # ОБЩАЯ СТАТИСТИКА
    # =====================================================

    if text == "📊 Общая статистика":
        await show_global_stats(
            update
        )

        return

    # =====================================================
    # ЗАГРУЗКА ЗАЯВОК
    # =====================================================

    if text == "📥 Загрузить заявки":
        await start_import(
            update,
            context,
        )

        return

    # =====================================================
    # ВСЕ ЗАЯВКИ
    # =====================================================

    if text == "📋 Все заявки":

        if user_id != ADMIN_ID:
            await update.message.reply_text(
                "⛔ Доступ запрещён."
            )

            return

        await update.message.reply_text(
            "📋 Раздел «Все заявки» пока "
            "в разработке.",
            reply_markup=ADMIN_PANEL_MENU,
        )

        return

    # =====================================================
    # ТАРИФЫ
    # =====================================================

    if text == "📢 Рассылка":
        if user_id != ADMIN_ID:
            await update.message.reply_text(
                "⛔ Доступ запрещён.",
                reply_markup=get_menu(user_id),
            )
            return

        start_broadcast_session(user_id)

        await update.message.reply_text(
            "📢 РАССЫЛКА\n\n"
            "Напиши текст, который нужно отправить всем пользователям.\n\n"
            "После ввода я покажу предпросмотр и попрошу подтвердить отправку.\n\n"
            "Для отмены: ❌ Отмена",
            reply_markup=ReplyKeyboardMarkup(
                [["❌ Отмена"]],
                resize_keyboard=True,
            ),
        )
        return

    if text == "🔄 Пересчитать заявки":
        if user_id != ADMIN_ID:
            await update.message.reply_text(
                "⛔ Доступ запрещён.",
                reply_markup=get_menu(user_id),
            )
            return

        start_recalc_session(user_id)

        await update.message.reply_text(
            "🔄 ПЕРЕРАСЧЁТ ЗАЯВОК\n\n"
            "Введи начальную дату в формате ДД.ММ.ГГГГ.\n"
            "Например: 01.09.2026\n\n"
            "Для отмены: ❌ Отмена",
            reply_markup=ReplyKeyboardMarkup(
                [["❌ Отмена"]],
                resize_keyboard=True,
            ),
        )
        return

    if text == "⚙️ Тарифы":

        if user_id != ADMIN_ID:
            await update.message.reply_text(
                "⛔ Доступ запрещён."
            )
            return

        await update.message.reply_text(
            "⚙️ Управление тарифами открывается "
            "через кнопки ниже.",
            reply_markup=ADMIN_PANEL_MENU,
        )

        # Для ReplyKeyboard нельзя передать InlineKeyboard,
        # поэтому отправляем отдельное сообщение с кнопками.
        await update.message.reply_text(
            "Открой список тарифов 👇",
            reply_markup=build_tariffs_keyboard(),
        )
        return

    # =====================================================
    # КОРРЕКТИРОВКА
    # =====================================================

    if text == "💸 Корректировка":

        if user_id != ADMIN_ID:
            await update.message.reply_text(
                "⛔ Доступ запрещён."
            )

            return

        await update.message.reply_text(
            "💸 Раздел «Корректировка» пока "
            "в разработке.",
            reply_markup=ADMIN_PANEL_MENU,
        )

        return

    # =====================================================
    # РАССЫЛКА
    # =====================================================

    if text == "📢 Рассылка":

        if user_id != ADMIN_ID:
            await update.message.reply_text(
                "⛔ Доступ запрещён."
            )

            return

        await update.message.reply_text(
            "📢 Раздел «Рассылка» пока "
            "в разработке.",
            reply_markup=ADMIN_PANEL_MENU,
        )

        return

    # =====================================================
    # ЗАРАБОТОК
    # =====================================================

    if text == "💰 Заработок":
        await show_income(
            update
        )

        return

    # =====================================================
    # СЕГОДНЯ
    # =====================================================

    if text == "📅 Сегодня":
        await show_today(
            update
        )

        return

    # =====================================================
    # НЕДЕЛЯ
    # =====================================================

    if text == "📆 Неделя":
        await show_week(
            update
        )

        return

    # =====================================================
    # МЕСЯЦ
    # =====================================================

    if text == "🗓 Месяц":
        await show_month(
            update
        )

        return

    # =====================================================
    # ПОСЛЕДНИЕ ЗАЯВКИ
    # =====================================================

    if text == "📥 Последние заявки":
        await show_recent_earnings(
            update
        )

        return

    # =====================================================
    # НАСТРОЙКИ
    # =====================================================

    if text == "⚙️ Настройки":
        await update.message.reply_text(
            "⚙️ Настройки пока "
            "в разработке.",
            reply_markup=get_menu(user_id),
        )

        return

    # =====================================================
    # ОБЫЧНОЕ СООБЩЕНИЕ / ОДИНОЧНАЯ ЗАЯВКА
    # =====================================================

    await handle_direct_application(
        update,
        user_id,
        text,
    )


# =========================================================
# ЗАПУСК
# =========================================================

def main():
    init_db()

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "done",
            finish_import,
        )
    )

    # ВАЖНО:
    # callback-кнопки админки должны обрабатываться
    # отдельно от обычных текстовых сообщений.
    app.add_handler(
        CallbackQueryHandler(
            handle_admin_callback,
            pattern=r"^admin_",
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    print(
        "🤖 Efin Money Bot запущен!"
    )

    app.run_polling()


if __name__ == "__main__":
    main()
