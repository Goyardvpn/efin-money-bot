import sqlite3
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, CallbackQueryHandler, filters

from config import ADMIN_ID
from database import get_connection


# In-memory admin sessions. The actual projects/files are persistent in SQLite.
KB_SESSIONS = {}


def init_knowledge_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                file_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                mime_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def get_projects():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT id, name, file_id, file_name, mime_type
            FROM knowledge_projects
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()


def get_project(project_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT id, name, file_id, file_name, mime_type
            FROM knowledge_projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()


def add_project(name, file_id, file_name, mime_type=None):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_projects
                (name, file_id, file_name, mime_type, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (name, file_id, file_name, mime_type),
        )
        conn.commit()


def update_project_file(project_id, file_id, file_name, mime_type=None):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE knowledge_projects
            SET file_id = ?, file_name = ?, mime_type = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (file_id, file_name, mime_type, project_id),
        )
        conn.commit()


def delete_project(project_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM knowledge_projects WHERE id = ?",
            (project_id,),
        )
        conn.commit()


def project_name_exists(name):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM knowledge_projects WHERE name = ?",
            (name,),
        ).fetchone()
        return row is not None


def build_cancel_keyboard():
    return ReplyKeyboardMarkup(
        [["❌ Отмена"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def build_user_projects_keyboard():
    rows = []
    for project in get_projects():
        rows.append([
            InlineKeyboardButton(
                f"📄 {project['name']}",
                callback_data=f"kb_project:{project['id']}",
            )
        ])
    rows.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="kb_back")
    ])
    return InlineKeyboardMarkup(rows)


def build_admin_projects_keyboard():
    rows = [
        [InlineKeyboardButton("➕ Добавить проект", callback_data="admin_kb_add")]
    ]
    for project in get_projects():
        rows.append([
            InlineKeyboardButton(
                f"✏️ {project['name']}",
                callback_data=f"admin_kb_replace:{project['id']}",
            ),
            InlineKeyboardButton(
                "🗑",
                callback_data=f"admin_kb_delete:{project['id']}",
            ),
        ])
    rows.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel")
    ])
    return InlineKeyboardMarkup(rows)


async def show_user_knowledge(update, edit=False):
    text = (
        "📚 БАЗА ЗНАНИЙ\n\n"
        "Выбери проект, чтобы получить памятку:"
    )
    markup = build_user_projects_keyboard()
    if edit:
        await update.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


def start_add_session(admin_id):
    KB_SESSIONS[admin_id] = {"mode": "add", "project_id": None}


def start_replace_session(admin_id, project_id):
    KB_SESSIONS[admin_id] = {"mode": "replace", "project_id": project_id}


def finish_session(admin_id):
    KB_SESSIONS.pop(admin_id, None)


def get_session(admin_id):
    return KB_SESSIONS.get(admin_id)


async def show_admin_knowledge(query):
    projects = get_projects()
    text = "📚 БАЗА ЗНАНИЙ — АДМИН\n\n"
    if projects:
        text += "Проекты:\n"
        for project in projects:
            text += f"• {project['name']} — {project['file_name']}\n"
    else:
        text += "Проектов пока нет.\n"
    text += "\nДобавь проект или замени файл памятки."
    await query.edit_message_text(
        text,
        reply_markup=build_admin_projects_keyboard(),
    )


class KnowledgeTextFilter(filters.MessageFilter):
    def filter(self, message):
        if not message or not message.from_user:
            return False
        text = message.text or ""
        if text == "📚 База знаний":
            return True
        return message.from_user.id == ADMIN_ID and get_session(ADMIN_ID) is not None


class KnowledgeDocumentFilter(filters.MessageFilter):
    def filter(self, message):
        if not message or not message.from_user or not message.document:
            return False
        return message.from_user.id == ADMIN_ID and get_session(ADMIN_ID) is not None


async def handle_knowledge_text(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    if text == "📚 База знаний":
        if user_id == ADMIN_ID:
            await update.message.reply_text(
                "📚 Управление базой знаний:",
                reply_markup=build_admin_projects_keyboard(),
            )
        else:
            await show_user_knowledge(update)
        return

    if user_id != ADMIN_ID:
        return

    session = get_session(user_id)
    if not session:
        return

    if text == "❌ Отмена":
        finish_session(user_id)
        await update.message.reply_text(
            "❌ Операция с базой знаний отменена."
        )
        return

    if session["mode"] == "add":
        if not text:
            await update.message.reply_text("❌ Название проекта не может быть пустым.")
            return

        if project_name_exists(text):
            await update.message.reply_text(
                "⚠️ Проект с таким названием уже существует.\n"
                "Введи другое название."
            )
            return

        session["name"] = text
        session["step"] = "file"
        await update.message.reply_text(
            f"✅ Проект «{text}» создан в черновике.\n\n"
            "📎 Теперь отправь файл памятки.\n"
            "Поддерживаются PDF, DOCX, TXT и другие файлы, которые Telegram отправляет как документ.\n\n"
            "Для отмены нажми кнопку ниже 👇",
            reply_markup=build_cancel_keyboard(),
        )
        return


async def handle_knowledge_document(update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    session = get_session(admin_id)
    if not session:
        return

    document = update.message.document
    file_name = document.file_name or "Памятка"
    mime_type = document.mime_type or ""

    if session.get("mode") == "add":
        if session.get("step") != "file" or not session.get("name"):
            return
        add_project(
            session["name"],
            document.file_id,
            file_name,
            mime_type,
        )
        name = session["name"]
        finish_session(admin_id)
        await update.message.reply_text(
            "✅ ПРОЕКТ ДОБАВЛЕН\n\n"
            f"📁 Проект: {name}\n"
            f"📎 Файл: {file_name}\n\n"
            "Пользователи уже могут открыть памятку в 📚 Базе знаний."
        )
        return

    if session.get("mode") == "replace":
        project_id = session.get("project_id")
        project = get_project(project_id)
        if not project:
            finish_session(admin_id)
            await update.message.reply_text("⚠️ Проект не найден.")
            return

        update_project_file(
            project_id,
            document.file_id,
            file_name,
            mime_type,
        )
        finish_session(admin_id)
        await update.message.reply_text(
            "✅ ПАМЯТКА ОБНОВЛЕНА\n\n"
            f"📁 Проект: {project['name']}\n"
            f"📎 Новый файл: {file_name}"
        )


async def handle_knowledge_callback(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data or ""

    if data == "kb_back":
        await query.edit_message_text("Раздел закрыт.")
        return

    if data.startswith("kb_project:"):
        try:
            project_id = int(data.split(":", 1)[1])
        except ValueError:
            return

        project = get_project(project_id)
        if not project:
            await query.answer("Проект не найден.", show_alert=True)
            return

        await context.bot.send_document(
            chat_id=user_id,
            document=project["file_id"],
            caption=f"📚 {project['name']}\n📎 {project['file_name']}",
        )
        return

    if user_id != ADMIN_ID:
        await query.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    if data == "admin_kb_add":
        start_add_session(ADMIN_ID)
        await query.message.reply_text(
            "➕ ДОБАВЛЕНИЕ ПРОЕКТА\n\n"
            "Напиши название проекта.\n"
            "Например: Ozon\n\n"
            "Для отмены нажми кнопку ниже 👇",
            reply_markup=build_cancel_keyboard(),
        )
        return

    if data.startswith("admin_kb_replace:"):
        try:
            project_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        project = get_project(project_id)
        if not project:
            await query.answer("Проект не найден.", show_alert=True)
            return
        start_replace_session(ADMIN_ID, project_id)
        await query.message.reply_text(
            "✏️ ЗАМЕНА ПАМЯТКИ\n\n"
            f"Проект: {project['name']}\n"
            f"Текущий файл: {project['file_name']}\n\n"
            "📎 Отправь новый файл памятки.\n\n"
            "Для отмены нажми кнопку ниже 👇",
            reply_markup=build_cancel_keyboard(),
        )
        return

    if data.startswith("admin_kb_delete:"):
        try:
            project_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        project = get_project(project_id)
        if not project:
            await query.answer("Проект уже удалён.", show_alert=True)
            return
        await query.edit_message_text(
            "🗑 УДАЛЕНИЕ ПРОЕКТА\n\n"
            f"📁 {project['name']}\n"
            f"📎 {project['file_name']}\n\n"
            "Удалить?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "✅ Удалить",
                    callback_data=f"admin_kb_confirm_delete:{project_id}",
                )],
                [InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data="admin_kb_list",
                )],
            ]),
        )
        return

    if data == "admin_kb_list":
        await show_admin_knowledge(query)
        return

    if data.startswith("admin_kb_confirm_delete:"):
        try:
            project_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        delete_project(project_id)
        await query.edit_message_text(
            "✅ Проект удалён.",
            reply_markup=build_admin_projects_keyboard(),
        )


def install(bot_module):
    init_knowledge_db()

    # Добавляем кнопку в существующие меню без изменения bot.py.
    from telegram import ReplyKeyboardMarkup

    bot_module.USER_MENU = ReplyKeyboardMarkup(
        [
            ["💰 Заработок", "📅 Сегодня"],
            ["📆 Неделя", "🗓 Месяц"],
            ["📥 Загрузить заявки", "📥 Последние заявки"],
            ["📚 База знаний"],
            ["⚙️ Настройки"],
        ],
        resize_keyboard=True,
    )

    bot_module.ADMIN_MENU = ReplyKeyboardMarkup(
        [
            ["💰 Заработок", "📅 Сегодня"],
            ["📆 Неделя", "🗓 Месяц"],
            ["📥 Загрузить заявки", "📥 Последние заявки"],
            ["📚 База знаний"],
            ["⚙️ Настройки"],
            ["🛠 Админ-панель"],
        ],
        resize_keyboard=True,
    )

    bot_module.ADMIN_PANEL_MENU = ReplyKeyboardMarkup(
        [
            ["👥 Пользователи"],
            ["📊 Общая статистика"],
            ["📋 Все заявки"],
            ["⚙️ Тарифы"],
            ["🔄 Пересчитать заявки"],
            ["🔧 Технический режим"],
            ["📚 База знаний"],
            ["💸 Корректировка"],
            ["📢 Рассылка"],
            ["⬅️ Назад"],
        ],
        resize_keyboard=True,
    )

    # Инжектируем обработчики до универсальных обработчиков bot.py.
    from telegram.ext import Application
    original_add_handler = Application.add_handler
    installed_apps = set()

    def patched_add_handler(self, handler, group=0):
        app_id = id(self)
        if app_id not in installed_apps:
            original_add_handler(
                self,
                CallbackQueryHandler(
                    handle_knowledge_callback,
                    pattern=r"^(kb_|admin_kb_)"
                ),
                group=-1,
            )
            original_add_handler(
                self,
                MessageHandler(
                    KnowledgeDocumentFilter(),
                    handle_knowledge_document,
                ),
                group=-1,
            )
            original_add_handler(
                self,
                MessageHandler(
                    KnowledgeTextFilter(),
                    handle_knowledge_text,
                ),
                group=-1,
            )
            installed_apps.add(app_id)
        return original_add_handler(self, handler, group)

    Application.add_handler = patched_add_handler
